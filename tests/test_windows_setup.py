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


@pytest.mark.skipif(os.name != "nt", reason="PowerShell setup is Windows-specific")
def test_windows_setup_handles_multiple_python_commands_on_path(tmp_path: Path) -> None:
    first_directory = tmp_path / "first python"
    second_directory = tmp_path / "second python"
    first_directory.mkdir()
    second_directory.mkdir()

    for directory in (first_directory, second_directory):
        shim = directory / "python.cmd"
        shim.write_text(
            f'@echo off\n"{sys.executable}" %*\n',
            encoding="utf-8",
        )

    environment = os.environ.copy()
    environment.pop("PYTHON_BIN", None)
    environment["PATH"] = os.pathsep.join(
        (str(first_directory), str(second_directory), environment["PATH"])
    )

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SETUP_SCRIPT),
            "-CheckOnly",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert f"Selected Python: {first_directory / 'python.cmd'}" in completed.stdout
    assert "Setup check passed. No environment was created." in completed.stdout
