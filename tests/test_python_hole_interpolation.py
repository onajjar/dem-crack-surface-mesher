from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

import castem_pipeline_gui_t13 as baseline
from castem_pipeline_gui_python_holes import (
    archive_existing_mesh_outputs,
    expected_mesh_output_names,
)
from python_hole_interpolation import (
    SurfaceFillMesh,
    build_python_holes_dgibi,
    detect_circle_rings,
    generated_program_uses_python_holes,
    interpolate_surface,
    load_surface_csvs,
    radial_layer_fractions,
    validate_surface_fill_mesh,
)


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "examples" / "input"


def test_rectilinear_bilinear_interpolation_is_exact_for_bilinear_field() -> None:
    x_axis = np.array((-1.0, -0.2, 0.7, 1.5))
    y_axis = np.array((-0.5, 0.3, 1.2))
    x = np.tile(x_axis, (len(y_axis), 1))
    y = np.tile(y_axis[:, None], (1, len(x_axis)))
    z = 1.5 - 2.0 * x + 0.75 * y + 3.0 * x * y
    points = np.array(((-0.8, -0.1), (0.0, 0.9), (1.3, 0.6)))

    actual = interpolate_surface(x, y, z, points)
    expected = 1.5 - 2.0 * points[:, 0] + 0.75 * points[:, 1] + 3.0 * points[:, 0] * points[:, 1]
    assert np.allclose(actual, expected, rtol=0.0, atol=1.0e-12)


def test_curvilinear_bilinear_interpolation_checks_and_solves_inverse() -> None:
    x = np.array(((0.0, 1.0), (0.2, 1.2)))
    y = np.array(((0.0, 0.0), (1.0, 1.0)))
    z = 2.0 * x - 0.5 * y + 1.0
    point = np.array(((0.38, 0.4),))

    actual = interpolate_surface(x, y, z, point)

    assert np.allclose(actual, 2.0 * point[:, 0] - 0.5 * point[:, 1] + 1.0)


def test_curvilinear_interpolation_rejects_singular_cell() -> None:
    x = np.array(((0.0, 1.0), (0.0, 1.0)))
    y = np.zeros((2, 2))
    z = np.array(((0.0, 10.0), (100.0, 110.0)))

    with pytest.raises(ValueError, match="Could not locate circle point"):
        interpolate_surface(x, y, z, np.array(((0.2, 0.0),)))


def test_surface_validation_rejects_locally_concave_quad() -> None:
    mesh = SurfaceFillMesh(
        points=np.array(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.2, 0.2, 0.0), (0.0, 1.0, 0.0))),
        quads=np.array(((0, 1, 2, 3),), dtype=int),
    )

    with pytest.raises(ValueError, match="concave, folded, or locally degenerate"):
        validate_surface_fill_mesh(mesh)


def test_documented_multiple_holes_produce_expected_circle_rings() -> None:
    x, y, _zmin, _zmax = load_surface_csvs(
        INPUT / "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    )
    holes = (baseline.Hole(-0.20, 0.20, 0.07), baseline.Hole(0.20, -0.20, 0.07))

    rings = detect_circle_rings(x, y, holes)

    assert [len(ring.xy) for ring in rings] == [32, 32]
    for ring, hole in zip(rings, holes, strict=True):
        radii = np.hypot(ring.xy[:, 0] - hole.cx, ring.xy[:, 1] - hole.cy)
        assert np.allclose(radii, hole.r, rtol=0.0, atol=1.0e-12)


def test_hole_inflation_has_requested_outer_to_inner_size_ratio() -> None:
    fractions = radial_layer_fractions(num_layers=5, inflation_factor=5.0)
    widths = np.diff(fractions)

    assert np.all(np.diff(fractions) > 0.0)
    assert fractions[0] == 0.0
    assert fractions[-1] == 1.0
    assert np.isclose(widths[0] / widths[-1], 5.0, rtol=0.0, atol=1.0e-12)


def test_derived_program_bulk_loads_inflated_hole_meshes_without_displace() -> None:
    params = baseline.CastemMainParams(
        holes_enabled=True,
        holes=(baseline.Hole(-0.20, 0.20, 0.07), baseline.Hole(0.20, -0.20, 0.07)),
    )
    template = (ROOT / "source_codes" / "castem_tool.dgibi").read_text(encoding="utf-8")
    program, hole_meshes = build_python_holes_dgibi(
        template,
        params,
        INPUT / "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        baseline.patch_dgibi_main_program,
        hole_mesh_directory=ROOT / "_runtime" / "test-hole-fill",
    )

    assert hole_meshes is not None
    assert generated_program_uses_python_holes(program)
    assert "INT_COMP surf_zmin_comp" not in program
    assert "DISPLACE surf_zmin" not in program
    assert "REGL (-1*num_el_fill)" not in program
    assert "py_min_h1_p1 = POIN" not in program
    assert "LIRE 'NAS' 'python_hole_fill_min.bdf'" in program
    assert hole_meshes.points_per_hole == (32, 32)
    assert hole_meshes.min_mesh.points.shape == (384, 3)
    assert hole_meshes.min_mesh.quads.shape == (320, 4)
    for path in (hole_meshes.min_path, hole_meshes.max_path, hole_meshes.mean_path):
        text = path.read_text(encoding="ascii")
        assert text.count("GRID*") == 384
        assert text.count("CQUAD4") == 320
        assert text.endswith("ENDDATA\n")


def test_no_hole_program_is_the_unmodified_baseline_parameter_patch() -> None:
    params = baseline.CastemMainParams(holes_enabled=False, holes=())
    template = (ROOT / "source_codes" / "castem_tool.dgibi").read_text(encoding="utf-8")
    actual, rings = build_python_holes_dgibi(
        template,
        params,
        INPUT / "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        baseline.patch_dgibi_main_program,
    )

    assert rings is None
    assert actual == baseline.patch_dgibi_main_program(template, params)


def test_previous_fixed_name_outputs_are_archived_before_reuse() -> None:
    workdir = ROOT / "_runtime" / "test-mesh-archive" / uuid4().hex
    workdir.mkdir(parents=True)
    previous = (workdir / "castem_mesh_v.bdf", workdir / "castem_mesh_surf_trou_3.bdf")
    for path in previous:
        path.write_text("previous run\n", encoding="ascii")
    unrelated = workdir / "notes.txt"
    unrelated.write_text("keep\n", encoding="ascii")
    messages: list[str] = []

    archive = archive_existing_mesh_outputs(workdir, messages.append)

    assert archive is not None
    assert all(not path.exists() for path in previous)
    assert all((archive / path.name).is_file() for path in previous)
    assert unrelated.is_file()
    assert "Archived 2 previous mesh artifact(s)" in "".join(messages)


def test_expected_output_manifest_matches_enabled_holes() -> None:
    params = baseline.CastemMainParams(
        holes_enabled=True,
        holes=(baseline.Hole(0.0, 0.0, 0.1), baseline.Hole(0.3, 0.0, 0.1)),
    )

    names = expected_mesh_output_names(params)

    assert "castem_mesh_v.bdf" in names
    assert "castem_mesh_surf_trou_1.bdf" in names
    assert "castem_mesh_surf_trou_2.bdf" in names
    assert "castem_mesh_surf_trou_3.bdf" not in names
