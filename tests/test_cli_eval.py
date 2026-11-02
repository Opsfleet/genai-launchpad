"""`bootcamp.py eval`: golden file parsing, managed-dataset sync, ground-truth metadata and scoring (no AWS calls)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import datasets, evaluate, evaluators, golden  # noqa: E402
from bootcamp_cli.golden import GoldenItem  # noqa: E402

ITEM = GoldenItem("eng", "How many in Engineering?", "481 employees.")
TOOL_ITEM = GoldenItem("sales", "Sales headcount?", "360.", ("Uses the database.",), ("data_agent",))


def test_shipped_golden_file_is_valid_and_small() -> None:
    items = golden.load_items()
    assert 6 <= len(items) <= 14
    assert {"total-headcount", "non-us-weather", "delete-refused"} <= {item.id for item in items}


def test_csv_matches_yaml_columns(tmp_path: Path) -> None:
    csv_file = tmp_path / "golden.csv"
    csv_file.write_text(
        "id,question,expected,assertions,tools\nsales,Sales headcount?,360.,Uses the database.,data_agent\n",
        encoding="utf-8",
    )
    assert golden.load_items(csv_file) == [TOOL_ITEM]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("- {id: a, question: q}\n", "has no expected"),
        ("- {id: 'a b', question: q, expected: e}\n", "must be 1-64"),
        ("- {id: a, question: q, expected: e}\n- {id: a, question: q, expected: e}\n", "duplicate ids a"),
        ("id: a\n", "expected a list"),
    ],
)
def test_invalid_files_are_rejected(tmp_path: Path, text: str, problem: str) -> None:
    path = tmp_path / "golden.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(RuntimeError, match=problem):
        golden.load_items(path)


def test_example_round_trip_and_default_assertion() -> None:
    example = golden.to_example(ITEM)
    assert example["assertions"] == ["The final answer agrees with this reference answer: 481 employees."]
    assert "expected_trajectory" not in example
    assert golden.from_example({"exampleId": "x", **golden.to_example(TOOL_ITEM)}) == TOOL_ITEM


def test_same_examples_ignores_ids_and_order() -> None:
    wanted = [golden.to_example(ITEM), golden.to_example(TOOL_ITEM)]
    stored = [{"exampleId": "2", **wanted[1]}, {"exampleId": "1", **wanted[0]}]
    assert datasets.same_examples(stored, wanted)
    assert not datasets.same_examples(stored[:1], wanted)


class FakeControl:
    """Dataset API stand-in: one dataset whose published versions are snapshots of the draft."""

    def __init__(self, exists: bool) -> None:
        self.draft: list[dict] = []
        self.versions: dict[str, list[dict]] = {}
        self.exists, self.calls = exists, []

    def get_paginator(self, _operation: str):
        found = [{"datasetName": "awsworkshop_bob_golden", "datasetId": "ds-1"}] if self.exists else []
        return type("Paginator", (), {"paginate": lambda _self: [{"datasets": found}]})()

    def create_dataset(self, source: dict, **_) -> dict:
        self.calls.append("create")
        self.exists, self.draft = True, list(source["inlineExamples"]["examples"])
        return {"datasetId": "ds-1"}

    def get_dataset(self, datasetId: str) -> dict:  # noqa: N803
        return {"status": "ACTIVE"}

    def list_dataset_versions(self, datasetId: str) -> dict:  # noqa: N803
        return {"versions": [{"datasetVersion": number} for number in self.versions]}

    def list_dataset_examples(self, datasetId: str, maxResults: int, datasetVersion: str = "") -> dict:  # noqa: N803
        rows = self.versions[datasetVersion] if datasetVersion else self.draft
        return {"examples": [{"exampleId": str(index), **row} for index, row in enumerate(rows)]}

    def delete_dataset_examples(self, datasetId: str, exampleIds: list[str]) -> None:  # noqa: N803
        self.calls.append("delete-examples")
        self.draft = []

    def add_dataset_examples(self, datasetId: str, source: dict) -> None:  # noqa: N803
        self.calls.append("add-examples")
        self.draft = list(source["inlineExamples"]["examples"])

    def create_dataset_version(self, datasetId: str) -> dict:  # noqa: N803
        number = str(len(self.versions) + 1)
        self.versions[number] = list(self.draft)
        self.calls.append(f"publish-{number}")
        return {"datasetVersion": number}


def test_sync_creates_publishes_and_then_is_idempotent() -> None:
    control = FakeControl(exists=False)
    first = datasets.sync(control, "bob", [ITEM])
    second = datasets.sync(control, "bob", [ITEM])
    assert (first.version, first.changed, second.version, second.changed) == ("1", True, "1", False)
    assert control.calls == ["create", "publish-1"]
    assert second.items == [GoldenItem(ITEM.id, ITEM.question, ITEM.expected, ITEM.checks())]


def test_sync_replaces_the_draft_and_publishes_a_new_version_on_change() -> None:
    control = FakeControl(exists=False)
    datasets.sync(control, "bob", [ITEM])
    changed = datasets.sync(control, "bob", [ITEM, TOOL_ITEM])
    assert (changed.version, [item.id for item in changed.items]) == ("2", ["eng", "sales"])
    assert control.calls[2:] == ["delete-examples", "add-examples", "publish-2"]


def test_session_metadata_carries_ground_truth() -> None:
    result = evaluate.new_result(TOOL_ITEM, "eval-1")
    dataset = datasets.DatasetVersion("ds-1", "awsworkshop_bob_golden", "3", [TOOL_ITEM], False)
    metadata = evaluate.session_metadata(result, TOOL_ITEM, dataset)
    assert metadata["sessionId"].startswith(evaluate.SESSION_PREFIX) and len(metadata["sessionId"]) >= 33
    assert metadata["testScenarioId"] == "sales"
    assert metadata["groundTruth"]["inline"] == {
        "turns": [{"input": {"prompt": "Sales headcount?"}, "expectedResponse": {"text": "360."}}],
        "assertions": [{"text": "Uses the database."}],
        "expectedTrajectory": {"toolNames": ["data_agent"]},
    }
    assert evaluators.builtin_for([ITEM]) == list(evaluators.BUILTIN)
    assert evaluators.builtin_for([ITEM, TOOL_ITEM])[-1] == evaluators.TRAJECTORY


def event(session: str, evaluator: str, score: float | None = None, error: str = "") -> dict:
    attributes = {"session.id": session, "gen_ai.evaluation.name": evaluator, "gen_ai.evaluation.explanation": "why"}
    if score is not None:
        attributes["gen_ai.evaluation.score.value"] = score
    return {"attributes": attributes | ({"error.type": error} if error else {})}


def test_scores_keep_the_lowest_per_evaluator_and_decide_pass() -> None:
    good, bad = evaluate.new_result(ITEM, "eval-1"), evaluate.new_result(TOOL_ITEM, "eval-1")
    events = [event(good.session, "Builtin.Correctness", 1.0), event(bad.session, "Builtin.Correctness", 1.0),
              event(bad.session, "Builtin.Correctness", 0.5), event("other", "Builtin.Correctness", 0.0)]  # fmt: skip
    evaluate.attach_scores([good, bad], events, ["Builtin.Correctness"])
    assert (good.scores, bad.scores) == ({"Builtin.Correctness": 1.0}, {"Builtin.Correctness": 0.5})
    assert good.passed() and not bad.passed()
    assert not evaluate.new_result(ITEM, "eval-1").passed()


def test_incomplete_telemetry_is_detected() -> None:
    assert evaluate.incomplete([event("s", "Builtin.Correctness", error=evaluate.INCOMPLETE_ERROR)])
    no_spans = event("s", "Builtin.Correctness", error="ValidationException")
    no_spans["attributes"]["error.message"] = "Provided input has no spans to evaluate. Please ensure ..."
    assert evaluate.incomplete([no_spans])
    assert not evaluate.incomplete([event("s", "Builtin.Correctness", 1.0)])


def test_report_round_trip_and_render(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evaluate, "REPORT_DIR", tmp_path)
    passed, failed = evaluate.new_result(ITEM, "eval-1"), evaluate.new_result(TOOL_ITEM, "eval-1")
    passed.answer, passed.scores = "Engineering has **481**.", {"Builtin.Correctness": 1.0}
    failed.answer, failed.scores = "About 500.", {"Builtin.Correctness": 0.0}
    failed.explanations = {"Builtin.Correctness": "Expected 360."}
    report = evaluate.Report("ds", "2", "job-1", "COMPLETED", "now", ["Builtin.Correctness"], [passed, failed],
                             {"Builtin.Correctness": 0.5}, 0.0012)  # fmt: skip
    evaluate.save("bob", report)
    lines = evaluate.render(evaluate.load_last("bob"))
    assert lines[2].startswith("[PASS] eng") and lines[3].startswith("[FAIL] sales")
    assert "PASS RATE 1/2 (50%)" in lines and lines[-1].startswith("LiteLLM spend for this run: $0.0012")
    assert evaluate.failures(report) == ["- sales: Correctness=0.00 Expected 360."]


def test_batch_name_fits_the_api_pattern() -> None:
    name = evaluate.batch_name("abcdefghijklmnop")
    assert len(name) <= 48 and name.startswith("awsworkshop_abcdefghijklmnop_golden_")


def test_a_failed_question_is_retried_once_in_a_new_session(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions: list[str] = []

    def flaky(_out: dict, _token: str, _prompt: str, session: str, **_kwargs: object) -> dict:
        sessions.append(session)
        if len(sessions) == 1:
            raise RuntimeError("agent returned HTTP 504: <html>\n<head>")
        return {"response": " 481 employees. "}

    monkeypatch.setattr(evaluate.agentcore, "invoke_agent_body", flaky)
    result = evaluate.ask({}, "token", evaluate.new_result(ITEM, "eval-1"))
    assert (result.answer, result.error, result.session) == ("481 employees.", "", sessions[1])
    assert sessions[0] != sessions[1]


def test_every_question_is_asked_as_its_own_throwaway_user(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []
    monkeypatch.setattr(evaluate.users, "admin_password", lambda session, out, name: "pw")
    monkeypatch.setattr(evaluate.users, "sign_in", lambda session, out, name, password: f"token-{name}")
    monkeypatch.setattr(evaluate.users, "delete_user", lambda session, out, name: deleted.append(name))
    monkeypatch.setattr(evaluate, "ask", lambda out, token, result: result if token == f"token-{result.actor}" else 0)
    results = evaluate.ask_all(None, {}, [ITEM, TOOL_ITEM])
    actors = [result.actor for result in results]
    assert len(set(actors)) == 2 and all(actor.startswith("eval-") for actor in actors)
    assert sorted(deleted) == sorted(actors)


class FakeBatches:
    """Data-plane stand-in listing jobs of two participants; records stop/delete calls."""

    JOBS = [
        {"batchEvaluationName": f"awsworkshop_bob_golden_{n}", "batchEvaluationId": f"b{n}", "createdAt": n,
         "status": "IN_PROGRESS" if n == 1 else "COMPLETED"}
        for n in range(1, 4)
    ] + [{"batchEvaluationName": "awsworkshop_bobby_golden_9", "batchEvaluationId": "x", "createdAt": 9,
          "status": "COMPLETED"}]  # fmt: skip

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_paginator(self, _operation: str):
        return type("Paginator", (), {"paginate": lambda _self: [{"batchEvaluations": self.JOBS}]})()

    def stop_batch_evaluation(self, batchEvaluationId: str) -> None:  # noqa: N803
        self.calls.append(("stop", batchEvaluationId))

    def delete_batch_evaluation(self, batchEvaluationId: str) -> None:  # noqa: N803
        self.calls.append(("delete", batchEvaluationId))


def test_old_batch_jobs_are_pruned_and_down_deletes_all() -> None:
    pruned, everything = FakeBatches(), FakeBatches()
    evaluate.delete_batches(pruned, "bob", keep=2)
    evaluate.delete_batches(everything, "bob")
    assert pruned.calls == [("stop", "b1"), ("delete", "b1")]
    assert everything.calls == [("delete", "b3"), ("delete", "b2"), ("stop", "b1"), ("delete", "b1")]


def test_a_limit_above_the_dataset_size_says_so(caplog: pytest.LogCaptureFixture) -> None:
    dataset = datasets.DatasetVersion("ds-1", "awsworkshop_bob_golden", "3", [TOOL_ITEM], False)
    with caplog.at_level("INFO"):
        assert evaluate.limited_items(dataset, 20) == [TOOL_ITEM]
    assert "1 items (limit 20)" in caplog.text
    caplog.clear()
    assert evaluate.limited_items(dataset, 1) == [TOOL_ITEM] and not caplog.text


@pytest.mark.parametrize(
    "items, limit, variants, ok",
    [
        (11, 10, (), True),
        (11, 25, (), True),
        (30, 25, (), True),
        (30, 26, (), False),
        (11, 10, ("A", "B"), True),
        (30, 20, ("A", "B"), False),
        (51, 5, (), False),
        (11, 0, (), False),
    ],
)
def test_check_size_caps_scored_answers(items: int, limit: int, variants: tuple, ok: bool) -> None:
    options = evaluate.RunOptions(limit=limit, variants=variants)
    if ok:
        evaluate.check_size(items, options)
    else:
        with pytest.raises(RuntimeError, match="at most|limit is"):
            evaluate.check_size(items, options)
