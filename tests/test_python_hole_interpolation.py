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
    HoleGeometry,
    SurfaceFillMesh,
    build_python_holes_dgibi,
    detect_circle_rings,
    detect_hole_rings,
    generated_program_uses_python_holes,
    hole_boundary_vertices,
    interpolate_surface,
    load_surface_csvs,
    parse_hole_spec,
    prepare_hole_fill_meshes,
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

    with pytest.raises(ValueError, match="Could not locate hole-boundary point"):
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


def test_hole_ring_matches_refined_background_edge_count() -> None:
    x, y, _zmin, _zmax = load_surface_csvs(
        INPUT / "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    )
    holes = (baseline.Hole(-0.20, 0.20, 0.07), baseline.Hole(0.20, -0.20, 0.07))

    rings = detect_circle_rings(x, y, holes, nelem_x=2, nelem_y=2)

    assert [len(ring.outer_xy) for ring in rings] == [64, 64]
    assert [len(ring.xy) for ring in rings] == [64, 64]
    for ring, hole in zip(rings, holes, strict=True):
        radii = np.hypot(ring.xy[:, 0] - hole.cx, ring.xy[:, 1] - hole.cy)
        assert np.allclose(radii, hole.r, rtol=0.0, atol=1.0e-12)


def _distance_to_polygon_edges(points: np.ndarray, vertices: np.ndarray) -> np.ndarray:
    starts = vertices
    edges = np.roll(vertices, -1, axis=0) - starts
    relative = points[:, np.newaxis, :] - starts[np.newaxis, :, :]
    scale = np.sum(relative * edges[np.newaxis, :, :], axis=2) / np.sum(edges * edges, axis=1)
    scale = np.clip(scale, 0.0, 1.0)
    closest = starts[np.newaxis, :, :] + scale[:, :, np.newaxis] * edges[np.newaxis, :, :]
    return np.min(np.linalg.norm(points[:, np.newaxis, :] - closest, axis=2), axis=1)


def test_all_supported_hole_shapes_are_conformal_and_on_their_boundaries() -> None:
    x, y, _zmin, _zmax = load_surface_csvs(
        INPUT / "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    )
    shapes = (
        HoleGeometry("circle", -0.25, 0.25, radius=0.045),
        HoleGeometry("rectangle", 0.23, 0.25, width=0.10, height=0.06, rotation_degrees=15.0),
        HoleGeometry("triangle", -0.25, -0.23, side_length=0.10, rotation_degrees=-10.0),
        HoleGeometry("regular_polygon", 0.23, -0.23, radius=0.055, sides=6, rotation_degrees=30.0),
    )

    rings = detect_hole_rings(x, y, shapes, nelem_x=2, nelem_y=2)

    assert len(rings) == 4
    for ring, geometry in zip(rings, shapes, strict=True):
        assert len(ring.xy) == len(ring.outer_xy)
        assert len(ring.xy) >= 32
        if geometry.shape == "circle":
            distance = np.hypot(ring.xy[:, 0] - geometry.cx, ring.xy[:, 1] - geometry.cy)
            assert np.allclose(distance, geometry.radius, rtol=0.0, atol=1.0e-12)
        else:
            assert np.max(
                _distance_to_polygon_edges(ring.xy, hole_boundary_vertices(geometry))
            ) < 1.0e-12


@pytest.mark.parametrize(
    ("text", "shape"),
    (
        ("circle, -0.2, 0.2, 0.07", "circle"),
        ("rectangle, 0.2, 0.2, 0.10, 0.06, 15", "rectangle"),
        ("triangle, -0.2, -0.2, 0.10, -10", "triangle"),
        ("regular_polygon, 0.2, -0.2, 6, 0.055, 30", "regular_polygon"),
    ),
)
def test_documented_shape_specifications_parse(text: str, shape: str) -> None:
    assert parse_hole_spec(text).shape == shape


def test_mixed_shape_fill_mesh_has_valid_quads() -> None:
    output = ROOT / "_runtime" / "test-mixed-shapes" / uuid4().hex
    meshes = prepare_hole_fill_meshes(
        INPUT / "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        (
            HoleGeometry("circle", -0.25, 0.25, radius=0.045),
            HoleGeometry("rectangle", 0.23, 0.25, width=0.10, height=0.06, rotation_degrees=15.0),
            HoleGeometry("triangle", -0.25, -0.23, side_length=0.10, rotation_degrees=-10.0),
            HoleGeometry("regular_polygon", 0.23, -0.23, radius=0.055, sides=6, rotation_degrees=30.0),
        ),
        output,
        num_layers=5,
        inflation_factor=5.0,
        nelem_x=2,
        nelem_y=2,
    )

    assert len(meshes.points_per_hole) == 4
    assert meshes.min_mesh.quads.shape[0] == 5 * sum(meshes.points_per_hole)
    validate_surface_fill_mesh(meshes.min_mesh)


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


def test_preoptimized_chamber_template_is_reused_without_displace() -> None:
    params = baseline.CastemMainParams(
        holes_enabled=True,
        holes=(baseline.Hole(-0.20, 0.20, 0.07), baseline.Hole(0.20, -0.20, 0.07)),
    )
    template = (ROOT / "source_codes" / "castem_tool_chambers.dgibi").read_text(
        encoding="utf-8"
    )
    program, hole_meshes = build_python_holes_dgibi(
        template,
        params,
        INPUT / "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        baseline.patch_dgibi_main_program,
        hole_mesh_directory=ROOT / "_runtime" / "test-preoptimized-chamber",
    )

    assert hole_meshes is not None
    assert generated_program_uses_python_holes(program)
    assert program == baseline.patch_dgibi_main_program(template, params)


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
