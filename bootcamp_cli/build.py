"""Builds AgentCore direct-code-deploy zips (linux/arm64, Python 3.13) on any host OS."""

import hashlib
import logging
import os
import shutil
import stat
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

import requests

from bootcamp_cli import lab_data
from bootcamp_cli.config import ROOT

log = logging.getLogger(__name__)

APP_DIR = ROOT / "phase2" / "app"
BUILD_DIR = ROOT / ".build"
SHARED_DIR = ROOT / "shared"
APP_EXTRA_FILES = {"rubric_judge": (ROOT / "phase2" / "evals" / "evaluators.yaml",)}
"""Files from outside `phase2/app/<name>/` that an app zip also needs (copied to its root): the judge's rubrics."""
DB_URL = "https://genai-launchpad.aws.opsfleet.com/assets/datastream_corp.db"
DB_SHA256 = "41a50fc1f8a64f41fd476f2c01189c2dec9928ed75e8f85e58ddbc71f3e6b575"
"""Checksum of the published copy: a truncated or wrong download fails loudly instead of as 'no such table'."""
OTEL_SHIM = (
    "#!/usr/bin/env python3\n"
    "import sys\n"
    "from opentelemetry.instrumentation.auto_instrumentation import run\n"
    "sys.exit(run())\n"
)
"""Portable `opentelemetry-instrument` launcher.

uv's generated script has a host-specific shebang (or is an .exe on Windows), so it would not run on AgentCore.
"""


def build_app(name: str) -> Path:
    """Build `.build/<name>.zip` from `phase2/app/<name>/`, skipping when sources are unchanged.

    Staging happens in a short private temp dir (keeps Windows paths under MAX_PATH, and concurrent runs never
    share it); the zip and its stamp are swapped in atomically.
    """
    source = APP_DIR / name
    target = BUILD_DIR / f"{name}.zip"
    stamp = BUILD_DIR / f"{name}.sha256"
    digest = _source_digest(source)
    if target.exists() and stamp.exists() and stamp.read_text() == digest:
        log.info("%s unchanged, reusing %s", name, target.name)
        return target
    BUILD_DIR.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="bc-"))
    try:
        _stage(source, staging)
        _atomic_write(target, lambda path: _zip_dir(staging, path))
        _atomic_write(stamp, lambda path: path.write_text(digest))
    finally:
        shutil.rmtree(staging, onexc=_force_remove)
    log.info("Built %s (%.1f MB)", target.name, target.stat().st_size / 1e6)
    return target


def _stage(source: Path, staging: Path) -> None:
    """Install arm64 wheels, then copy the app, the shared helpers, its extra files and the portable OTel launcher."""
    _install_dependencies(source / "requirements.txt", staging)
    shutil.copytree(
        source,
        staging,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "requirements.txt", "requirements.in"),
    )
    for extra in [*SHARED_DIR.glob("*.py"), *APP_EXTRA_FILES.get(source.name, ())]:
        shutil.copy2(extra, staging / extra.name)
    (staging / "bin").mkdir(exist_ok=True)
    (staging / "bin" / "opentelemetry-instrument").write_text(OTEL_SHIM, newline="\n")


def _atomic_write(target: Path, write: Callable[[Path], None]) -> None:
    """Write via a unique sibling temp file and rename it over `target`, so readers never see a partial file."""
    handle, temp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    os.close(handle)
    try:
        write(Path(temp))
        os.replace(temp, target)
    finally:
        Path(temp).unlink(missing_ok=True)


def _force_remove(function: Callable[[str], object], path: str, _: BaseException) -> None:
    """rmtree error hook: clear the read-only bit Windows leaves on some wheel files, then retry."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _source_digest(source: Path) -> str:
    sha = hashlib.sha256()
    files = [*source.rglob("*"), *SHARED_DIR.glob("*.py"), *APP_EXTRA_FILES.get(source.name, ())]
    for path in sorted(p for p in files if p.is_file() and "__pycache__" not in p.parts):
        sha.update(path.name.encode())
        sha.update(path.read_bytes())
    return sha.hexdigest()


def _install_dependencies(requirements: Path, staging: Path) -> None:
    log.info("Installing linux/arm64 wheels from %s", requirements.relative_to(ROOT))
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--quiet",
            "-r",
            str(requirements),
            "--target",
            str(staging),
            "--python-platform",
            "aarch64-manylinux2014",
            "--python-version",
            "3.13",
            "--only-binary",
            ":all:",
        ],
        check=True,
    )


def _zip_dir(staging: Path, target: Path) -> None:
    """Zip with POSIX paths and exec bits so the archive is identical whatever OS built it."""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(
            p for p in staging.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.name != ".lock"
        ):
            relative = path.relative_to(staging).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(2020, 1, 1, 0, 0, 0))
            info.external_attr = (0o100755 if relative.startswith("bin/") else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())


def seed_database() -> Path:
    """Download the workshop's DataStream DB once, plus the guardrails lab table; Terraform seeds your copy from it."""
    target = BUILD_DIR / "datastream_corp.db"
    if not target.exists():
        BUILD_DIR.mkdir(exist_ok=True)
        response = requests.get(DB_URL, timeout=60)
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != DB_SHA256:
            raise RuntimeError(f"{DB_URL} did not match the expected checksum; download it again")
        _atomic_write(target, lambda path: path.write_bytes(response.content))
    lab_data.ensure_helpdesk_tickets(target)
    return target
