"""Shared pass/warn/fail reports of `doctor` and `preflight`: ordering, crash containment, rendering, exit code."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import report  # noqa: E402


def slow_pass() -> report.Result:
    time.sleep(0.05)
    return report.passed("slow", "done")


def check_boom() -> report.Result:
    raise ValueError("kaput")


def test_results_keep_declaration_order_and_lists_flatten() -> None:
    results = report.run_checks([slow_pass, lambda: [report.warned("a", "x"), report.skipped("b", "y")]])
    assert [r.name for r in results] == ["slow", "a", "b"]


def test_a_crashing_check_becomes_a_failure() -> None:
    [result] = report.run_checks([check_boom])
    assert result.status is report.Status.FAIL and result.name == "boom" and "kaput" in result.detail


def test_render_shows_fix_hints_and_plain_words_without_unicode() -> None:
    results = [report.passed("ok", "fine"), report.failed("tf", "missing", "install it")]
    assert report.render(results, fancy=True) == ["✔ ok: fine", "✘ tf: missing", "    fix: install it"]
    assert report.render(results, fancy=False)[1] == "FAIL tf: missing"


def test_only_failures_fail_the_run() -> None:
    assert report.exit_code([report.warned("w", "x"), report.skipped("s", "y")]) == 0
    assert report.exit_code([report.failed("f", "x", "y")]) == 1
    assert report.summary([report.passed("p", ""), report.failed("f", "", "")]) == "1 pass, 1 fail"
