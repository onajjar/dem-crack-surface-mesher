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


def _legacy_isotropic_field(source: SurfaceSource) -> np.ndarray:
    rng = np.random.default_rng(source.random_seed)
    noise = rng.standard_normal((source.points_y, source.points_x))
    spectrum = np.fft.rfft2(noise)
    dx = source.size_x / (source.points_x - 1)
    dy = source.size_y / (source.points_y - 1)
    kx = 2.0 * np.pi * np.fft.rfftfreq(source.points_x, d=dx)
    ky = 2.0 * np.pi * np.fft.fftfreq(source.points_y, d=dy)
    radius = np.hypot(ky[:, None], kx[None, :])
    spectral_filter = np.zeros_like(radius)
    nonzero = radius > 0.0
    spectral_filter[nonzero] = radius[nonzero] ** (
        -(source.resolved_hurst_exponent + 1.0)
    )
    spectrum *= spectral_filter
    spectrum[0, 0] = 0.0
    field = np.fft.irfft2(spectrum, s=noise.shape).real
    field -= float(field.mean())
    return field * (source.rms_height / np.sqrt(np.mean(field * field)))


def test_fractal_surface_is_reproducible_and_normalized() -> None:
    source = _fractal_source()
    first = build_surface_grid(source)
    second = build_surface_grid(source)
    mean_surface = 0.5 * (first.zmin + first.zmax)
    legacy_field = _legacy_isotropic_field(source)

    assert first.shape == (24, 32)
    assert np.array_equal(first.x, second.x)
    assert np.array_equal(first.zmin, second.zmin)
    assert np.array_equal(first.zmin, legacy_field - source.mean_aperture / 2.0)
    assert np.array_equal(first.zmax, legacy_field + source.mean_aperture / 2.0)
    assert np.isclose(mean_surface.mean(), 0.0, atol=1.0e-18)
    assert np.isclose(np.sqrt(np.mean(mean_surface**2)), 4.0e-5, rtol=1.0e-12)
    assert np.allclose(first.opening, 2.0e-4, rtol=0.0, atol=1.0e-18)


def test_advanced_fractal_supports_all_extended_wall_statistics() -> None:
    source = _fractal_source(
        points_x=128,
        points_y=96,
        hurst_exponent=None,
        hurst_exponent_x=0.85,
        hurst_exponent_y=0.55,
        lower_wall_rms=1.0e-5,
        upper_wall_rms=1.2e-5,
        minimum_aperture=1.0e-6,
        wall_correlation=0.0,
        rolloff_wavelength_x=0.4,
        rolloff_wavelength_y=0.12,
        height_distribution="lognormal",
        lognormal_shape=0.5,
        random_seed=42,
    )

    first = build_surface_grid(source)
    second = build_surface_grid(source)
    achieved = first.metadata["achieved"]
    target = first.metadata["targets"]
    dx = source.size_x / (source.points_x - 1)
    dy = source.size_y / (source.points_y - 1)
    gradient_x = np.std(np.diff(first.zmin, axis=1)) / dx
    gradient_y = np.std(np.diff(first.zmin, axis=0)) / dy

    assert np.array_equal(first.zmin, second.zmin)
    assert np.array_equal(first.zmax, second.zmax)
    assert target["hurst_exponent_x"] == 0.85
    assert target["hurst_exponent_y"] == 0.55
    assert target["height_distribution"] == "lognormal"
    assert np.isclose(achieved["lower_wall_rms"], 1.0e-5, rtol=1.0e-12)
    assert np.isclose(achieved["upper_wall_rms"], 1.2e-5, rtol=1.0e-12)
    assert achieved["lower_wall_skewness"] > 1.0
    assert achieved["upper_wall_skewness"] > 1.0
    assert abs(achieved["wall_correlation"]) < 0.1
    assert achieved["aperture_standard_deviation"] > 1.0e-5
    assert achieved["minimum_aperture"] >= source.minimum_aperture
    assert gradient_x / gradient_y < 0.5


def test_rolloff_reduces_long_wavelength_spectral_dominance() -> None:
    source = _fractal_source(
        points_x=128,
        points_y=128,
        size_x=1.0,
        size_y=1.0,
        hurst_exponent=0.7,
        rms_height=1.0,
        mean_aperture=3.0,
        random_seed=42,
    )
    without_rolloff = build_surface_grid(source)
    with_rolloff = build_surface_grid(
        replace(
            source,
            rolloff_wavelength_x=0.1,
            rolloff_wavelength_y=0.1,
        )
    )

    def low_frequency_fraction(grid) -> float:
        surface = 0.5 * (grid.zmin + grid.zmax)
        power = np.abs(np.fft.rfft2(surface)) ** 2
        kx = np.fft.rfftfreq(surface.shape[1])
        ky = np.fft.fftfreq(surface.shape[0])
        radius = np.hypot(ky[:, None], kx[None, :])
        return float(power[(radius > 0.0) & (radius < 0.04)].sum() / power.sum())

    assert low_frequency_fraction(with_rolloff) < (
        0.5 * low_frequency_fraction(without_rolloff)
    )


@pytest.mark.parametrize(
    "distribution",
    ["gaussian", "uniform", "laplace", "lognormal"],
)
def test_supported_height_distributions_are_reproducible(
    distribution: str,
) -> None:
    source = _fractal_source(
        points_x=64,
        points_y=64,
        rms_height=2.0e-5,
        height_distribution=distribution,
        wall_correlation=1.0,
        lognormal_shape=0.6,
    )

    first = build_surface_grid(source)
    second = build_surface_grid(source)
    roughness = first.zmin - float(first.zmin.mean())

    assert np.array_equal(first.zmin, second.zmin)
    assert np.isfinite(first.zmin).all()
    assert np.isclose(np.sqrt(np.mean(roughness**2)), 2.0e-5, rtol=1.0e-12)
    assert first.metadata["targets"]["height_distribution"] == distribution


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
        (_fractal_source(hurst_exponent_x=1.0), "hurst_exponent_x"),
        (_fractal_source(wall_correlation=1.1), "wall_correlation"),
        (
            _fractal_source(rolloff_wavelength_x=0.2),
            "must be supplied together",
        ),
        (
            _fractal_source(height_distribution="gamma"),
            "height_distribution",
        ),
        (
            _fractal_source(
                height_distribution="lognormal",
                lognormal_shape=0.0,
            ),
            "lognormal_shape",
        ),
        (
            _fractal_source(minimum_aperture=2.0e-4),
            "minimum_aperture",
        ),
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


def test_advanced_example_parses_every_extended_fractal_control() -> None:
    setup = load_setup(SURFACE_EXAMPLES / "fractal-advanced.ini")
    source = setup.surface_source

    assert source.resolved_hurst_exponents == (0.85, 0.55)
    assert source.rolloff_wavelength_x == 0.4
    assert source.rolloff_wavelength_y == 0.12
    assert source.height_distribution == "lognormal"
    assert source.lognormal_shape == 0.5
    assert source.lower_wall_rms == 1.0e-5
    assert source.upper_wall_rms == 1.2e-5
    assert source.wall_correlation == 0.0
    assert source.minimum_aperture == 1.0e-6
    assert setup.mesh_mode == "python_only"
    assert setup.mesh_template is None


@pytest.mark.parametrize(
    "filename, expected_mode, expected_edges",
    [
        ("fractal-hurst.ini", "fractal", (28, 32)),
        ("fractal-dimension.ini", "fractal", (28, 32)),
        ("fractal-advanced.ini", "fractal", (44, 52)),
        ("constant-planes.ini", "constant", (28, 32)),
    ],
)
def test_generated_surface_examples_are_conformal(
    filename: str,
    expected_mode: str,
    expected_edges: tuple[int, int],
) -> None:
    setup = load_setup(SURFACE_EXAMPLES / filename)

    assert setup.surface_source.normalized_mode == expected_mode
    assert validate_setup(setup) == expected_edges
