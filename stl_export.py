"""Safe STL export from the boundary BDF files written by Cast3M.

Cast3M's native ``SORT 'STL'`` path rejects zero-area triangles on very thin
side boundaries.  Binary STL would introduce a second problem here because its
32-bit coordinates cannot reliably preserve micron-scale openings on the
model's absolute coordinate range.  This module therefore writes ASCII STL
with double-precision text coordinates and omits only triangles that are
already exactly degenerate in the BDF geometry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from chamber_geometry import CHAMBER_STL_SURFACES


@dataclass(frozen=True)
class SurfaceExport:
    """One boundary BDF converted to a high-precision ASCII STL."""

    source: Path
    target: Path
    triangles: int
    skipped_degenerate_triangles: int


def boundary_output_pairs(
    workdir: Path,
    hole_count: int,
    *,
    include_chambers: bool = False,
) -> tuple[tuple[Path, Path], ...]:
    """Return the established Cast3M boundary-BDF to STL filename mapping."""

    pairs = [
        ("castem_mesh_surf_min.bdf", "castem_mesh_surf_zmin.stl"),
        ("castem_mesh_surf_max.bdf", "castem_mesh_surf_max.stl"),
        ("castem_mesh_surf_mean.bdf", "castem_mesh_surf_zmean.stl"),
        ("castem_mesh_surf_xmin.bdf", "castem_mesh_surf_xmin.stl"),
        ("castem_mesh_surf_xmax.bdf", "castem_mesh_surf_xmax.stl"),
        ("castem_mesh_surf_ymin.bdf", "castem_mesh_surf_ymin.stl"),
        ("castem_mesh_surf_ymax.bdf", "castem_mesh_surf_ymax.stl"),
    ]
    pairs.extend(
        (f"castem_mesh_surf_trou_{index}.bdf", f"castem_mesh_surf_trou_{index}.stl")
        for index in range(1, hole_count + 1)
    )
    if include_chambers:
        pairs.extend((f"{stem}.bdf", f"{stem}.stl") for stem in CHAMBER_STL_SURFACES)
    return tuple((workdir / source, workdir / target) for source, target in pairs)


def comment_native_stl_export(program: str) -> str:
    """Comment the native Cast3M STL block in a generated DGIBI program.

    The immutable reference template remains unchanged.  Every generated mesh
    program that requests STL receives an explicitly commented copy of the
    native block, and Python performs the requested conversion after Cast3M
    has successfully written the boundary BDF files.
    """

    lines = program.splitlines(keepends=True)
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(
                r"^\s*SI\s*\(\s*NON\s*\(\s*EGA\s+opti_stl\s+0\s*\)\s*\)\s*;",
                line,
                flags=re.IGNORECASE,
            )
        ),
        None,
    )
    if start is None:
        raise ValueError("Could not find the native Cast3M STL export block.")

    depth = 0
    end = None
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("*"):
            continue
        if re.match(r"^SI(?:\s|\()", stripped, flags=re.IGNORECASE):
            depth += 1
        elif re.match(r"^FINSI\b", stripped, flags=re.IGNORECASE):
            depth -= 1
            if depth == 0:
                end = index
                break
    if end is None:
        raise ValueError("The native Cast3M STL export block is not balanced.")

    disabled = [
        "* Native STL export disabled: Python converts boundary BDF files after Cast3M.\n"
    ]
    for line in lines[start : end + 1]:
        disabled.append("* " + line if line.strip() else "*\n")
    return "".join(lines[:start] + disabled + lines[end + 1 :])


def active_native_stl_sort_lines(program: str) -> tuple[str, ...]:
    """Return uncommented ``SORT 'STL'`` statements, for validation/tests."""

    return tuple(
        line.strip()
        for line in program.splitlines()
        if not line.lstrip().startswith("*")
        and re.search(r"\bSORT\s+'STL'", line, flags=re.IGNORECASE)
    )


def _nastran_float(text: str) -> float:
    value = text.strip().replace("D", "E").replace("d", "e")
    if not value:
        raise ValueError("Empty NASTRAN floating-point field.")
    if "e" not in value.lower():
        value = re.sub(r"(?<=\d)([+-]\d+)$", r"E\1", value)
    return float(value)


def _large_fields(line: str) -> list[str]:
    return [line[start : start + 16].strip() for start in range(8, 72, 16)]


def _small_fields(line: str) -> list[str]:
    if "," in line:
        return [field.strip() for field in line.rstrip().split(",")[1:]]
    fixed = [line[start : start + 8].strip() for start in range(8, len(line), 8)]
    if len([field for field in fixed if field]) >= 2:
        return fixed
    return line.split()[1:]


def _surface_elements(path: Path) -> list[tuple[int, ...]]:
    elements: list[tuple[int, ...]] = []
    with path.open("r", encoding="ascii", errors="ignore") as stream:
        while line := stream.readline():
            card = line[:8].strip().upper()
            if card in {"CQUAD4*", "CTRIA3*"}:
                fields = _large_fields(line)
                continuation = stream.readline()
                fields.extend(_large_fields(continuation))
            elif card in {"CQUAD4", "CTRIA3"}:
                fields = _small_fields(line)
            else:
                continue

            node_count = 4 if card.startswith("CQUAD4") else 3
            nodes = tuple(int(value) for value in fields[2 : 2 + node_count])
            if len(nodes) != node_count:
                raise ValueError(f"Incomplete {card.rstrip('*')} card in {path.name}.")
            elements.append(nodes)
    if not elements:
        raise ValueError(f"No CQUAD4 or CTRIA3 surface elements found in {path.name}.")
    return elements


def _selected_grid_points(
    path: Path, required: set[int]
) -> dict[int, tuple[float, float, float]]:
    points: dict[int, tuple[float, float, float]] = {}
    with path.open("r", encoding="ascii", errors="ignore") as stream:
        while line := stream.readline():
            card = line[:8].strip().upper()
            if card == "GRID*":
                fields = _large_fields(line)
                continuation = stream.readline()
                continuation_fields = _large_fields(continuation)
                node = int(fields[0])
                if node in required:
                    points[node] = (
                        _nastran_float(fields[2]),
                        _nastran_float(fields[3]),
                        _nastran_float(continuation_fields[0]),
                    )
            elif card == "GRID":
                fields = _small_fields(line)
                node = int(fields[0])
                if node in required:
                    points[node] = tuple(
                        _nastran_float(value) for value in fields[2:5]
                    )  # type: ignore[assignment]

    missing = required.difference(points)
    if missing:
        raise ValueError(
            f"{path.name} is missing {len(missing)} GRID coordinates referenced "
            "by the boundary elements."
        )
    return points


def _triangles(
    elements: Iterable[tuple[int, ...]],
    points: dict[int, tuple[float, float, float]],
) -> Iterable[tuple[np.ndarray, np.ndarray]]:
    for element in elements:
        node_triangles = (
            ((element[0], element[1], element[2]), (element[0], element[2], element[3]))
            if len(element) == 4
            else (element,)
        )
        for nodes in node_triangles:
            vertices = np.asarray([points[node] for node in nodes], dtype=np.float64)
            normal = np.cross(vertices[1] - vertices[0], vertices[2] - vertices[0])
            length = float(np.linalg.norm(normal))
            if length == 0.0:
                continue
            yield normal / length, vertices


def _write_ascii_stl(
    target: Path,
    elements: list[tuple[int, ...]],
    points: dict[int, tuple[float, float, float]],
) -> tuple[int, int]:
    possible = sum(2 if len(element) == 4 else 1 for element in elements)
    temporary = target.with_name(target.name + ".tmp")
    written = 0
    try:
        with temporary.open("w", encoding="ascii", newline="\n") as stream:
            stream.write(f"solid {target.stem}\n")
            for normal, vertices in _triangles(elements, points):
                if not np.all(np.isfinite(normal)) or not np.all(np.isfinite(vertices)):
                    raise ValueError(f"Non-finite STL geometry found while writing {target.name}.")
                stream.write(
                    "  facet normal "
                    + " ".join(format(float(value), ".17g") for value in normal)
                    + "\n"
                )
                stream.write("    outer loop\n")
                for vertex in vertices:
                    stream.write(
                        "      vertex "
                        + " ".join(format(float(value), ".17g") for value in vertex)
                        + "\n"
                    )
                stream.write("    endloop\n  endfacet\n")
                written += 1
            stream.write(f"endsolid {target.stem}\n")
        if written == 0:
            raise ValueError(f"All triangles in {target.name} are degenerate.")
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return written, possible - written


def export_boundary_bdfs_to_stl(
    workdir: Path,
    *,
    hole_count: int,
    include_chambers: bool = False,
    log: Callable[[str], None] | None = None,
) -> tuple[SurfaceExport, ...]:
    """Convert all expected boundary BDFs to high-precision ASCII STL files."""

    logger = log or (lambda _message: None)
    pairs = boundary_output_pairs(
        workdir,
        hole_count,
        include_chambers=include_chambers,
    )
    missing = [source.name for source, _target in pairs if not source.is_file()]
    if missing:
        raise FileNotFoundError(
            "Cannot export STL; boundary BDF files are missing: " + ", ".join(missing)
        )

    element_sets = [(source, target, _surface_elements(source)) for source, target in pairs]
    all_required = {
        node
        for _source, _target, elements in element_sets
        for element in elements
        for node in element
    }
    try:
        shared_points = _selected_grid_points(pairs[0][0], all_required)
    except ValueError:
        # Cast3M repeats its global GRID table in every boundary BDF, whereas
        # the source-free Python backend writes compact standalone boundaries.
        # Preserve the single-read Cast3M path and fall back to each compact
        # file's own complete coordinate table.
        shared_points = None
        logger(
            "Python BDF-to-STL: compact boundary GRID tables detected; "
            "reading coordinates from each source BDF.\n"
        )

    results: list[SurfaceExport] = []
    for source, target, elements in element_sets:
        required = {node for element in elements for node in element}
        points = (
            shared_points
            if shared_points is not None
            else _selected_grid_points(source, required)
        )
        triangles, skipped = _write_ascii_stl(target, elements, points)
        result = SurfaceExport(source, target, triangles, skipped)
        results.append(result)
        logger(
            f"Python BDF-to-STL: {target.name} ({triangles} triangles, "
            f"{skipped} exactly degenerate skipped)\n"
        )
    return tuple(results)


def export_report(exports: Iterable[SurfaceExport]) -> dict[str, object]:
    """Return a JSON-serializable summary for a headless run report."""

    items = tuple(exports)
    return {
        "method": "python_boundary_bdf_to_ascii_stl",
        "precision": "17 significant digits",
        "files": [
            {
                "source_bdf": item.source.name,
                "stl": item.target.name,
                "triangles": item.triangles,
                "skipped_exactly_degenerate_triangles": item.skipped_degenerate_triangles,
            }
            for item in items
        ],
        "total_triangles": sum(item.triangles for item in items),
        "total_skipped_exactly_degenerate_triangles": sum(
            item.skipped_degenerate_triangles for item in items
        ),
    }
