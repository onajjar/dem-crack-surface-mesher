from dataclasses import replace
from pathlib import Path
from tkinter import ttk

import pytest

import castem_pipeline_gui_scientific as scientific
from castem_pipeline_headless import load_setup, validate_setup
from characterization_gui import CharacterizationPanel
from python_hole_interpolation import HoleGeometry

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples" / "scientific-run.ini"
SHAPE_CONFIG = ROOT / "examples" / "shaped-holes" / "all-shapes.ini"
CHARACTERIZATION_CONFIG = (
    ROOT / "examples" / "characterization" / "characterize-only.ini"
)


def test_scientific_launcher_dispatches_headless_validation(capsys) -> None:
    result = scientific.main(["--headless", str(CONFIG), "--validate-only"])

    assert result == 0
    output = capsys.readouterr()
    assert '"valid": true' in output.out
    assert '"source": "csv_filenames"' in output.out
    assert output.err == ""


def test_example_headless_config_covers_conformal_multiple_holes() -> None:
    setup = load_setup(CONFIG)

    assert setup.operation == "mesh"
    assert setup.mesh_mode == "python"
    assert setup.params.nelem_x == setup.params.nelem_y == 2
    assert setup.params.opti_visu == 0
    assert setup.open_gmsh is False
    assert len(setup.params.holes) == 2
    circle_edges = validate_setup(setup)
    assert circle_edges == (64, 64)


def test_gmsh_option_never_enables_cast3m_visualization() -> None:
    setup = replace(load_setup(CONFIG), open_gmsh=True)

    assert setup.open_gmsh is True
    assert setup.params.opti_visu == 0


def test_headless_config_rejects_nonpositive_hole_radius() -> None:
    setup = load_setup(CONFIG)
    setup.params.hole_shapes[0] = HoleGeometry("circle", -0.2, 0.2, radius=0.0)

    with pytest.raises(ValueError, match="radius"):
        validate_setup(setup)


def test_all_shape_headless_example_is_conformal() -> None:
    setup = load_setup(SHAPE_CONFIG)

    assert [hole.shape for hole in setup.params.hole_shapes] == [
        "circle",
        "rectangle",
        "triangle",
        "regular_polygon",
    ]
    edges = validate_setup(setup)
    assert len(edges) == 4
    assert all(count >= 32 for count in edges)


def test_non_circular_shapes_are_rejected_in_reference_mode() -> None:
    setup = replace(load_setup(SHAPE_CONFIG), mesh_mode="reference")

    with pytest.raises(ValueError, match="require mesh mode = python"):
        validate_setup(setup)


def test_characterization_only_config_does_not_require_castem() -> None:
    setup = load_setup(CHARACTERIZATION_CONFIG)

    assert setup.operation == "characterize"
    assert setup.characterization_enabled is True
    assert setup.characterization.aperture_method == "local_normal"
    assert setup.characterization.flow_direction == "Y"
    assert validate_setup(setup, check_castem=True) == ()


def test_embedded_characterization_uses_automatic_analysis_defaults() -> None:
    assert issubclass(CharacterizationPanel, ttk.Frame)
    config = CharacterizationPanel._config(object())
    assert config.aperture_method == "local_normal"
    assert config.flow_direction == "Y"
    assert config.hurst_bootstrap_samples == 100
