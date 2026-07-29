from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

import castem_pipeline_gui_t13 as baseline
from castem_pipeline_gui_python_holes import patch_mesh_program
from stl_export import (
    active_native_stl_sort_lines,
    boundary_output_pairs,
    export_boundary_bdfs_to_stl,
    export_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _large_grid(node: int, x: float, y: float, z: float) -> str:
    return (
        f"{'GRID*':<8}{node:>16}{0:>16}{x:>16.9E}{y:>16.9E}\n"
        f"{'*':<8}{z:>16.9E}\n"
    )


def _small_quad(element: int, nodes: tuple[int, int, int, int]) -> str:
    fields = ("CQUAD4", element, 1, *nodes)
    return f"{fields[0]:<8}" + "".join(f"{value:>8}" for value in fields[1:]) + "\n"


def _boundary_bdf() -> str:
    # The 1e-9 Z separation is below useful float32 resolution near -0.6, but
    # remains distinct in the high-precision ASCII STL path.
    points = (
        (1, -0.6, 0.0, -0.6),
        (2, -0.6, 1.0, -0.6),
        (3, -0.6, 1.0, -0.599999999),
        (4, -0.6, 0.0, -0.599999999),
    )
    return (
        "BEGIN BULK\n"
        + "".join(_large_grid(*point) for point in points)
        + _small_quad(1, (1, 2, 3, 4))
        + _small_quad(2, (1, 1, 2, 2))
        + "ENDDATA\n"
    )


def test_requested_stl_comments_every_native_cast3m_sort_statement() -> None:
    template = (ROOT / "source_codes" / "castem_tool.dgibi").read_text(
        encoding="utf-8"
    )
    params = baseline.CastemMainParams(opti_stl=1)

    program = patch_mesh_program(template, params)

    assert active_native_stl_sort_lines(program) == ()
    assert "opti_stl = 1" in program
    assert sum(
        1
        for line in program.splitlines()
        if line.startswith("* ") and "SORT 'STL'" in line
    ) == 8
    assert active_native_stl_sort_lines(template)


def test_boundary_bdf_export_is_high_precision_and_skips_exact_degeneracy() -> None:
    workdir = ROOT / "_runtime" / "test-stl-export" / uuid4().hex
    workdir.mkdir(parents=True)
    content = _boundary_bdf()
    for source, _target in boundary_output_pairs(workdir, hole_count=0):
        source.write_text(content, encoding="ascii")

    exports = export_boundary_bdfs_to_stl(workdir, hole_count=0)

    assert len(exports) == 7
    assert all(item.triangles == 2 for item in exports)
    assert all(item.skipped_degenerate_triangles == 2 for item in exports)
    report = export_report(exports)
    assert report["method"] == "python_boundary_bdf_to_ascii_stl"
    assert report["total_triangles"] == 14
    assert report["total_skipped_exactly_degenerate_triangles"] == 14

    text = exports[0].target.read_text(encoding="ascii")
    assert text.startswith("solid ")
    assert text.count("facet normal") == 2
    vertices = np.asarray(
        [
            [float(value) for value in match.groups()]
            for match in re.finditer(
                r"^\s*vertex\s+(\S+)\s+(\S+)\s+(\S+)$",
                text,
                flags=re.MULTILINE,
            )
        ]
    ).reshape(-1, 3, 3)
    assert np.all(
        np.linalg.norm(
            np.cross(
                vertices[:, 1] - vertices[:, 0],
                vertices[:, 2] - vertices[:, 0],
            ),
            axis=1,
        )
        > 0.0
    )
    assert np.ptp(vertices[:, :, 2]) > 0.0


def test_boundary_export_reads_each_compact_python_bdf_grid() -> None:
    workdir = ROOT / "_runtime" / "test-compact-stl-export" / uuid4().hex
    workdir.mkdir(parents=True)
    pairs = boundary_output_pairs(workdir, hole_count=0)
    expected_z: dict[Path, float] = {}
    for file_index, (source, target) in enumerate(pairs):
        first_node = 10 * file_index + 1
        z = 0.125 * file_index
        points = (
            (first_node, 0.0, 0.0, z),
            (first_node + 1, 1.0, 0.0, z),
            (first_node + 2, 1.0, 1.0, z),
            (first_node + 3, 0.0, 1.0, z),
        )
        source.write_text(
            "BEGIN BULK\n"
            + "".join(_large_grid(*point) for point in points)
            + _small_quad(
                file_index + 1,
                (
                    first_node,
                    first_node + 1,
                    first_node + 2,
                    first_node + 3,
                ),
            )
            + "ENDDATA\n",
            encoding="ascii",
        )
        expected_z[target] = z

    messages: list[str] = []
    exports = export_boundary_bdfs_to_stl(
        workdir,
        hole_count=0,
        log=messages.append,
    )

    assert len(exports) == 7
    assert any("compact boundary GRID tables" in message for message in messages)
    for item in exports:
        z_values = [
            float(match.group(1))
            for match in re.finditer(
                r"^\s*vertex\s+\S+\s+\S+\s+(\S+)$",
                item.target.read_text(encoding="ascii"),
                flags=re.MULTILINE,
            )
        ]
        assert z_values
        assert z_values == pytest.approx(
            [expected_z[item.target]] * len(z_values)
        )
