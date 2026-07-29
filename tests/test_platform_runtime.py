from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest

import platform_runtime


def _executable(path: Path, text: str = "#!/bin/sh\nexit 0\n") -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_castem_path_directory_resolves_native_linux_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = _executable(tmp_path / "castem25")
    monkeypatch.setenv("CASTEM_PATH", str(tmp_path))

    assert platform_runtime.resolve_castem_exe("2025", platform_name="posix") == launcher


def test_invalid_castem_override_has_actionable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASTEM_PATH", str(tmp_path / "missing"))

    with pytest.raises(FileNotFoundError, match="CASTEM_PATH"):
        platform_runtime.resolve_castem_exe("25", platform_name="posix")


def test_castem_version_remains_numeric() -> None:
    with pytest.raises(ValueError, match="numeric"):
        platform_runtime.resolve_castem_exe("latest", platform_name="posix")


def test_missing_env_shebang_interpreter_is_not_runnable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = _executable(
        tmp_path / "gmsh",
        "#!/usr/bin/env unavailable-python\n",
    )
    monkeypatch.setattr(platform_runtime.shutil, "which", lambda _name: None)

    assert not platform_runtime._is_runnable_file(launcher, platform_name="posix")


def test_castem_command_preserves_windows_batch_form(tmp_path: Path) -> None:
    launcher = tmp_path / "castem25.bat"
    dgibi = tmp_path / "mesh.dgibi"

    assert platform_runtime.castem_command(
        launcher,
        dgibi,
        platform_name="nt",
    ) == ["cmd.exe", "/c", str(launcher), str(dgibi)]


def test_castem_command_runs_native_linux_launcher_directly(tmp_path: Path) -> None:
    launcher = _executable(tmp_path / "castem25")
    dgibi = tmp_path / "mesh.dgibi"

    assert platform_runtime.castem_command(
        launcher,
        dgibi,
        platform_name="posix",
    ) == [str(launcher), dgibi.name]


def test_castem_command_repairs_legacy_linux_wrapper_shebang(tmp_path: Path) -> None:
    launcher = _executable(tmp_path / "castem25", "#/bin/bash\nexit 0\n")
    dgibi = tmp_path / "mesh.dgibi"

    assert platform_runtime.castem_command(
        launcher,
        dgibi,
        platform_name="posix",
    ) == ["/bin/bash", str(launcher), dgibi.name]


def test_legacy_cmd_command_is_adapted_only_on_non_windows(tmp_path: Path) -> None:
    launcher = _executable(tmp_path / "castem25")
    dgibi = tmp_path / "mesh.dgibi"
    legacy = ["cmd.exe", "/c", str(launcher), str(dgibi)]

    assert platform_runtime.adapt_legacy_castem_command(
        legacy,
        platform_name="posix",
    ) == [str(launcher), dgibi.name]
    assert platform_runtime.adapt_legacy_castem_command(
        legacy,
        platform_name="nt",
    ) == legacy


def test_gmsh_is_resolved_from_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gmsh = _executable(tmp_path / "gmsh")
    monkeypatch.delenv("GMSH_PATH", raising=False)
    monkeypatch.setattr(
        platform_runtime.shutil,
        "which",
        lambda name: str(gmsh) if name == "gmsh" else None,
    )

    assert platform_runtime.resolve_gmsh_exe(platform_name="posix") == gmsh


def test_immutable_module_resolvers_can_be_adapted_without_editing_it() -> None:
    legacy = ModuleType("legacy")

    platform_runtime.install_legacy_resolvers(legacy)

    assert legacy.resolve_castem_exe is platform_runtime.resolve_castem_exe
    assert legacy.resolve_gmsh_exe is platform_runtime.resolve_gmsh_exe
