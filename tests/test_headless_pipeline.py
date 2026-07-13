from dataclasses import replace
from pathlib import Path

import pytest

from castem_pipeline_headless import load_setup, validate_setup
from python_hole_interpolation import HoleGeometry


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples" / "scientific-run.ini"
SHAPE_CONFIG = ROOT / "examples" / "shaped-holes" / "all-shapes.ini"


def test_example_headless_config_covers_conformal_multiple_holes() -> None:
    setup = load_setup(CONFIG)

    assert setup.operation == "mesh"
    assert setup.mesh_mode == "python"
    assert setup.params.nelem_x == setup.params.nelem_y == 2
    assert len(setup.params.holes) == 2
    circle_edges = validate_setup(setup)
    assert circle_edges == (64, 64)


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
