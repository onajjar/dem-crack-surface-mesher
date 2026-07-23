from __future__ import annotations

import shutil
import warnings
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from crack_characterization import (
    CharacterizationConfig,
    SyntheticConfig,
    characterize_surface,
    generate_synthetic_surface,
)
from crack_characterization.visualization import _bounded_histogram_bins
from surface_generation import SurfaceGrid

ROOT = Path(__file__).resolve().parents[1]


def _grid(
    aperture: float | np.ndarray = 2.0e-4,
    *,
    points_x: int = 25,
    points_y: int = 21,
    x_axis: np.ndarray | None = None,
    y_axis: np.ndarray | None = None,
    mid: np.ndarray | None = None,
) -> SurfaceGrid:
    x_values = (
        np.linspace(0.0, 1.2, points_x) if x_axis is None else np.asarray(x_axis)
    )
    y_values = (
        np.linspace(0.0, 0.8, points_y) if y_axis is None else np.asarray(y_axis)
    )
    x, y = np.meshgrid(x_values, y_values)
    center = np.zeros_like(x) if mid is None else np.asarray(mid)
    opening = np.broadcast_to(aperture, x.shape)
    return SurfaceGrid(
        x=x,
        y=y,
        zmin=center - opening / 2.0,
        zmax=center + opening / 2.0,
        mode="test",
    )


def _config(**changes) -> CharacterizationConfig:
    return replace(
        CharacterizationConfig(
            aperture_method="global_z",
            flow_direction="X",
            hurst_bootstrap_samples=0,
            generate_figures=False,
        ),
        **changes,
    )


def test_parallel_planar_crack_has_exact_analytical_metrics() -> None:
    result = characterize_surface(_grid(), _config())
    aperture = result.summary["aperture"]["statistics"]
    hydraulic = result.summary["hydraulic"]
    tortuosity = result.summary["tortuosity"]["mid"]

    assert np.isclose(aperture["arithmetic_mean"], 2.0e-4)
    assert np.isclose(aperture["standard_deviation"], 0.0, atol=1.0e-18)
    assert np.isclose(aperture["global_cubic_mean"], 2.0e-4)
    assert np.isclose(hydraulic["global_equivalent_hydraulic_aperture"], 2.0e-4)
    assert np.isclose(tortuosity["mean"], 1.0)
    flat_fits = result.tables["hurst_analysis"]
    assert all(row["hurst_exponent"] is None for row in flat_fits)
    assert {"X", "Y"} == {row["direction"] for row in flat_fits}
    assert {"structure_function", "power_spectral_density"} == {
        row["method"] for row in flat_fits
    }
    assert {"global_z", "local_normal"} == {
        row["aperture_definition"]
        for row in result.tables["aperture_statistics"]
    }
    assert {"X", "Y"} == set(
        result.summary["hydraulic_by_aperture_and_direction"]["local_normal"]
    )
    assert any("flat" in warning.lower() for warning in result.warnings)


def test_inclined_plane_local_normal_aperture_and_tortuosity() -> None:
    base = _grid()
    slope_x, slope_y = 0.2, -0.1
    mid = slope_x * base.x + slope_y * base.y
    grid = _grid(mid=mid)
    result = characterize_surface(
        grid,
        _config(aperture_method="local_normal", flow_direction="X"),
    )
    expected_aperture = 2.0e-4 / np.sqrt(1.0 + slope_x**2 + slope_y**2)

    assert np.isclose(
        result.summary["aperture"]["statistics"]["arithmetic_mean"],
        expected_aperture,
        rtol=1.0e-12,
    )
    assert np.isclose(
        result.summary["apertures"]["global_z"]["statistics"]["arithmetic_mean"],
        2.0e-4,
        rtol=1.0e-12,
    )
    normal = np.array([-slope_x, -slope_y, 1.0])
    normal /= np.linalg.norm(normal)
    projected_x = np.array([1.0, 0.0, 0.0]) - normal[0] * normal
    parameter_direction = projected_x[:2] / np.linalg.norm(projected_x[:2])
    directional_slope = slope_x * parameter_direction[0] + slope_y * parameter_direction[1]
    assert np.isclose(
        result.summary["tortuosity"]["directions"]["X"]["mid"]["mean"],
        np.sqrt(1.0 + directional_slope**2),
        rtol=1.0e-12,
    )


def test_sinusoidal_mid_surface_preserves_constant_global_aperture() -> None:
    base = _grid(points_x=33, points_y=25)
    mid = 1.0e-3 * np.sin(2.0 * np.pi * base.x / np.ptp(base.x))
    result = characterize_surface(_grid(points_x=33, points_y=25, mid=mid), _config())

    assert np.isclose(
        result.summary["apertures"]["global_z"]["statistics"][
            "standard_deviation"
        ],
        0.0,
        atol=1.0e-18,
    )
    assert result.summary["tortuosity"]["directions"]["X"]["mid"]["mean"] > 1.0


def test_varying_aperture_series_resistance_matches_independent_integration() -> None:
    base = _grid(points_x=31, points_y=9)
    aperture = 1.0e-4 + 2.0e-4 * base.x / np.ptp(base.x)
    result = characterize_surface(_grid(aperture, points_x=31, points_y=9), _config())
    x = base.x[0]
    b = aperture[0]
    resistance = np.sum(np.diff(x) * 0.5 * (b[:-1] ** -3 + b[1:] ** -3))
    expected = (resistance / np.ptp(x)) ** (-1.0 / 3.0)

    assert np.isclose(
        result.summary["hydraulic"]["global_equivalent_hydraulic_aperture"],
        expected,
        rtol=1.0e-12,
    )


def test_strong_bottleneck_reduces_equivalent_aperture() -> None:
    base = _grid(points_x=41, points_y=11)
    aperture = np.full(base.shape, 3.0e-4)
    aperture[:, 20] = 2.0e-5
    result = characterize_surface(_grid(aperture, points_x=41, points_y=11), _config())

    assert (
        result.summary["hydraulic"]["global_equivalent_hydraulic_aperture"]
        < result.summary["aperture"]["statistics"]["arithmetic_mean"]
    )
    nearly_discrete = np.concatenate(
        (np.full(100_000, 3.0e-4), np.array([2.0e-5, 2.0000001e-5]))
    )
    assert _bounded_histogram_bins(nearly_discrete) == 80


def test_zero_aperture_barrier_marks_every_flow_path_closed() -> None:
    base = _grid(points_x=21, points_y=13)
    aperture = np.full(base.shape, 2.0e-4)
    aperture[:, 10] = 0.0
    result = characterize_surface(
        _grid(aperture, points_x=21, points_y=13),
        _config(aperture_cutoff=1.0e-12),
    )

    assert result.summary["hydraulic"]["closed_or_disconnected_paths"] == 13
    assert result.summary["hydraulic"]["global_equivalent_hydraulic_aperture"] == 0.0


def test_nonuniform_sampling_uses_physical_segment_lengths() -> None:
    x_axis = np.array([0.0, 0.01, 0.05, 0.2, 0.55, 1.0])
    y_axis = np.array([0.0, 0.03, 0.2, 0.6])
    base = _grid(x_axis=x_axis, y_axis=y_axis, points_x=6, points_y=4)
    aperture = 1.0e-4 + base.x * 1.0e-4
    result = characterize_surface(
        _grid(
            aperture,
            x_axis=x_axis,
            y_axis=y_axis,
            points_x=6,
            points_y=4,
        ),
        _config(),
    )

    assert result.summary["geometry"]["projected_crack_area"] > 0
    assert result.summary["hydraulic"]["global_equivalent_hydraulic_aperture"] > 0


def test_flow_along_x_y_and_custom_oblique_are_distinct_supported_cases() -> None:
    base = _grid(points_x=23, points_y=19)
    aperture = 1.0e-4 + 1.0e-4 * base.x + 2.0e-4 * base.y
    grid = _grid(aperture, points_x=23, points_y=19)
    along_x = characterize_surface(grid, _config(flow_direction="X"))
    along_y = characterize_surface(grid, _config(flow_direction="Y"))
    oblique = characterize_surface(
        grid,
        _config(
            flow_direction="custom",
            custom_flow_vector=(1.0, 1.0, 0.0),
            tortuosity_direction="custom",
            custom_tortuosity_vector=(1.0, -1.0, 0.0),
        ),
    )

    values = {
        round(
            item.summary["hydraulic"]["global_equivalent_hydraulic_aperture"],
            12,
        )
        for item in (along_x, along_y, oblique)
    }
    assert len(values) == 3
    assert {
        "X",
        "Y",
        "CUSTOM",
    } == set(
        oblique.summary["hydraulic_by_aperture_and_direction"]["local_normal"]
    )
    assert {"X", "Y"} == {
        row["direction"] for row in oblique.tables["directional_tortuosity"]
    }


def test_global_z_flow_is_rejected_for_flat_height_graph() -> None:
    try:
        characterize_surface(_grid(), _config(flow_direction="Z"))
    except ValueError as exc:
        assert "no resolvable projection" in str(exc)
    else:
        raise AssertionError("Global Z must be rejected when it is normal to a flat crack plane.")


def test_anisotropic_synthetic_surface_is_reproducible_and_positive() -> None:
    settings = SyntheticConfig(
        points_x=32,
        points_y=24,
        size_x=1.0,
        size_y=0.7,
        mean_aperture=2.0e-4,
        aperture_std=4.0e-5,
        mid_surface_rms=2.0e-5,
        hurst_x=0.8,
        hurst_y=0.6,
        correlation_length_x=0.2,
        correlation_length_y=0.08,
        minimum_aperture=1.0e-6,
        random_seed=77,
    )
    first = generate_synthetic_surface(settings)
    second = generate_synthetic_surface(settings)

    assert np.array_equal(first.zmin, second.zmin)
    assert np.array_equal(first.zmax, second.zmax)
    assert np.all(first.opening >= settings.minimum_aperture)
    assert np.isclose(np.std(0.5 * (first.zmin + first.zmax)), 2.0e-5)


def test_required_exports_and_synthetic_validation_use_mesh_csv_contract() -> None:
    output_directory = ROOT / "_runtime" / "tests" / "characterization-export"
    shutil.rmtree(output_directory, ignore_errors=True)
    settings = SyntheticConfig(
        points_x=16,
        points_y=14,
        size_x=1.0,
        size_y=0.7,
        mean_aperture=2.0e-4,
        aperture_std=2.0e-5,
        mid_surface_rms=1.0e-5,
        random_seed=88,
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            result = characterize_surface(
                _grid(points_x=17, points_y=15),
                _config(publication_formats=("png",)),
                output_directory=output_directory,
                synthetic_config=settings,
            )
        required = {
            "characterization_summary.json",
            "characterization_summary.csv",
            "aperture_statistics.csv",
            "directional_tortuosity.csv",
            "flow_path_equivalent_aperture.csv",
            "hurst_analysis.csv",
            "roughness_statistics.csv",
            "surface_orientation_statistics.csv",
            "synthetic_surface_validation.csv",
            "characterization_report.md",
        }

        assert required.issubset(
            {path.name for path in output_directory.iterdir()}
        )
        assert result.tables["synthetic_surface_validation"]
        synthetic_csv = output_directory / "synthetic" / "surface_csv"
        assert {
            "xrange_generated.csv",
            "yrange_generated.csv",
            "zfit_zmin_generated.csv",
            "zfit_zmax_generated.csv",
        } == {path.name for path in synthetic_csv.iterdir()}
    finally:
        shutil.rmtree(output_directory, ignore_errors=True)


def test_multiple_synthetic_realizations_are_exported_with_distinct_seeds() -> None:
    output_directory = ROOT / "_runtime" / "tests" / "characterization-ensemble"
    shutil.rmtree(output_directory, ignore_errors=True)
    settings = SyntheticConfig(
        points_x=8,
        points_y=8,
        size_x=1.0,
        size_y=0.8,
        mean_aperture=2.0e-4,
        aperture_std=2.0e-5,
        mid_surface_rms=1.0e-5,
        random_seed=901,
        realizations=2,
    )
    try:
        result = characterize_surface(
            _grid(points_x=9, points_y=9),
            _config(),
            output_directory=output_directory,
            synthetic_config=settings,
        )
        records = result.summary["synthetic_surface"]["realizations"]
        assert [record["random_seed"] for record in records] == [901, 902]
        for index in (1, 2):
            assert (
                output_directory
                / "synthetic"
                / f"realization_{index:03d}"
                / "surface_csv"
                / "zfit_zmax_generated.csv"
            ).is_file()
    finally:
        shutil.rmtree(output_directory, ignore_errors=True)


def test_characterization_honors_cancellation_before_work() -> None:
    with pytest.raises(InterruptedError, match="cancelled"):
        characterize_surface(_grid(), _config(), cancelled=lambda: True)
