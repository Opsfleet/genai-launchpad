"""Concise terraform output: which lines are shown, how they are shortened, and what a failure prints."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import tf  # noqa: E402


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Plan: 3 to add, 1 to change, 0 to destroy.", "terraform plan: +3 ~1 -0"),
        ("aws_s3_bucket.code[0]: Creation complete after 2s [id=b]", "  + aws_s3_bucket.code[0] (2s)"),
        ("aws_iam_role.r: Modifications complete after 1s [id=r]", "  ~ aws_iam_role.r (1s)"),
        ("aws_iam_role.r: Destruction complete after 0s", "  - aws_iam_role.r (0s)"),
        ("aws_x.m[0]: Still creating... [01m00s elapsed]", "  ... aws_x.m[0] still creating (01m00s)"),
        ("aws_x.m[0]: Still destroying... [id=abc, 2m0s elapsed]", "  ... aws_x.m[0] still destroying (2m0s)"),
        ("Apply complete! Resources: 3 added, 0 changed, 0 destroyed.", None),
        ("No changes. Your infrastructure matches the configuration.", None),
    ],
)
def test_summary_lines(line: str, expected: str | None) -> None:
    assert tf.summarize_line(line) == (expected or line)


@pytest.mark.parametrize(
    "line",
    ["aws_x.m[0]: Still creating... [10s elapsed]", "aws_x.m[0]: Still creating... [1m10s elapsed]", "  + resource {"],
)
def test_noise_is_hidden(line: str) -> None:
    assert tf.summarize_line(line) is None


def test_failure_prints_the_error_block() -> None:
    output = ["noise"] * 100 + ["Error: creating thing", "", "  with aws_x.y,"]
    assert tf.failure_excerpt(output) == output[100:]


def test_failure_without_error_block_prints_the_tail() -> None:
    output = [str(index) for index in range(100)]
    assert tf.failure_excerpt(output) == output[-tf.FAILURE_TAIL_LINES :]


@pytest.mark.skipif(sys.platform == "win32", reason="the terraform stand-in is a POSIX shell script")
def test_run_live_summarises_and_raises_on_failure(monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path) -> None:
    script = tmp_path / "terraform"
    script.write_text("#!/bin/sh\necho 'Plan: 1 to add, 0 to change, 0 to destroy.'\necho 'Error: boom'\nexit 1\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    with pytest.raises(tf.subprocess.CalledProcessError) as raised:
        tf.run_live(tmp_path, ["apply", "-auto-approve"], {"PATH": f"{tmp_path}:/usr/bin:/bin"})
    captured = capsys.readouterr()
    assert "terraform plan: +1 ~0 -0" in captured.out and "Error: boom" in captured.err
    assert "-no-color" in raised.value.cmd


def test_run_live_retries_once_on_aws_throttling(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter([(1, ["Error: creating Gateway: Too Many Requests (Status Code: 429)"]), (0, ["Apply complete!"])])
    calls = []
    monkeypatch.setattr(tf, "_require_terraform", lambda: None)
    monkeypatch.setattr(tf, "_stream_summary", lambda command, env: calls.append(command) or next(results))
    monkeypatch.setattr(tf.time, "sleep", lambda seconds: None)
    tf.run_live(Path("."), ["apply", "-auto-approve"], {})
    assert len(calls) == 2


def test_run_live_does_not_retry_real_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(tf, "_require_terraform", lambda: None)
    monkeypatch.setattr(tf, "_stream_summary", lambda command, env: calls.append(command) or (1, ["Error: invalid"]))
    with pytest.raises(subprocess.CalledProcessError):
        tf.run_live(Path("."), ["apply", "-auto-approve"], {})
    assert len(calls) == 1
