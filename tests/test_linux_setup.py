from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = ROOT / "scripts" / "setup_linux.sh"


def test_linux_setup_is_repository_relative_and_accepts_conda_python() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    linux_guide = (ROOT / "docs" / "linux.md").read_text(encoding="utf-8")

    assert '${BASH_SOURCE[0]}' in script
    assert 'candidate_names=("python3" "python")' in script
    assert "PYTHON_BIN" in script
    assert "/home/" not in script
    assert "py -3.11 -m venv" not in readme
    assert "replace `python3` with `python`" in readme
    assert "PYTHON_BIN=python ./scripts/setup_linux.sh" in linux_guide
    assert "./scripts/setup_linux.sh --check-only" in linux_guide


@pytest.mark.skipif(os.name == "nt", reason="Bash setup is POSIX-specific")
def test_linux_setup_check_works_outside_the_repository(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["PYTHON_BIN"] = sys.executable
    completed = subprocess.run(
        ["bash", str(SETUP_SCRIPT), "--check-only"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert f"Project root: {ROOT}" in completed.stdout
    assert "Setup check passed. No environment was created." in completed.stdout
