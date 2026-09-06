from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

import deap_crack_surface as deap
from castem_pipeline_headless import load_setup, validate_setup
from surface_generation import SurfaceGrid, build_surface_grid

ROOT = Path(__file__).resolve().parents[1]


def test_deap_closes_overlap_and_extends_lower_wall_without_lifting_contact(monkeypatch):
    x = np.array([.2, .8, .8, .2, .3, .4, .5, .6, .7, .4, .6])
    y = np.array([.2, .2, .8, .8, .3, .4, .5, .6, .7, .6, .4])
    lower_points = np.column_stack((x, y, np.zeros_like(x)))
    upper_points = lower_points + [0, 0, .001]
    component = deap.CrackComponent(np.arange(11), lower_points, upper_points)
    monkeypatch.setattr(deap, "extract_components", lambda config: [component])
    lower = np.arange(100, dtype=float).reshape(10, 10) / 1000
    raw_opening = np.full_like(lower, .001)
    raw_opening[4, 4] = -.001
    raw_upper = lower + raw_opening
    calls = iter([lower.copy(), raw_upper.copy()])
    monkeypatch.setattr(deap, "quadratic_loess_surface", lambda *a, **kw: next(calls))
    config = deap.SurfaceConfig(
        case_dir=ROOT / "examples/deap/1_simple/results", time_step=10,
        grid_resolution=10, orientation="XY", bounding_box=(0, 1, 0, 1, 0, 1),
    )
    monkeypatch.setattr(deap, "_read_limits", lambda config: (0, 1, 0, 1, 0, 1))
    result = deap.reconstruct_surface(config)
    expected_lower = lower[np.ix_(np.clip(np.arange(10), 2, 7),
                                 np.clip(np.arange(10), 2, 7))]
    expected_opening = np.zeros_like(lower)
    expected_opening[2:8, 2:8] = (raw_upper - lower)[2:8, 2:8]
    expected_opening[4, 4] = 0
    np.testing.assert_array_equal(result.z_min, expected_lower)
    np.testing.assert_array_equal(result.z_max, expected_lower + expected_opening)
    assert result.z_min[4, 4] == result.z_max[4, 4]


def test_python_only_preflight_rejects_contact_without_altering_surface():
    setup = load_setup(ROOT / "examples/docker/constant-planes.ini")
    grid = build_surface_grid(setup.surface_source)
    upper = grid.zmax.copy()
    upper[0, 0] = grid.zmin[0, 0]
    contact = SurfaceGrid(grid.x, grid.y, grid.zmin, upper, mode="csv")
    before = upper.copy()
    with pytest.raises(ValueError, match="strictly positive"):
        validate_setup(setup, surface_grid=contact)
    np.testing.assert_array_equal(contact.zmax, before)


def test_span_zero_is_accepted_by_pipeline_like_matlab():
    setup = load_setup(ROOT / "examples/deap/1_simple/run.ini")
    grid = build_surface_grid(setup.surface_source)
    setup.params.re_smfa = 0.0
    setup = replace(setup, operation="characterize", characterization_enabled=True)
    assert validate_setup(setup, surface_grid=grid) == ()
