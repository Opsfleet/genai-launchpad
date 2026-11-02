"""Offline evaluation with ground truth (`bootcamp.py eval`): golden questions -> your agent -> AgentCore batch eval.

1. The golden file is synced to your managed dataset and a published version is read back (`datasets.sync`).
2. Each question goes to your deployed agent in a fresh session, signed in as a brand-new throwaway Cognito user (a
   fresh actor: no memory can mask a regression); the users are deleted once every question is answered.
3. Once the sessions' telemetry is in CloudWatch, one `StartBatchEvaluation` job scores exactly those sessions,
   with each item's ground truth attached as session metadata (expected answer -> Builtin.Correctness, assertions
   -> Builtin.GoalSuccessRate, expected tools -> Builtin.TrajectoryAnyOrderMatch).
4. Per-session scores are read from the job's result log stream and the report is saved for `eval --last`.
"""

import json
import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from bootcamp_cli import agentcore, evaluators, observe, progress, users
from bootcamp_cli.config import ROOT
from bootcamp_cli.datasets import DatasetVersion, tags
from bootcamp_cli.evaluators import short_name
from bootcamp_cli.golden import GoldenItem

log = logging.getLogger(__name__)

SESSION_PREFIX = "bootcamp-eval-"
"""Sessions opened by `eval`, so they are easy to spot in traces and scores."""
PASS_SCORE = 0.75
"""An item passes when every evaluator that scored it gave at least this (Correctness 'partially' is 0.5)."""
MIN_PASS_RATE = 0.8
"""`eval` exits 1 below this share of passing items (override with --min-pass)."""
DEFAULT_LIMIT = 10
MAX_QUESTIONS = 25
"""Most answers one `eval` gets scored (items x variants): AgentCore's built-in judges bill the account, not LiteLLM."""
MAX_DATASET_ITEMS = 50
"""Largest golden file `eval` accepts; keep golden sets small and pick items with --limit."""
INVOKE_WORKERS = 4
INVOKE_ATTEMPTS = 2
TELEMETRY_TIMEOUT_SECONDS = 900
TELEMETRY_POLL_SECONDS = 30
SETTLE_SECONDS = 120
"""Extra wait after every session shows up in CloudWatch: the evaluation service's own queries see new telemetry a
few minutes after ingestion, and a session evaluated too early fails with LogEventMissingException."""
RETRIES = 2
RETRY_SECONDS = 90
INCOMPLETE_ERROR = "LogEventMissingException"
NO_SPANS_MESSAGE = "has no spans to evaluate"
"""Both mean a session's telemetry was not complete yet when the job read it (seen in dry runs)."""
BATCH_POLL_SECONDS = 20
BATCH_TIMEOUT_SECONDS = 1800
TERMINAL = {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED", "STOPPED"}
KEEP_BATCHES = 5
"""`eval` keeps your newest batch evaluation jobs (in the console and the API) and deletes older ones."""
REPORT_DIR = ROOT / ".build"
ANSWER_CHARS = 60
SCORE_WIDTH = 11
NAME_CHARS = 17
"""Score columns are as wide as the longest evaluator name, up to NAME_CHARS (longer names are cut)."""


@dataclass
class Result:
    """One golden item: what the agent said and how the evaluators scored it."""

    id: str
    question: str
    expected: str
    session: str
    actor: str
    answer: str = ""
    error: str = ""
    scores: dict[str, float] = field(default_factory=dict)
    explanations: dict[str, str] = field(default_factory=dict)
    variant: str = ""

    def passed(self) -> bool:
        """Answered, scored by at least one evaluator, and every score at least PASS_SCORE."""
        return not self.error and bool(self.scores) and all(value >= PASS_SCORE for value in self.scores.values())


@dataclass
class Report:
    """A finished `eval` run (saved as JSON for `eval --last`)."""

    dataset: str
    version: str
    batch_id: str
    status: str
    started: str
    evaluators: list[str]
    results: list[Result]
    averages: dict[str, float] = field(default_factory=dict)
    spend_usd: float | None = None
    variants: list[str] = field(default_factory=list)


def new_result(item: GoldenItem, actor: str, variant: str = "") -> Result:
    """A fresh session for one item, asked as `actor` (a brand-new user), optionally with a prompt variant."""
    session = f"{SESSION_PREFIX}{uuid.uuid4().hex}"
    return Result(item.id, item.question, item.expected, session, actor, variant=variant)


def ask(out: dict, token: str, result: Result) -> Result:
    """Send one golden question to the agent, recording the answer or the error (one retry in a new session)."""
    extra = {"variant": result.variant} if result.variant else None
    for _ in range(INVOKE_ATTEMPTS):
        try:
            body = agentcore.invoke_agent_body(out, token, result.question, result.session, extra_payload=extra)
        except Exception as error:  # noqa: BLE001 - one failed question must not stop the run
            result.error = one_line(f"{type(error).__name__}: {error}", 300)
            result.session = f"{SESSION_PREFIX}{uuid.uuid4().hex}"
            continue
        result.answer, result.error = str(body.get("response", "")).strip(), variant_error(result.variant, body)
        break
    return result


def variant_error(requested: str, body: dict) -> str:
    """Why a reply does not count for the requested prompt variant ("" when it does, or none was requested)."""
    applied = body.get("variant")
    if not requested or applied == requested:
        return ""
    return (f"the agent applied variant {applied or '(none)'}, not {requested}: define it in "
            "phase2/app/agent/prompt_variants.py and `deploy`")  # fmt: skip


def ask_all(session, out: dict, items: list[GoldenItem], variants: list[str] | None = None) -> list[Result]:
    """Ask every item (once per prompt variant) concurrently, each in its own new session as its own throwaway user."""
    plan = [(item, variant) for variant in (variants or [""]) for item in items]
    with users.temporary_users(session, out, len(plan), "eval") as accounts:
        asks = [
            (new_result(item, name, variant), token)
            for (item, variant), (name, token) in zip(plan, accounts, strict=True)
        ]
        log.info("Asking your agent %d golden questions (%d at a time, ~1-3 min)...", len(asks), INVOKE_WORKERS)
        with progress.heartbeat("asking golden questions"), ThreadPoolExecutor(INVOKE_WORKERS) as pool:
            return list(pool.map(lambda pair: ask(out, pair[1], pair[0]), asks))


def sessions_seen(logs, groups: list[str], session_ids: list[str], hours: float = 1) -> set[str]:
    """Which of `session_ids` already have records in all of `groups` (each queried separately)."""
    quoted = ", ".join(f'"{observe.check_session_id(session)}"' for session in session_ids)
    query = f"filter attributes.session.id in [{quoted}] | stats count(*) by attributes.session.id as session"
    seen = set(session_ids)
    for group in groups:
        seen &= {row.get("session", "") for row in observe.run_query(logs, [group], query, hours)}
    return seen


def wait_for_telemetry(logs, groups: list[str], session_ids: list[str]) -> None:
    """Wait until every session has spans and runtime logs in CloudWatch (usually 2-5 min), plus a settle time."""
    deadline = time.monotonic() + TELEMETRY_TIMEOUT_SECONDS
    with progress.heartbeat("waiting for the sessions' telemetry in CloudWatch"):
        while len(seen := sessions_seen(logs, groups, session_ids)) < len(session_ids):
            if time.monotonic() > deadline:
                log.warning("Only %d/%d sessions reached CloudWatch; evaluating those.", len(seen), len(session_ids))
                return
            time.sleep(TELEMETRY_POLL_SECONDS)
        time.sleep(SETTLE_SECONDS)


def session_metadata(result: Result, item: GoldenItem, dataset: DatasetVersion) -> dict:
    """One session's ground truth for the batch job, from the dataset item it answered."""
    truth: dict = {
        "turns": [{"input": {"prompt": item.question}, "expectedResponse": {"text": item.expected}}],
        "assertions": [{"text": text} for text in item.checks()],
    }
    if item.tools:
        truth["expectedTrajectory"] = {"toolNames": list(item.tools)}
    return {
        "sessionId": result.session,
        "testScenarioId": item.id,
        "groundTruth": {"inline": truth},
        "metadata": {"dataset": dataset.name, "datasetVersion": dataset.version}
        | ({"variant": result.variant} if result.variant else {}),
    }


def batch_name(participant: str) -> str:
    """A unique job name under the participant's awsworkshop_<name>_ prefix (letters, digits, _; max 48)."""
    return f"awsworkshop_{participant}_golden_{datetime.now(UTC):%m%d%H%M%S}"


def start_batch(client, participant: str, out: dict, metadata: list[dict], evaluators: list[str]) -> str:
    """Start one batch evaluation over exactly the given sessions; returns its id."""
    response = client.start_batch_evaluation(
        batchEvaluationName=batch_name(participant),
        description="bootcamp.py eval: golden dataset with ground truth",
        evaluators=[{"evaluatorId": evaluator} for evaluator in evaluators],
        dataSourceConfig={
            "cloudWatchLogs": {
                "serviceNames": [observe.service_name(participant)],
                "logGroupNames": [out["agent_log_group"]],
                "filterConfig": {"sessionIds": [item["sessionId"] for item in metadata]},
            }
        },
        evaluationMetadata={"sessionMetadata": metadata},
        outputConfig={"cloudWatchConfig": {"resultDestination": "SOURCE_LOG_GROUP"}},
        tags=tags(participant),
        clientToken=str(uuid.uuid4()),
    )
    log.info("Started batch evaluation %s (%s)", response["batchEvaluationName"], response["batchEvaluationId"])
    return response["batchEvaluationId"]


def wait_batch(client, batch_id: str) -> dict:
    """Poll the job until it reaches a terminal state (usually 2-5 min).

    Raises:
        RuntimeError: The job did not finish within BATCH_TIMEOUT_SECONDS.
    """
    deadline = time.monotonic() + BATCH_TIMEOUT_SECONDS
    with progress.heartbeat("waiting for the batch evaluation"):
        while (job := client.get_batch_evaluation(batchEvaluationId=batch_id))["status"] not in TERMINAL:
            if time.monotonic() > deadline:
                raise RuntimeError(f"batch evaluation {batch_id} still {job['status']}; check it later with --last")
            time.sleep(BATCH_POLL_SECONDS)
    return job


def averages(results: list[Result], evaluator_ids: list[str]) -> dict[str, float]:
    """Evaluator id -> mean score over the results it scored (the job's own summary omits code-based evaluators)."""
    means = {}
    for evaluator in evaluator_ids:
        scores = [result.scores[evaluator] for result in results if evaluator in result.scores]
        if scores:
            means[evaluator] = sum(scores) / len(scores)
    return means


def result_events(logs, job: dict, source_group: str) -> list[dict]:
    """The job's per-session result events, parsed from its output log stream (in the agent's own log group)."""
    config = (job.get("outputConfig") or {}).get("cloudWatchConfig") or {}
    group, stream = config.get("logGroupName") or source_group, config.get("logStreamName")
    if not stream:
        return []
    params, events = {"logGroupName": group, "logStreamName": stream, "startFromHead": True}, []
    while True:
        page = logs.get_log_events(**params)
        events += [observe.parse_record(event["message"]) for event in page["events"]]
        if not page["events"] or page["nextForwardToken"] == params.get("nextToken"):
            return events
        params["nextToken"] = page["nextForwardToken"]


def attach_scores(results: list[Result], events: list[dict], requested: list[str]) -> None:
    """Copy each event's score and explanation onto its session's result (the lowest per evaluator wins).

    Scores are keyed by the requested evaluator id, whether an event names its evaluator by id or by name.
    """
    by_session = {result.session: result for result in results}
    for event in events:
        attributes = event.get("attributes") or {}
        result = by_session.get(attributes.get("session.id", ""))
        evaluator, score = attributes.get("gen_ai.evaluation.name"), attributes.get("gen_ai.evaluation.score.value")
        evaluator = evaluator and evaluators.canonical(evaluator, requested)
        if result is None or not evaluator or score is None or float(score) > result.scores.get(evaluator, 2.0):
            continue
        result.scores[evaluator] = float(score)
        result.explanations[evaluator] = str(attributes.get("gen_ai.evaluation.explanation", ""))


def report_path(participant: str) -> Path:
    """Where the participant's latest `eval` report is saved (git-ignored)."""
    return REPORT_DIR / f"eval_{participant}_last.json"


def save(participant: str, report: Report) -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    report_path(participant).write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")


def load_last(participant: str) -> Report:
    """The latest saved report.

    Raises:
        RuntimeError: No `eval` has been run on this machine yet.
    """
    try:
        data = json.loads(report_path(participant).read_text(encoding="utf-8"))
    except OSError as error:
        raise RuntimeError("No saved `eval` run on this machine yet: run `uv run bootcamp.py eval` first.") from error
    data["results"] = [Result(**item) for item in data["results"]]
    return Report(**data)


def one_line(text: str, limit: int) -> str:
    """`text` on one line, cut to `limit` characters."""
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def pass_rate(results: list[Result]) -> float:
    """Share of `results` that passed (0 for none)."""
    return sum(result.passed() for result in results) / max(len(results), 1)


def score_width(names: list[str]) -> int:
    """Column width for evaluator scores: the longest short name, between SCORE_WIDTH and NAME_CHARS."""
    return max(SCORE_WIDTH, min(NAME_CHARS, max((len(name) for name in names), default=0)))


def render(report: Report) -> list[str]:
    """The result table, then pass rate, per-evaluator averages and spend."""
    lines = [f"dataset {report.dataset} v{report.version}, batch {report.batch_id} ({report.status})"]
    lines += table(report.results, report.evaluators)
    lines.append("averages: " + ", ".join(f"{short_name(k)}={v:.2f}" for k, v in report.averages.items()))
    return lines + spend_lines(report)


def spend_lines(report: Report) -> list[str]:
    """The run's LiteLLM spend (the agent's calls and rubric_judge's judge calls), when it was measured."""
    if report.spend_usd is None:
        return []
    return [f"LiteLLM spend for this run: ${report.spend_usd:.4f} (agent + rubric_judge; built-in judges are billed "
            "by AgentCore)"]  # fmt: skip


def table(results: list[Result], evaluator_ids: list[str]) -> list[str]:
    """Header, one row per result and the PASS RATE line."""
    names = [short_name(evaluator) for evaluator in evaluator_ids]
    width = score_width(names)
    header = f"{'id':<22} {'expected':<34} {'got':<{ANSWER_CHARS}} " + " ".join(f"{n[:width]:>{width}}" for n in names)
    passed = sum(result.passed() for result in results)
    footer = f"PASS RATE {passed}/{len(results)} ({pass_rate(results):.0%})"
    return [header, *(_row(result, evaluator_ids, width) for result in results), footer]


def _row(result: Result, evaluator_ids: list[str], width: int = SCORE_WIDTH) -> str:
    """One table row: verdict, id, expected, the agent's answer (or error) and each evaluator's score."""
    got = one_line(result.error or result.answer or "(empty)", ANSWER_CHARS)
    scores = " ".join(
        f"{result.scores[e]:>{width}.2f}" if e in result.scores else f"{'-':>{width}}" for e in evaluator_ids
    )
    verdict = "PASS" if result.passed() else "FAIL"
    return f"[{verdict}] {result.id[:15]:<15} {one_line(result.expected, 34):<34} {got:<{ANSWER_CHARS}} {scores}"


def failures(report: Report) -> list[str]:
    """Why each failed item failed: the lowest-scoring evaluator's explanation."""
    lines = []
    for result in report.results:
        if result.passed():
            continue
        if result.error or not result.scores:
            tag = f"[{result.variant}] " if result.variant else ""
            lines.append(f"- {tag}{result.id}: {result.error or 'not scored (no telemetry for this session?)'}")
            continue
        worst = min(result.scores, key=result.scores.__getitem__)
        explanation = one_line(result.explanations.get(worst, ""), 220)
        tag = f"[{result.variant}] " if result.variant else ""
        lines.append(f"- {tag}{result.id}: {short_name(worst)}={result.scores[worst]:.2f} {explanation}")
    return lines


@dataclass(frozen=True)
class RunOptions:
    """What one `eval` run asks and how it scores: item limit, `--evaluators` spec and prompt variants."""

    limit: int = DEFAULT_LIMIT
    evaluators: str = evaluators.DEFAULT_SPEC
    variants: tuple[str, ...] = ()


def check_size(dataset_items: int, options: RunOptions) -> None:
    """Refuse runs that would have the built-in judges score more than MAX_QUESTIONS answers.

    Raises:
        RuntimeError: The golden file is too large, or --limit x variants asks too many questions.
    """
    if dataset_items > MAX_DATASET_ITEMS:
        raise RuntimeError(f"The golden file has {dataset_items} items; keep it to {MAX_DATASET_ITEMS} at most.")
    asks = min(max(options.limit, 0), dataset_items) * max(1, len(options.variants))
    if options.limit < 1 or asks > MAX_QUESTIONS:
        raise RuntimeError(
            f"This run would score {asks} answers; the limit is 1 to {MAX_QUESTIONS} per run (items x variants), "
            "because AgentCore's built-in judges are billed to the class account, not your LiteLLM budget."
        )


def limited_items(dataset: DatasetVersion, limit: int) -> list[GoldenItem]:
    """The first `limit` items, saying so when the dataset holds fewer (`--limit 20` on an 11-item golden set)."""
    if limit > len(dataset.items):
        log.info("The dataset has %d items (limit %d): asking all of them.", len(dataset.items), limit)
    return dataset.items[:limit]


def run(session, out: dict, participant: str, dataset: DatasetVersion, options: RunOptions) -> Report:
    """Ask the first `limit` items of a dataset version (once per variant), batch-evaluate the sessions, report.

    Raises:
        RuntimeError: The agent is not deployed, an evaluator is unknown, or no question got an answer.
    """
    if not out.get("agent_runtime_arn"):
        raise RuntimeError("No agent deployed yet: run `uv run bootcamp.py up 4` (or later) first.")
    items = limited_items(dataset, options.limit)
    chosen = evaluators.resolve(options.evaluators, items, out.get("custom_evaluators") or {})
    results = ask_all(session, out, items, list(options.variants))
    job, events = evaluate_sessions(session, out, participant, answered_metadata(results, items, dataset), chosen)
    attach_scores(results, events, chosen)
    delete_batches(session.client("bedrock-agentcore"), participant, keep=KEEP_BATCHES)
    return Report(dataset.name, dataset.version, job["batchEvaluationId"], job["status"], str(job["createdAt"]),
                  chosen, results, averages(results, chosen), variants=list(options.variants))  # fmt: skip


def answered_metadata(results: list[Result], items: list[GoldenItem], dataset: DatasetVersion) -> list[dict]:
    """Ground-truth session metadata for every answered result.

    Raises:
        RuntimeError: No question got an answer.
    """
    by_id = {item.id: item for item in items}
    metadata = [session_metadata(result, by_id[result.id], dataset) for result in results if not result.error]
    if not metadata:
        raise RuntimeError(f"Every question failed, e.g. {results[0].error}")
    return metadata


def evaluate_sessions(
    session, out: dict, participant: str, metadata: list[dict], evaluators: list[str]
) -> tuple[dict, list[dict]]:
    """Wait for the sessions' telemetry, then batch-evaluate them; returns the finished job and its result events.

    A job started while some telemetry is not yet queryable fails those sessions; it is deleted and retried.
    """
    logs, client = session.client("logs"), session.client("bedrock-agentcore")
    wait_for_telemetry(logs, [observe.SPANS_GROUP, out["agent_log_group"]], [item["sessionId"] for item in metadata])
    for _ in range(RETRIES):
        job, events = run_batch(logs, client, participant, out, metadata, evaluators)
        if not incomplete(events):
            return job, events
        log.info("Some telemetry was not queryable yet; retrying the evaluation in %ss", RETRY_SECONDS)
        client.delete_batch_evaluation(batchEvaluationId=job["batchEvaluationId"])
        time.sleep(RETRY_SECONDS)
    return run_batch(logs, client, participant, out, metadata, evaluators)


def run_batch(
    logs, client, participant: str, out: dict, metadata: list[dict], evaluators: list[str]
) -> tuple[dict, list[dict]]:
    """Start one batch job, wait for it and read its per-session result events."""
    job = wait_batch(client, start_batch(client, participant, out, metadata, evaluators))
    return job, result_events(logs, job, out["agent_log_group"])


def incomplete(events: list[dict]) -> bool:
    """Whether any session failed because its telemetry was not complete yet when the job read it."""
    return any(_incomplete(event.get("attributes") or {}) for event in events)


def _incomplete(attributes: dict) -> bool:
    message = str(attributes.get("error.message", ""))
    return attributes.get("error.type") == INCOMPLETE_ERROR or NO_SPANS_MESSAGE in message


def participant_batches(client, participant: str) -> list[dict]:
    """The participant's batch evaluation jobs (named awsworkshop_<name>_*), newest first."""
    prefix = f"awsworkshop_{participant}_"
    pages = client.get_paginator("list_batch_evaluations").paginate()
    jobs = [job for page in pages for job in page["batchEvaluations"] if job["batchEvaluationName"].startswith(prefix)]
    return sorted(jobs, key=lambda job: job["createdAt"], reverse=True)


def delete_batches(client, participant: str, keep: int = 0) -> None:
    """Stop and delete the participant's batch evaluation jobs, except the newest `keep` (all of them on `down`)."""
    for job in participant_batches(client, participant)[keep:]:
        if job["status"] in {"PENDING", "IN_PROGRESS"}:
            client.stop_batch_evaluation(batchEvaluationId=job["batchEvaluationId"])
        if job["status"] != "DELETING":
            client.delete_batch_evaluation(batchEvaluationId=job["batchEvaluationId"])
            log.log(logging.DEBUG if keep else logging.INFO, "Deleted batch evaluation %s", job["batchEvaluationName"])
