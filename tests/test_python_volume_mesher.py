from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

import castem_pipeline_gui_t13 as baseline
import castem_pipeline_headless as headless
from castem_pipeline_headless import load_setup, validate_setup
from python_hole_interpolation import HoleGeometry, load_surface_csvs
from python_volume_mesher import (
    build_python_volume_mesh,
    build_surface_topology,
    cast3m_fixed_count_fractions,
    hexa8_quality,
    write_python_mesh_outputs,
)
from surface_generation import build_surface_grid

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples" / "python-only-chambers" / "run.ini"
INPUT = ROOT / "examples" / "input"


def test_cast3m_fixed_count_grading_matches_reviewed_chamber_coordinates() -> None:
    fractions, ratio = cast3m_fixed_count_fractions(
        10,
        0.02,
        0.10,
        0.20,
    )

    assert ratio == pytest.approx(1.4879215610874228)
    assert fractions == pytest.approx(
        (
            0.0,
            0.00934959718369108,
            0.023261064420787285,
            0.04396023646922401,
            0.07475898085675112,
            0.12058509668537296,
            0.18877076248766902,
            0.2902256847920067,
            0.44118265116708,
            0.6657947762329006,
            1.0,
        )
    )


def test_unequal_xy_controls_follow_cr_surf_axis_semantics() -> None:
    x_axis = np.linspace(-1.0, 1.0, 3)
    y_axis = np.linspace(-2.0, 2.0, 3)
    x, y = np.meshgrid(x_axis, y_axis)

    topology = build_surface_topology(
        x,
        y,
        (),
        nelem_x=2,
        nelem_y=3,
        hole_radial_cells=1,
        hole_outer_inner_ratio=1.0,
        tolerance=1.0e-10,
    )

    assert len(topology.quads) == 2 * 2 * 2 * 3
    assert len(topology.outer_edges["xmin"]) == 2 * 2
    assert len(topology.outer_edges["xmax"]) == 2 * 2
    assert len(topology.outer_edges["ymin"]) == 2 * 3
    assert len(topology.outer_edges["ymax"]) == 2 * 3


def test_python_only_example_has_no_mesh_source_or_external_solver_requirement(
    monkeypatch,
) -> None:
    setup = load_setup(CONFIG)
    surface = build_surface_grid(setup.surface_source)
    monkeypatch.setattr(
        headless,
        "resolve_castem_exe",
        lambda _version: (_ for _ in ()).throw(
            AssertionError("Cast3M must not be resolved")
        ),
    )

    assert setup.mesh_mode == "python_only"
    assert setup.mesh_template is None
    assert setup.fiss_template is None
    assert validate_setup(
        setup,
        check_castem=True,
        surface_grid=surface,
    ) == (64, 64)


def test_python_only_rejects_external_gmsh_viewer_option() -> None:
    setup = replace(load_setup(CONFIG), open_gmsh=True)
    surface = build_surface_grid(setup.surface_source)

    with pytest.raises(ValueError, match="does not invoke Gmsh"):
        validate_setup(setup, check_castem=False, surface_grid=surface)


def test_python_only_chamber_topology_matches_reviewed_reference_counts() -> None:
    setup = load_setup(CONFIG)
    surface = build_surface_grid(setup.surface_source)

    mesh = build_python_volume_mesh(
        surface.x,
        surface.y,
        surface.zmin,
        surface.zmax,
        setup.params,
    )

    assert mesh.counts == {
        "points": 830579,
        "hexa8": 798400,
        "surface_quads": 11020,
        "crack_hexa8": 661200,
        "inlet_hexa8": 68600,
        "outlet_hexa8": 68600,
        "exterior_quads": 63880,
    }
    expected_boundaries = {
        "castem_mesh_surf_min": 11020,
        "castem_mesh_surf_max": 11020,
        "castem_mesh_surf_mean": 11020,
        "castem_mesh_surf_xmin": 5880,
        "castem_mesh_surf_xmax": 5880,
        "castem_mesh_surf_ymin": 5880,
        "castem_mesh_surf_ymax": 5880,
        "castem_mesh_surf_trou_1": 3840,
        "castem_mesh_surf_trou_2": 3840,
        "castem_mesh_surf_all": 63880,
        "castem_mesh_surf_inlet_all": 17080,
        "castem_mesh_surf_inlet_interface": 6860,
        "castem_mesh_surf_inlet_outer": 6860,
        "castem_mesh_surf_inlet_top": 980,
        "castem_mesh_surf_inlet_bottom": 980,
        "castem_mesh_surf_inlet_xmin": 700,
        "castem_mesh_surf_inlet_xmax": 700,
        "castem_mesh_surf_outlet_all": 17080,
        "castem_mesh_surf_outlet_interface": 6860,
        "castem_mesh_surf_outlet_outer": 6860,
        "castem_mesh_surf_outlet_top": 980,
        "castem_mesh_surf_outlet_bottom": 980,
        "castem_mesh_surf_outlet_xmin": 700,
        "castem_mesh_surf_outlet_xmax": 700,
    }
    assert {
        name: len(quads)
        for name, quads in mesh.boundaries.items()
    } == expected_boundaries
    quality = hexa8_quality(mesh.points, mesh.hexes)
    assert quality["valid"] is True
    assert quality["nonpositive_jacobians"] == 0
    assert quality["minimum_scaled_jacobian"] == pytest.approx(
        0.4115765578310503
    )


def test_python_only_no_hole_writes_bdf_med_and_preview() -> None:
    meshio = pytest.importorskip("meshio")
    workdir = ROOT / "_runtime" / "test-python-volume-mesher" / uuid4().hex
    x_axis = np.linspace(-0.4, 0.4, 3)
    y_axis = np.linspace(-0.3, 0.3, 3)
    x, y = np.meshgrid(x_axis, y_axis)
    zmin = 2.0e-5 * x - 1.0e-5 * y
    zmax = zmin + 2.5e-4
    params = baseline.CastemMainParams(
        nelem_x=2,
        nelem_y=3,
        nelem_z=2,
        re_fact_z=1.025,
        num_el_fill=3,
        re_fact_hole=4.0,
        holes_enabled=False,
    )

    result = write_python_mesh_outputs(
        workdir,
        x,
        y,
        zmin,
        zmax,
        params,
        export_med=True,
    )

    assert result.mesh.counts["surface_quads"] == 24
    assert result.mesh.counts["crack_hexa8"] == 96
    assert result.quality["valid"] is True
    assert result.volume_bdf.is_file()
    assert result.preview_path.is_file()
    assert result.med_path is not None and result.med_path.is_file()
    assert len(result.written_bdfs) == 8
    med = meshio.read(result.med_path)
    assert len(med.cells_dict["hexahedron"]) == 96


def test_python_only_rejects_zero_opening() -> None:
    x, y = np.meshgrid(np.linspace(0.0, 1.0, 2), np.linspace(0.0, 1.0, 2))
    z = np.zeros_like(x)
    params = baseline.CastemMainParams()

    with pytest.raises(ValueError, match="strictly positive"):
        build_python_volume_mesh(x, y, z, z, params)


def test_python_only_volume_supports_every_documented_hole_shape() -> None:
    x, y, zmin, zmax = load_surface_csvs(
        INPUT / "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        INPUT / "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    )
    shapes = [
        HoleGeometry("circle", -0.25, 0.25, radius=0.045),
        HoleGeometry(
            "rectangle",
            0.23,
            0.25,
            width=0.10,
            height=0.06,
            rotation_degrees=15.0,
        ),
        HoleGeometry(
            "triangle",
            -0.25,
            -0.23,
            side_length=0.10,
            rotation_degrees=-10.0,
        ),
        HoleGeometry(
            "regular_polygon",
            0.23,
            -0.23,
            radius=0.055,
            sides=6,
            rotation_degrees=30.0,
        ),
    ]
    params = baseline.CastemMainParams(
        nelem_x=2,
        nelem_y=2,
        nelem_z=1,
        re_fact_z=1.025,
        num_el_fill=5,
        re_fact_hole=5.0,
        holes_enabled=True,
    )
    params.hole_shapes = shapes

    mesh = build_python_volume_mesh(x, y, zmin, zmax, params)

    assert len(mesh.topology.points_per_hole) == 4
    assert all(count >= 32 for count in mesh.topology.points_per_hole)
    assert {
        f"castem_mesh_surf_trou_{index}"
        for index in range(1, 5)
    }.issubset(mesh.boundaries)
    assert hexa8_quality(mesh.points, mesh.hexes)["valid"] is True
