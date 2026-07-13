from pathlib import Path

import pytest

from castem_pipeline_headless import load_setup, validate_setup


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples" / "scientific-run.ini"


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
    setup.params.holes[0].r = 0.0

    with pytest.raises(ValueError, match="radius"):
        validate_setup(setup)
