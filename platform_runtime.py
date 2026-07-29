"""Cross-platform executable discovery and process-launch helpers.

The historical T13 module is intentionally immutable and contains Windows-only
launcher code.  Maintained entry points use this module to preserve that
workflow while selecting the native Cast3M, Gmsh, and desktop commands on
Windows, Linux, and macOS.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Sequence


def _castem_versions(version: str) -> tuple[str, str]:
    raw = str(version).strip()
    if not raw.isdigit():
        raise ValueError("CASTEM version must be numeric (example: 25 or 2025).")
    short = raw[-2:]
    year = raw if len(raw) == 4 else f"20{short}"
    return short, year


def _is_runnable_file(path: Path, *, platform_name: str) -> bool:
    if not path.is_file():
        return False
    if platform_name == "nt":
        return True
    if not os.access(path, os.X_OK):
        return False
    try:
        first_line = path.read_bytes()[:512].splitlines()[0].decode(
            "utf-8",
            errors="ignore",
        )
    except (IndexError, OSError):
        return True
    if not first_line.startswith("#!"):
        return True
    try:
        invocation = shlex.split(first_line[2:].strip())
    except ValueError:
        return False
    if not invocation:
        return False
    interpreter = Path(invocation[0])
    if interpreter.name == "env":
        commands = [part for part in invocation[1:] if not part.startswith("-")]
        return bool(commands and shutil.which(commands[0]))
    return interpreter.is_file()


def _castem_names(short: str, year: str, *, platform_name: str) -> tuple[str, ...]:
    stems = (f"castem{short}", f"castem{year}", "castem")
    if platform_name == "nt":
        return tuple(
            f"{stem}{suffix}"
            for stem in stems
            for suffix in (".bat", ".cmd", ".exe")
        )
    return stems


def _executable_from_directory(
    directory: Path,
    names: Sequence[str],
    *,
    platform_name: str,
) -> Path | None:
    for name in names:
        candidate = directory / name
        if _is_runnable_file(candidate, platform_name=platform_name):
            return candidate.resolve()
    return None


def resolve_castem_exe(
    version: str,
    *,
    platform_name: str | None = None,
) -> Path:
    """Resolve a Cast3M launcher without changing the historical version input."""

    platform_name = os.name if platform_name is None else platform_name
    short, year = _castem_versions(version)
    names = _castem_names(short, year, platform_name=platform_name)
    configured = os.environ.get("CASTEM_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        candidate = (
            _executable_from_directory(path, names, platform_name=platform_name)
            if path.is_dir()
            else path.resolve()
            if _is_runnable_file(path, platform_name=platform_name)
            else None
        )
        if candidate is not None:
            return candidate
        raise FileNotFoundError(
            f"CASTEM_PATH does not identify a runnable Cast3M launcher: {path}"
        )

    for name in names:
        located = shutil.which(name)
        candidate = Path(located) if located else None
        if candidate is not None and _is_runnable_file(
            candidate,
            platform_name=platform_name,
        ):
            return candidate.resolve()

    candidates: list[Path] = []
    if platform_name == "nt":
        candidates.extend(
            Path(rf"C:\Cast3M\PCW_{short}\bin") / name
            for name in names
        )
    else:
        installation_roots = (
            Path("/u/logiciels/CASTEM"),
            Path("/opt/cast3m"),
            Path("/opt/CASTEM"),
            Path("/usr/local/cast3m"),
        )
        for root in installation_roots:
            candidates.extend(
                (
                    root / f"CASTEM{year}" / "bin" / f"castem{short}",
                    root / year / "bin" / f"castem{short}",
                    root / "bin" / f"castem{short}",
                )
            )

    for candidate in candidates:
        if _is_runnable_file(candidate, platform_name=platform_name):
            return candidate.resolve()

    expected = (
        f"castem{short}.bat or castem{short}.exe"
        if platform_name == "nt"
        else f"castem{short}"
    )
    raise FileNotFoundError(
        f"Cast3M {version} was not found. Set CASTEM_PATH to {expected} "
        "or its containing directory, or add the launcher to PATH."
    )


def _fallback_shell(path: Path) -> str | None:
    """Return an interpreter for an executable text wrapper with no valid shebang."""

    try:
        header = path.read_bytes()[:512]
    except OSError:
        return None
    if not header or header.startswith(b"#!") or b"\0" in header:
        return None
    first_line = header.splitlines()[0].decode("utf-8", errors="ignore").strip()
    declared = re.fullmatch(r"#\s*(/\S+)(?:\s+.*)?", first_line)
    if declared and Path(declared.group(1)).is_file():
        return declared.group(1)
    return "/bin/sh"


def castem_command(
    executable: Path,
    dgibi: Path,
    *,
    platform_name: str | None = None,
) -> list[str]:
    """Build the native command for one Cast3M DGIBI run."""

    platform_name = os.name if platform_name is None else platform_name
    executable = Path(executable)
    dgibi = Path(dgibi)
    if platform_name == "nt":
        return ["cmd.exe", "/c", str(executable), str(dgibi)]
    fallback_shell = _fallback_shell(executable)
    prefix = [fallback_shell, str(executable)] if fallback_shell else [str(executable)]
    return [*prefix, dgibi.name]


def adapt_legacy_castem_command(
    command: Sequence[str],
    *,
    platform_name: str | None = None,
) -> list[str]:
    """Translate the immutable T13 ``cmd.exe /c`` form on non-Windows hosts."""

    platform_name = os.name if platform_name is None else platform_name
    normalized = [str(part) for part in command]
    if (
        platform_name != "nt"
        and len(normalized) >= 4
        and Path(normalized[0]).name.lower() == "cmd.exe"
        and normalized[1].lower() == "/c"
    ):
        return castem_command(
            Path(normalized[2]),
            Path(normalized[3]),
            platform_name=platform_name,
        )
    return normalized


def resolve_gmsh_exe(*, platform_name: str | None = None) -> Path:
    """Resolve Gmsh from an override, PATH, or common native locations."""

    platform_name = os.name if platform_name is None else platform_name
    names = ("gmsh.exe", "gmsh") if platform_name == "nt" else ("gmsh", "gmsh.exe")
    configured = os.environ.get("GMSH_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        candidate = (
            _executable_from_directory(path, names, platform_name=platform_name)
            if path.is_dir()
            else path.resolve()
            if _is_runnable_file(path, platform_name=platform_name)
            else None
        )
        if candidate is not None:
            return candidate
        raise FileNotFoundError(
            f"GMSH_PATH does not identify a runnable Gmsh executable: {path}"
        )

    for name in names:
        located = shutil.which(name)
        candidate = Path(located) if located else None
        if candidate is not None and _is_runnable_file(
            candidate,
            platform_name=platform_name,
        ):
            return candidate.resolve()

    if platform_name == "nt":
        candidates = (
            Path(r"C:\Program Files\Gmsh\gmsh.exe"),
            Path(r"C:\Program Files (x86)\Gmsh\gmsh.exe"),
        )
    else:
        candidates = (
            Path("/usr/bin/gmsh"),
            Path("/usr/local/bin/gmsh"),
            Path.home() / ".local" / "bin" / "gmsh",
            Path("/Applications/Gmsh.app/Contents/MacOS/gmsh"),
        )
    for candidate in candidates:
        if _is_runnable_file(candidate, platform_name=platform_name):
            return candidate.resolve()
    raise FileNotFoundError(
        "Gmsh was not found. Set GMSH_PATH to the executable or its directory, "
        "or add gmsh to PATH."
    )


def launch_gmsh(mesh: Path, *, cwd: Path | None = None) -> subprocess.Popen[str]:
    """Open an existing mesh with the native Gmsh executable."""

    executable = resolve_gmsh_exe()
    mesh = Path(mesh).resolve()
    if not mesh.is_file():
        raise FileNotFoundError(f"Mesh does not exist: {mesh}")
    return subprocess.Popen(
        [str(executable), str(mesh)],
        cwd=str(cwd or mesh.parent),
        text=True,
    )


def open_with_default_application(path: Path) -> subprocess.Popen[str] | None:
    """Open a file or directory with the platform's desktop application."""

    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"Path does not exist: {target}")
    if os.name == "nt":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return None
    if sys.platform == "darwin":
        command = ["open", str(target)]
    else:
        opener = shutil.which("xdg-open")
        command = [opener, str(target)] if opener else []
        if not command:
            gio = shutil.which("gio")
            command = [gio, "open", str(target)] if gio else []
        if not command:
            raise FileNotFoundError(
                "No desktop opener was found. Install xdg-utils or use gio."
            )
    return subprocess.Popen(command, text=True)


def install_legacy_resolvers(module: ModuleType) -> None:
    """Route immutable T13 resolver calls through the portable implementations."""

    module.resolve_castem_exe = resolve_castem_exe
    module.resolve_gmsh_exe = resolve_gmsh_exe
