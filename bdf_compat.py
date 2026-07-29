"""Small compatibility normalizations for merged NASTRAN BDF meshes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

LogFunction = Callable[[str], None]


def _cquad4_span(lines: list[str], start: int) -> tuple[int, tuple[str, ...] | None]:
    """Return the card end and its four node fields for small/large BDF forms."""

    end = start + 1
    while end < len(lines):
        prefix = lines[end][:8].strip()
        if not prefix or prefix[0] not in {"*", "+"}:
            break
        end += 1

    tokens: list[str] = []
    for line in lines[start:end]:
        fields = line.replace(",", " ").split()
        if fields and fields[0] in {"*", "+"}:
            fields = fields[1:]
        tokens.extend(fields)
    if not tokens or not tokens[0].upper().rstrip("*") == "CQUAD4":
        return end, None
    body = tokens[1:]
    if len(body) < 6:
        return end, None
    return end, tuple(body[2:6])


def remove_degenerate_cquad4(path: Path) -> int:
    """Remove collapsed CQUAD4 cards with fewer than three distinct node IDs.

    Cast3M legitimately collapses crack-front side faces when the opening reaches
    zero. Some Gmsh and CFD importers reject those zero-measure shell records.
    Three-node triangular CQUAD4 representations remain untouched; removing only
    line/point collapses leaves every volume cell and non-zero boundary face
    unchanged.
    """

    path = Path(path)
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines(True)
    kept: list[str] = []
    removed = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.lstrip().upper().startswith("CQUAD4"):
            end, node_ids = _cquad4_span(lines, index)
            if node_ids is not None and len(set(node_ids)) < 3:
                removed += 1
                index = end
                continue
            kept.extend(lines[index:end])
            index = end
            continue
        kept.append(line)
        index += 1

    if removed:
        path.write_text("".join(kept), encoding="utf-8")
    return removed


def merge_bdfs_compatible(
    baseline_module: Any,
    workdir: Path,
    log: LogFunction,
) -> Path | None:
    """Run the preserved merger and discard only zero-measure shell records."""

    combined = baseline_module.merge_bdfs(Path(workdir), log)
    if combined is None or not combined.is_file():
        return combined
    removed = remove_degenerate_cquad4(combined)
    if removed:
        log(
            f"Removed {removed} zero-area CQUAD4 record(s) from the combined "
            "BDF for CFD/Gmsh compatibility.\n"
        )
    return combined
