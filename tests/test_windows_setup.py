import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = ROOT / "scripts" / "setup_windows.ps1"


def test_windows_setup_is_repository_relative_and_launcher_agnostic() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "$PSScriptRoot" in script
    assert 'Name = "python"' in script
    assert 'Name = "py"' in script
    assert 'Name = "python3"' in script
    assert "C:\\Users\\" not in script
    assert "py -3.11 -m venv" not in readme
    assert "python -m venv .venv" in readme
    assert "C:\\Windows\\System32" in readme


@pytest.mark.skipif(os.name != "nt", reason="PowerShell setup is Windows-specific")
def test_windows_setup_check_works_outside_the_repository() -> None:
    system_directory = Path(os.environ["WINDIR"]) / "System32"
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SETUP_SCRIPT),
            "-PythonExecutable",
            sys.executable,
            "-CheckOnly",
        ],
        cwd=system_directory,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert f"Project root: {ROOT}" in completed.stdout
    assert "Setup check passed. No environment was created." in completed.stdout
