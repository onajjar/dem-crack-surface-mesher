from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from castem_pipeline_headless import load_setup, validate_setup
from python_hole_interpolation import load_surface_csvs
from surface_generation import SurfaceSource, build_surface_grid, write_surface_grid

ROOT = Path(__file__).resolve().parents[1]
SURFACE_EXAMPLES = ROOT / "examples" / "surfaces"


def _fractal_source(**changes) -> SurfaceSource:
    source = SurfaceSource(
        mode="fractal",
        points_x=32,
        points_y=24,
        size_x=1.2,
        size_y=0.9,
        hurst_exponent=0.75,
        fractal_dimension=None,
        rms_height=4.0e-5,
        mean_aperture=2.0e-4,
        random_seed=1234,
    )
    return replace(source, **changes)


def test_fractal_surface_is_reproducible_and_normalized() -> None:
    first = build_surface_grid(_fractal_source())
    second = build_surface_grid(_fractal_source())
    mean_surface = 0.5 * (first.zmin + first.zmax)

    assert first.shape == (24, 32)
    assert np.array_equal(first.x, second.x)
    assert np.array_equal(first.zmin, second.zmin)
    assert np.isclose(mean_surface.mean(), 0.0, atol=1.0e-18)
    assert np.isclose(np.sqrt(np.mean(mean_surface**2)), 4.0e-5, rtol=1.0e-12)
    assert np.allclose(first.opening, 2.0e-4, rtol=0.0, atol=1.0e-18)


def test_hurst_and_fractal_dimension_parameterizations_are_equivalent() -> None:
    by_hurst = build_surface_grid(_fractal_source(hurst_exponent=0.8))
    by_dimension = build_surface_grid(
        _fractal_source(hurst_exponent=None, fractal_dimension=2.2)
    )

    assert np.allclose(by_hurst.zmin, by_dimension.zmin, rtol=1.0e-13, atol=1.0e-18)
    assert np.allclose(by_hurst.zmax, by_dimension.zmax, rtol=1.0e-13, atol=1.0e-18)


def test_constant_surface_has_requested_extent_and_z_values() -> None:
    grid = build_surface_grid(
        SurfaceSource(
            mode="constant",
            points_x=7,
            points_y=5,
            size_x=2.0,
            size_y=1.0,
            center_x=0.5,
            center_y=-0.25,
            constant_zmin=0.0,
            constant_zmax=3.0e-4,
        )
    )

    assert grid.shape == (5, 7)
    assert np.isclose(grid.x.min(), -0.5)
    assert np.isclose(grid.x.max(), 1.5)
    assert np.isclose(grid.y.min(), -0.75)
    assert np.isclose(grid.y.max(), 0.25)
    assert np.count_nonzero(grid.zmin) == 0
    assert np.all(grid.zmax == 3.0e-4)


def test_constant_surface_rejects_zero_volume() -> None:
    with pytest.raises(ValueError, match="zero-volume"):
        build_surface_grid(
            SurfaceSource(mode="constant", constant_zmin=0.0, constant_zmax=0.0)
        )


@pytest.mark.parametrize(
    "source, message",
    [
        (_fractal_source(hurst_exponent=1.0), "hurst_exponent"),
        (
            _fractal_source(hurst_exponent=0.8, fractal_dimension=2.3),
            "D = 3 - H",
        ),
        (_fractal_source(rms_height=-1.0), "rms_height"),
        (_fractal_source(mean_aperture=0.0), "mean_aperture"),
    ],
)
def test_fractal_surface_rejects_invalid_parameters(
    source: SurfaceSource, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_surface_grid(source)


def test_generated_csv_contract_round_trips() -> None:
    grid = build_surface_grid(_fractal_source())
    output = ROOT / "_runtime" / "tests" / "surface-generation"
    output.mkdir(parents=True, exist_ok=True)
    files = write_surface_grid(grid, output)
    x, y, zmin, zmax = load_surface_csvs(files.x, files.y, files.zmin, files.zmax)

    assert np.array_equal(x, grid.x)
    assert np.array_equal(y, grid.y)
    assert np.array_equal(zmin, grid.zmin)
    assert np.array_equal(zmax, grid.zmax)


@pytest.mark.parametrize(
    "filename, expected_mode",
    [
        ("fractal-hurst.ini", "fractal"),
        ("fractal-dimension.ini", "fractal"),
        ("constant-planes.ini", "constant"),
    ],
)
def test_generated_surface_examples_are_conformal(filename: str, expected_mode: str) -> None:
    setup = load_setup(SURFACE_EXAMPLES / filename)

    assert setup.surface_source.normalized_mode == expected_mode
    assert validate_setup(setup) == (28, 32)
