"""Your managed AgentCore evaluation dataset (`awsworkshop_<name>_golden`), kept in sync with the golden file.

Terraform's AWS provider has no dataset resource, so the CLI manages it with boto3. `sync` is idempotent: it creates
the dataset on first use, and when the file changed it replaces the draft's examples and publishes a new numbered
version; an unchanged file reuses the latest version. Evaluations always run against a published version, so a
result can be traced back to exactly the questions it used. `delete_all` removes it on `down`.
"""

import logging
import time
from dataclasses import dataclass
from operator import itemgetter

from bootcamp_cli.golden import GoldenItem, from_example, to_example

log = logging.getLogger(__name__)

SCHEMA = "AGENTCORE_EVALUATION_PREDEFINED_V1"
NAME_TEMPLATE = "awsworkshop_{participant}_golden"
POLL_SECONDS = 2
MAX_POLLS = 90
EXAMPLES_PAGE = 100
FAILED = {"CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED"}


@dataclass(frozen=True)
class DatasetVersion:
    """A published version of the participant's dataset and the items it holds."""

    dataset_id: str
    name: str
    version: str
    items: list[GoldenItem]
    changed: bool


def dataset_name(participant: str) -> str:
    """The participant's dataset name (the awsworkshop_<name>_ prefix their role may manage)."""
    return NAME_TEMPLATE.format(participant=participant)


def tags(participant: str) -> dict[str, str]:
    """Tags every participant evaluation resource carries (the role may only create resources tagged as itself)."""
    return {"Project": "genai-bootcamp", "Participant": participant}


def find(control, name: str) -> dict | None:
    """The dataset summary named `name`, or None."""
    for page in control.get_paginator("list_datasets").paginate():
        for dataset in page["datasets"]:
            if dataset["datasetName"] == name:
                return dataset
    return None


def wait_ready(control, dataset_id: str) -> dict:
    """Poll until the dataset leaves CREATING/UPDATING.

    Raises:
        RuntimeError: The dataset ended in a failed state or did not settle in time.
    """
    for _ in range(MAX_POLLS):
        dataset = control.get_dataset(datasetId=dataset_id)
        if dataset["status"] in FAILED:
            raise RuntimeError(f"dataset {dataset_id} is {dataset['status']}: {dataset.get('failureReason')}")
        if not dataset["status"].endswith("ING"):
            return dataset
        time.sleep(POLL_SECONDS)
    raise RuntimeError(f"dataset {dataset_id} still {dataset['status']} after {POLL_SECONDS * MAX_POLLS}s")


def examples(control, dataset_id: str, version: str | None = None) -> list[dict]:
    """Every example of the draft (or of a published `version`)."""
    params = {"datasetId": dataset_id, "maxResults": EXAMPLES_PAGE} | ({"datasetVersion": version} if version else {})
    found: list[dict] = []
    while True:
        page = control.list_dataset_examples(**params)
        found += page["examples"]
        if not page.get("nextToken"):
            return found
        params["nextToken"] = page["nextToken"]


def latest_version(control, dataset_id: str) -> str | None:
    """Highest published version number, or None before the first publish."""
    versions = control.list_dataset_versions(datasetId=dataset_id).get("versions", [])
    numbers = [int(item["datasetVersion"]) for item in versions if item["datasetVersion"].isdigit()]
    return str(max(numbers)) if numbers else None


def _comparable(example: dict) -> dict:
    """An example without its service-assigned exampleId."""
    return {key: value for key, value in example.items() if key != "exampleId"}


def same_examples(stored: list[dict], wanted: list[dict]) -> bool:
    """Whether a version holds exactly the wanted examples (order-insensitive)."""
    by_id = itemgetter("scenario_id")
    return sorted(map(_comparable, stored), key=by_id) == sorted(wanted, key=by_id)


def create(control, participant: str, wanted: list[dict]) -> str:
    """Create the dataset with `wanted` as its draft examples; returns its id once ACTIVE."""
    response = control.create_dataset(
        datasetName=dataset_name(participant),
        description="Golden questions with ground truth for bootcamp.py eval",
        schemaType=SCHEMA,
        source={"inlineExamples": {"examples": wanted}},
        tags=tags(participant),
    )
    wait_ready(control, response["datasetId"])
    log.info("Created dataset %s", dataset_name(participant))
    return response["datasetId"]


def replace_draft(control, dataset_id: str, wanted: list[dict]) -> None:
    """Make the draft hold exactly `wanted`: delete every current example, then add the new ones."""
    current = [example["exampleId"] for example in examples(control, dataset_id)]
    if current:
        control.delete_dataset_examples(datasetId=dataset_id, exampleIds=current)
        wait_ready(control, dataset_id)
    control.add_dataset_examples(datasetId=dataset_id, source={"inlineExamples": {"examples": wanted}})
    wait_ready(control, dataset_id)


def publish(control, dataset_id: str) -> str:
    """Publish the draft as a new numbered version and return its number."""
    version = control.create_dataset_version(datasetId=dataset_id)["datasetVersion"]
    wait_ready(control, dataset_id)
    return version


def sync(control, participant: str, items: list[GoldenItem]) -> DatasetVersion:
    """Make the managed dataset's latest version hold `items` (create/replace + publish only when needed)."""
    wanted, name = [to_example(item) for item in items], dataset_name(participant)
    existing = find(control, name)
    dataset_id = existing["datasetId"] if existing else create(control, participant, wanted)
    version = latest_version(control, dataset_id)
    unchanged = version is not None and same_examples(examples(control, dataset_id, version), wanted)
    if not unchanged:
        if existing:
            replace_draft(control, dataset_id, wanted)
        version = publish(control, dataset_id)
        log.info("Published %s version %s (%d examples)", name, version, len(wanted))
    stored = examples(control, dataset_id, version)
    return DatasetVersion(dataset_id, name, str(version), [from_example(item) for item in stored], not unchanged)


def delete_all(control, participant: str) -> None:
    """Delete the participant's dataset (every version and the draft), if it exists."""
    existing = find(control, dataset_name(participant))
    if existing:
        control.delete_dataset(datasetId=existing["datasetId"])
        log.info("Deleted dataset %s", existing["datasetName"])
