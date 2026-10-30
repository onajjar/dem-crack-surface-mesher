import dataclasses
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

import castem_pipeline_gui_t13 as baseline
import castem_pipeline_headless as headless
import openfoam_export as of
from chamber_geometry import ChamberParameters
from python_volume_mesher import build_python_volume_mesh, write_python_mesh_outputs

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_BDF = ROOT / "examples" / "output" / "combined_ti60_crpa1_smfa5_numsp50_opmin1.bdf"
HOLES_BDF = ROOT / "examples" / "multiple-holes" / "output" / "combined_ti60_crpa1_smfa5_numsp50_opmin1.bdf"

WIDTH, LENGTH, GAP = 0.04, 0.03, 1.0e-4


def _surfaces(nx=5, ny=4, warp=0.0):
    """Flat plates, or a seeded rough crack whose opening varies from 0.2 to 1.8 GAP."""

    x, y = np.meshgrid(np.linspace(-WIDTH / 2, WIDTH / 2, nx), np.linspace(0.0, LENGTH, ny))
    if not warp:
        return x, y, np.zeros_like(x), np.full_like(x, GAP)
    rng = np.random.default_rng(3)
    zmin = warp * rng.standard_normal(x.shape)
    return x, y, zmin, zmin + GAP * (0.2 + 1.6 * rng.random(x.shape))


def _params(nz=3, chambers=False):
    params = baseline.CastemMainParams(
        nelem_x=1,
        nelem_y=1,
        nelem_z=nz,
        re_fact_z=1.0,
        num_el_fill=3,
        re_fact_hole=4.0,
        holes_enabled=False,
    )
    params.chambers = ChamberParameters(
        enabled=chambers,
        height=0.004,
        inlet_length=0.005,
        outlet_length=0.005,
        inlet_height_elements=4,
        outlet_height_elements=4,
        inlet_length_elements=3,
        outlet_length_elements=3,
    )
    return params


def _python_mesh(**kwargs):
    chambers = kwargs.pop("chambers", False)
    nz = kwargs.pop("nz", 3)
    return build_python_volume_mesh(*_surfaces(**kwargs), _params(nz, chambers))


def _patch_sizes(poly):
    return {patch["name"]: patch["nFaces"] for patch in poly.patches}


def _read_foam_lists(path: Path) -> list[np.ndarray]:
    """Every List body of an OpenFOAM file (ascii or binary), as flat arrays."""

    data = path.read_bytes()
    header_end = data.index(b"}", data.index(b"FoamFile")) + 1
    binary = b"format      binary" in data[:header_end]
    body = data[header_end:]
    kind = re.search(rb"class\s+(\w+);", data[:header_end]).group(1).decode()
    lists, position = [], 0
    while True:
        match = re.compile(rb"\n(\d+)\s*\n?\(").search(body, position)
        if match is None:
            return lists
        count, start = int(match.group(1)), match.end()
        if binary:
            if kind == "vectorField":
                size, dtype = 24 * count, np.float64
            elif kind == "faceCompactList" and not lists:
                size, dtype = 4 * count, np.int32
            else:
                size, dtype = 4 * count, np.int32
            lists.append(np.frombuffer(body[start:start + size], dtype=dtype))
            position = start + size + 1
        else:
            end = body.index(b"\n)", start)
            text = body[start:end].decode()
            if kind == "faceList":
                rows = re.findall(r"\d+\(([^)]*)\)", text)
                lists.append([np.array(row.split(), dtype=np.int64) for row in rows])
            else:
                lists.append(np.array(text.replace("(", " ").replace(")", " ").split(), float))
            position = end + 2


def _assert_sound(poly, volume=None):
    quality = of.mesh_quality(poly)
    assert quality["nonpositive_volumes"] == 0
    assert quality["open_cells"] == 0
    assert quality["face_pyramid_failures"] == 0
    if volume is not None:
        assert quality["total_volume"] == pytest.approx(volume, rel=1.0e-9)
    owner, neighbour = poly.owner[: poly.n_internal_faces], poly.neighbour
    assert np.all(owner < neighbour)
    assert np.all(np.diff(owner) >= 0)
    same_owner = np.diff(owner) == 0
    assert np.all(np.diff(neighbour)[same_owner] >= 0)
    starts = [patch["startFace"] for patch in poly.patches]
    sizes = [patch["nFaces"] for patch in poly.patches]
    assert starts[0] == poly.n_internal_faces
    assert np.all(np.diff(starts) == sizes[:-1])
    assert starts[-1] + sizes[-1] == len(poly.faces)
    return quality


def test_nastran_reals_and_patch_rules_parse() -> None:
    assert of.nastran_float("-5.5-3") == pytest.approx(-5.5e-3)
    assert of.nastran_float("1.25+2") == pytest.approx(125.0)
    assert of.nastran_float(" 3.0D-1 ") == pytest.approx(0.3)
    rules = of.parse_patch_rules("in=patch:ymin; out=patch:castem_mesh_surf_ymax.bdf; w=wall:min+max")
    assert [(rule.name, rule.type, rule.surfaces) for rule in rules] == [
        ("in", "patch", ("ymin",)),
        ("out", "patch", ("ymax",)),
        ("w", "wall", ("min", "max")),
    ]
    with pytest.raises(ValueError, match="Unsupported patch type"):
        of.parse_patch_rules("a=solid:min")
    with pytest.raises(ValueError, match="unique"):
        of.parse_patch_rules("a=wall:min; a=wall:max")


def test_settings_mapping_round_trips_and_rejects_bad_values() -> None:
    settings = of.OpenFOAMSettings(solver="rhoSimpleFoam", openfoam_version="org", density=1.2)
    assert of.settings_from_mapping(of.settings_to_mapping(settings)) == settings
    with pytest.raises(ValueError, match="Unknown"):
        of.settings_from_mapping({"inlet_presure": "2e5"})
    with pytest.raises(ValueError, match="inlet_pressure"):
        of.settings_from_mapping({"inlet_pressure": "-1"})
    with pytest.raises(ValueError, match="flow_direction"):
        of.OpenFOAMSettings(flow_direction="+z").validated()


def test_constant_opening_keeps_hexahedra_and_volume() -> None:
    mesh = _python_mesh()
    poly = of.build_polymesh(of.mesh_from_python(mesh))

    _assert_sound(poly, WIDTH * LENGTH * GAP)
    # nelem_z = 3 per half opening gives 6 layers.
    assert poly.report["cell_counts"] == {"hex": 4 * 3 * 6, "hex_in_vertical_columns": 72}
    assert _patch_sizes(poly) == {
        "inlet": 4 * 6,
        "outlet": 4 * 6,
        "lowerWall": 12,
        "upperWall": 12,
        "sideWalls": 2 * 3 * 6,
    }
    assert poly.report["quality"]["max_non_orthogonality_deg"] < 1.0e-6
    # A mesh in millimetres becomes metres with length_scale = 1e-3.
    scaled = of.build_polymesh(of.mesh_from_python(mesh), of.OpenFOAMSettings(length_scale=1.0e-3))
    assert scaled.report["quality"]["total_volume"] == pytest.approx(WIDTH * LENGTH * GAP * 1.0e-9)
    assert _patch_sizes(scaled) == _patch_sizes(poly)


def test_warped_columns_are_split_only_where_pyramids_fail() -> None:
    source = of.mesh_from_python(_python_mesh(nx=9, ny=7, warp=2.0e-4))
    unsplit = of.build_polymesh(source, of.OpenFOAMSettings(cell_split="none"))
    auto = of.build_polymesh(source)
    prism = of.build_polymesh(source, of.OpenFOAMSettings(cell_split="prism"))

    assert unsplit.report["quality"]["face_pyramid_failures"] > 0
    volume = unsplit.report["quality"]["total_volume"]
    for poly in (auto, prism):
        # Triangulating a warped quad redefines its surface, so volumes agree only roughly.
        assert _assert_sound(poly)["total_volume"] == pytest.approx(volume, rel=2.0e-2)
        assert _patch_sizes(poly)["inlet"] == _patch_sizes(unsplit)["inlet"]
    counts = auto.report["cell_counts"]
    assert 0 < counts["hex_split_into_prisms"] < counts["hex_in_vertical_columns"]
    assert prism.report["cell_counts"]["prism"] == 2 * len(source.cells["hex"])
    # Split triangles stay on the wall patches: twice the quads of the walls.
    assert _patch_sizes(prism)["lowerWall"] == 2 * _patch_sizes(unsplit)["lowerWall"]


def test_chambers_give_zones_and_oriented_crack_face_zones() -> None:
    mesh = _python_mesh(chambers=True)
    source = of.mesh_from_python(mesh)
    poly = of.build_polymesh(source)

    quality = _assert_sound(poly)
    sizes = _patch_sizes(poly)
    assert sizes["inlet"] == len(mesh.boundaries["castem_mesh_surf_inlet_outer"])
    assert sizes["outlet"] == len(mesh.boundaries["castem_mesh_surf_outlet_outer"])
    assert set(sizes) == {
        "inlet", "outlet", "lowerWall", "upperWall", "sideWalls",
        "inletChamberWalls", "outletChamberWalls",
    }
    assert {zone: len(cells) for zone, cells in poly.cell_zones.items()} == {
        "crack": len(mesh.hexes) - len(mesh.inlet_hexes) - len(mesh.outlet_hexes),
        "inletChamber": len(mesh.inlet_hexes),
        "outletChamber": len(mesh.outlet_hexes),
    }
    crack_volume = poly.cell_volumes[poly.cell_zones["crack"]].sum()
    assert crack_volume == pytest.approx(WIDTH * LENGTH * GAP, rel=1.0e-9)
    assert quality["total_volume"] > crack_volume
    # Thin crack layers meet the first chamber cells: the jump is reported and warned.
    assert quality["max_cell_size_jump"] > 20.0
    assert any("differ by more than 20x" in item for item in poly.report["warnings"])
    _centres, areas = of._openfoam_face_geometry(poly.points, poly.faces)
    for zone in ("crackInlet", "crackOutlet"):
        faces, flip = poly.face_zones[zone]
        assert len(faces) == 4 * 6
        assert np.all(faces < poly.n_internal_faces)
        oriented = np.where(flip, -1.0, 1.0) * areas[faces, 1]
        assert np.all(oriented > 0.0)
        assert oriented.sum() == pytest.approx(WIDTH * GAP, rel=1.0e-9)
    # A combined BDF has no volume groups: the crack mouths give back the same zones.
    bare = of.build_polymesh(dataclasses.replace(source, cell_zones={}))
    assert bare.cell_zones.keys() == poly.cell_zones.keys()
    for zone, cells in poly.cell_zones.items():
        assert np.array_equal(bare.cell_zones[zone], cells)


def test_workdir_export_matches_memory_and_writes_case(tmp_path) -> None:
    x, y, zmin, zmax = _surfaces(warp=2.0e-4)
    params = _params(chambers=True)
    result = write_python_mesh_outputs(tmp_path / "run", x, y, zmin, zmax, params, export_med=False)
    from_memory = of.build_polymesh(of.mesh_from_python(result.mesh))
    from_files = of.build_polymesh(of.mesh_from_workdir(tmp_path / "run"))
    assert from_files.report["n_cells"] == from_memory.report["n_cells"]
    assert _patch_sizes(from_files) == _patch_sizes(from_memory)
    assert from_files.report["quality"]["total_volume"] == pytest.approx(
        from_memory.report["quality"]["total_volume"], rel=1.0e-9
    )

    exported = of.export_workdir(tmp_path / "run", of.OpenFOAMSettings(write_format="binary"))
    case = exported.case_directory
    assert case == tmp_path / "run" / "openfoam_case"
    for name in ("points", "faces", "owner", "neighbour", "boundary", "cellZones", "faceZones"):
        assert (case / "constant" / "polyMesh" / name).is_file()
    for name in ("0/U", "0/p", "system/controlDict", "system/fvSchemes", "system/fvSolution", "Allrun"):
        assert (case / name).is_file()
    points = _read_foam_lists(case / "constant" / "polyMesh" / "points")[0].reshape(-1, 3)
    offsets, labels = _read_foam_lists(case / "constant" / "polyMesh" / "faces")
    owner = _read_foam_lists(case / "constant" / "polyMesh" / "owner")[0]
    neighbour = _read_foam_lists(case / "constant" / "polyMesh" / "neighbour")[0]
    # The BDF round trip rounds coordinates, so the case is compared with the files.
    poly = from_files
    assert np.allclose(from_files.points, from_memory.points, rtol=0.0, atol=1.0e-9)
    assert np.array_equal(points, poly.points)
    assert np.array_equal(owner, poly.owner)
    assert np.array_equal(neighbour, poly.neighbour)
    assert np.array_equal(labels, poly.faces[poly.faces >= 0])
    assert offsets[-1] == labels.size
    report = json.loads((case / of.EXPORT_MARKER).read_text())
    assert report["n_cells"] == poly.n_cells
    assert report["incompressible_model"]["density"] == pytest.approx(
        0.5 * (111325.0 + 101325.0) / (287.05 * 298.15)
    )


def test_ascii_round_trip_and_case_dictionaries_per_distribution(tmp_path) -> None:
    source = of.mesh_from_python(_python_mesh(chambers=True))
    com = of.export_openfoam(source, tmp_path / "com", of.OpenFOAMSettings(solver="rhoSimpleFoam"))
    org = of.export_openfoam(
        source,
        tmp_path / "org",
        of.OpenFOAMSettings(solver="rhoSimpleFoam", openfoam_version="org"),
    )
    faces = _read_foam_lists(com.case_directory / "constant" / "polyMesh" / "faces")[0]
    poly = of.build_polymesh(source)
    assert len(faces) == len(poly.faces)
    assert all(np.array_equal(row, ref[ref >= 0]) for row, ref in zip(faces, poly.faces))

    control_com = (com.case_directory / "system" / "controlDict").read_text()
    control_org = (org.case_directory / "system" / "controlDict").read_text()
    assert "application     rhoSimpleFoam;" in control_com
    assert "type            solverInfo;" in control_com
    assert "application     foamRun;" in control_org
    assert "solver          fluid;" in control_org
    assert "operation       orientedSum;" in control_org
    for case in (com.case_directory, org.case_directory):
        solution = (case / "system" / "fvSolution").read_text()
        assert "SIMPLE\n{" in solution and "PIMPLE\n{" in solution
        temperature = (case / "0" / "T").read_text()
        assert "type totalTemperature;" in temperature and "gamma " in temperature
        thermo = (case / "constant" / "physicalProperties").read_text()
        assert "Hf              0;" in thermo and "hf              0;" in thermo
        assert "\r" not in (case / "Allrun").read_text()
        schemes = (case / "system" / "fvSchemes").read_text()
        assert "Gauss harmonic" in schemes and "interpolate((rho*rAU)) harmonic;" in schemes
        assert "consistent      no;" in solution
    # OpenFOAM.org takes pressure limits from fvConstraints only.
    solution_com = (com.case_directory / "system" / "fvSolution").read_text()
    solution_org = (org.case_directory / "system" / "fvSolution").read_text()
    assert "pMinFactor" in solution_com and "pMinFactor" not in solution_org
    assert not (com.case_directory / "system" / "fvConstraints").exists()
    assert "limitPressure" in (org.case_directory / "system" / "fvConstraints").read_text()


def test_previous_export_is_archived_and_foreign_directory_is_kept(tmp_path) -> None:
    source = of.mesh_from_python(_python_mesh())
    case = tmp_path / "case"
    of.export_openfoam(source, case, of.OpenFOAMSettings(solver="none"))
    second = of.export_openfoam(source, case, of.OpenFOAMSettings(solver="none"))
    assert second.archived_previous is not None
    assert (second.archived_previous / of.EXPORT_MARKER).is_file()
    assert (case / of.EXPORT_MARKER).is_file()

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("user data")
    with pytest.raises(FileExistsError, match="not written by this exporter"):
        of.export_openfoam(source, foreign, of.OpenFOAMSettings(solver="none"))
    assert (foreign / "keep.txt").read_text() == "user data"


def test_closed_front_cells_collapse_or_drop() -> None:
    # Two hexahedra side by side; the right one is closed at x = 2 (wedge) and a
    # third, zero-thickness one closes completely.  Coincident nodes come in as
    # separate GRIDs, as Cast3M writes them.
    bottom = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0), (2, 1, 0)]
    top = [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1), (2, 0, 0), (2, 1, 0)]
    flat = [(2, 0, 0), (3, 0, 0), (3, 1, 0), (2, 1, 0)]
    points = np.array(bottom + top + flat + flat, dtype=float)
    hexes = np.array(
        [
            (0, 1, 2, 3, 6, 7, 8, 9),
            (1, 4, 5, 2, 7, 10, 11, 8),
            (12, 13, 14, 15, 16, 17, 18, 19),
        ]
    )
    surfaces = {
        "min": np.array([(0, 1, 2, 3), (1, 4, 5, 2)]),
        "max": np.array([(6, 7, 8, 9), (7, 10, 11, 8)]),
        "ymin": np.array([(0, 1, 7, 6), (1, 4, 10, 7)]),
        "ymax": np.array([(3, 2, 8, 9), (2, 5, 11, 8)]),
        "xmin": np.array([(0, 3, 9, 6)]),
    }
    source = of.SourceMesh(points, {"hex": hexes}, surfaces)
    poly = of.build_polymesh(source, of.OpenFOAMSettings(cell_split="none"))

    _assert_sound(poly, 1.0 + 0.5)
    assert poly.report["dropped_zero_volume_cells"] == 1
    assert poly.report["merged_points"] >= 6
    assert _patch_sizes(poly)["inlet"] == 2
    assert sorted(int((row >= 0).sum()) for row in poly.faces) .count(3) == 2


@pytest.mark.parametrize("path", [REFERENCE_BDF, HOLES_BDF], ids=["reference", "holes"])
def test_bundled_cast3m_combined_bdfs_export(path, tmp_path) -> None:
    source = of.mesh_from_combined_bdf(path)
    result = of.export_openfoam(source, tmp_path / "case", of.OpenFOAMSettings(solver="none"))
    report = result.report
    sizes = {patch["name"]: patch["nFaces"] for patch in report["patches"]}
    assert sizes["inlet"] == sizes["outlet"] > 0
    assert sizes["lowerWall"] == sizes["upperWall"] > 0
    assert "otherWalls" not in sizes
    assert report["quality"]["face_pyramid_failures"] == 0
    assert report["quality"]["open_cells"] == 0
    if path == HOLES_BDF:
        assert sizes["hole1"] > 0 and sizes["hole2"] > 0


def test_headless_mesh_run_exports_openfoam_case(tmp_path) -> None:
    config = tmp_path / "run.ini"
    config.write_text(
        "\n".join(
            [
                "[run]",
                "operation = mesh",
                "working_directory = work",
                "[files]",
                "[surface]",
                "mode = constant",
                "points_x = 5",
                "points_y = 4",
                "size_x = 0.04",
                "size_y = 0.03",
                "constant_zmin = 0.0",
                "constant_zmax = 1e-4",
                "[naming]",
                "ti = 60",
                "crpa = 1",
                "smfa = 0.05",
                "numspa = 5",
                "opmin = 1e-6",
                "[mesh]",
                "mode = python_only",
                "elements_x = 1",
                "elements_y = 1",
                "elements_z = 2",
                "geometric_tolerance = 1e-10",
                "z_inflation_factor = 1.0",
                "hole_radial_cells = 6",
                "hole_outer_inner_ratio = 5",
                "export_med = false",
                "open_gmsh = false",
                "export_stl = false",
                "merge_bdfs = false",
                "export_openfoam = true",
                "[openfoam]",
                "solver = rhoSimpleFoam",
                "openfoam_version = org",
                "inlet_pressure = 2e5",
                "[holes]",
                "enabled = false",
                "[fiss]",
                "model = POISEU_GELAIN_2012",
                "gas = PARF",
                "condensation = MASS",
                "critical_reynolds = 10",
                "wall_temperature = 25",
                "downstream_pressure = 101325",
                "steam_pressure = 0",
                "line_subdivisions = 5",
                "pressure_mode = single",
                "pressure_in = 5e5",
                "temperature_mode = single",
                "temperature_in = 25",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    for attempt in range(2):
        assert headless.main([str(config)]) == 0
    summary = json.loads((tmp_path / "work" / "headless-run-report.json").read_text())
    openfoam = summary["mesh"]["openfoam"]
    assert openfoam["success"] is True
    assert openfoam["openfoam_version"] == "org"
    assert openfoam["patches"]["inlet"] == 4 * 4  # 4 columns, 2 x elements_z layers
    assert openfoam["archived_previous"] is not None
    case = Path(openfoam["case_directory"])
    assert "application     foamRun;" in (case / "system" / "controlDict").read_text()
    assert "uniform 200000.0;" in (case / "0" / "p").read_text()


@pytest.mark.skipif(
    shutil.which("checkMesh") is None or not os.environ.get("WM_PROJECT_DIR"),
    reason="no sourced OpenFOAM environment",
)
def test_check_mesh_accepts_exported_case(tmp_path) -> None:
    source = of.mesh_from_python(_python_mesh(nx=9, ny=7, warp=2.0e-4, chambers=True))
    result = of.export_openfoam(source, tmp_path / "case", of.OpenFOAMSettings(solver="none"))
    output = subprocess.run(
        ["checkMesh"], cwd=result.case_directory, capture_output=True, text=True, check=False
    )
    assert output.returncode == 0, output.stdout[-2000:]
    assert "Mesh OK." in output.stdout


def test_workbench_card_builds_validated_settings() -> None:
    from types import SimpleNamespace

    from castem_pipeline_gui_scientific import (
        OPENFOAM_SOLVER_LABELS,
        OPENFOAM_VERSION_LABELS,
        ScientificApp,
    )

    class _Variable:
        def __init__(self, value) -> None:
            self.value = value

        def get(self):
            return self.value

    app = SimpleNamespace(
        openfoam_enabled_var=_Variable(True),
        openfoam_solver_var=_Variable(OPENFOAM_SOLVER_LABELS[1]),
        openfoam_version_var=_Variable(OPENFOAM_VERSION_LABELS[1]),
        openfoam_split_var=_Variable("prism"),
        openfoam_case_var=_Variable(" my_case "),
        openfoam_inlet_pressure_var=_Variable("2e5"),
        openfoam_outlet_pressure_var=_Variable("101325"),
        openfoam_temperature_var=_Variable("300"),
        openfoam_iterations_var=_Variable("200"),
        openfoam_scale_var=_Variable("1e-3"),
    )
    settings = ScientificApp._openfoam_settings(app)
    assert settings.solver == "rhoSimpleFoam"
    assert settings.openfoam_version == "org"
    assert settings.case_directory == "my_case"
    assert settings.length_scale == pytest.approx(1.0e-3)
    assert settings.write_interval == 200
    app.openfoam_iterations_var = _Variable("2.5")
    with pytest.raises(ValueError, match="whole number"):
        ScientificApp._openfoam_settings(app)
    app.openfoam_iterations_var = _Variable("200")
    app.openfoam_inlet_pressure_var = _Variable("-1")
    with pytest.raises(ValueError, match="inlet_pressure"):
        ScientificApp._openfoam_settings(app)
    app.openfoam_enabled_var = _Variable(False)
    assert ScientificApp._openfoam_settings(app) is None
