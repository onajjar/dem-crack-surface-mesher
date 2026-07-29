"""Descriptive, robust, and spatial aperture statistics."""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .geometry import actual_area_weights, projected_area_weights
from .model import PreparedSurface

PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    finite = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    return float(np.sum(values[finite] * weights[finite]) / np.sum(weights[finite]))


def _sample_summary(values: np.ndarray) -> dict[str, float | None]:
    finite = np.asarray(values[np.isfinite(values)], dtype=float)
    if finite.size == 0:
        raise ValueError("No valid aperture samples remain after preprocessing.")
    mean = float(np.mean(finite))
    std = float(np.std(finite))
    has_spread = std > np.finfo(float).eps * max(abs(mean), 1.0)
    positive = finite[finite > 0]
    median = float(np.median(finite))
    mad = float(np.median(np.abs(finite - median)))
    result: dict[str, float | None] = {
        "arithmetic_mean": mean,
        "median": median,
        "minimum": float(np.min(finite)),
        "maximum": float(np.max(finite)),
        "range": float(np.ptp(finite)),
        "variance": float(np.var(finite)),
        "standard_deviation": std,
        "coefficient_of_variation": std / mean if mean != 0 else None,
        "root_mean_square": float(np.sqrt(np.mean(finite**2))),
        "geometric_mean": (
            float(stats.gmean(positive)) if positive.size == finite.size else None
        ),
        "harmonic_mean": (
            float(stats.hmean(positive)) if positive.size == finite.size else None
        ),
        "skewness": (
            float(stats.skew(finite, bias=False))
            if finite.size >= 3 and has_spread
            else 0.0
        ),
        "excess_kurtosis": (
            float(stats.kurtosis(finite, fisher=True, bias=False))
            if finite.size >= 4 and has_spread
            else 0.0
        ),
        "interquartile_range": float(stats.iqr(finite)),
        "median_absolute_deviation": mad,
        "robust_standard_deviation": 1.4826 * mad,
        "global_cubic_mean": (
            float(np.cbrt(np.mean(finite**3))) if np.all(finite >= 0) else None
        ),
    }
    result.update(
        {
            f"percentile_{percent}": float(np.percentile(finite, percent))
            for percent in PERCENTILES
        }
    )
    return result


def _line_statistics(aperture: np.ndarray) -> dict[str, float]:
    row_means = np.nanmean(aperture, axis=1)
    column_means = np.nanmean(aperture, axis=0)
    row_stds = np.nanstd(aperture, axis=1)
    column_stds = np.nanstd(aperture, axis=0)
    return {
        "spatial_std_along_x_mean": float(np.nanmean(row_stds)),
        "spatial_std_along_y_mean": float(np.nanmean(column_stds)),
        "std_of_x_line_averages": float(np.nanstd(row_means)),
        "std_of_y_line_averages": float(np.nanstd(column_means)),
        "mean_std_within_x_profiles": float(np.nanmean(row_stds)),
        "mean_std_within_y_profiles": float(np.nanmean(column_stds)),
        "std_across_x_profiles": float(np.nanstd(row_means)),
        "std_across_y_profiles": float(np.nanstd(column_means)),
    }


def aperture_statistics(
    surface: PreparedSurface,
    aperture: np.ndarray,
    *,
    cutoff: float,
) -> dict[str, object]:
    """Calculate requested opening statistics without hiding invalid samples."""

    finite = np.isfinite(aperture)
    valid_values = aperture[finite]
    raw = surface.raw_aperture
    raw_finite = np.isfinite(raw)
    zero = raw_finite & (raw == 0)
    negative = raw_finite & (raw < 0)
    closed = (~finite) | (aperture <= cutoff)
    projected = projected_area_weights(surface)
    actual = actual_area_weights(surface.mid, surface)
    sample = _sample_summary(valid_values)
    sample.update(_line_statistics(aperture))
    sample["projected_area_weighted_mean"] = _weighted_mean(aperture, projected)
    sample["surface_area_weighted_mean"] = _weighted_mean(aperture, actual)
    positive = finite & (aperture >= 0)
    sample["projected_area_weighted_cubic_mean"] = float(
        np.cbrt(
            np.sum(projected[positive] * aperture[positive] ** 3)
            / np.sum(projected[positive])
        )
    )
    total_area = float(np.sum(projected))
    closed_area = float(np.sum(projected[closed]))
    counts = {
        "total_samples": int(aperture.size),
        "valid_samples": int(np.count_nonzero(finite)),
        "zero_aperture_samples": int(np.count_nonzero(zero)),
        "negative_aperture_samples": int(np.count_nonzero(negative)),
        "closed_or_invalid_samples": int(np.count_nonzero(closed)),
        "closed_or_invalid_sample_fraction": float(np.mean(closed)),
        "closed_or_invalid_projected_area_fraction": closed_area / total_area,
        "aperture_cutoff": cutoff,
    }
    if not math.isfinite(float(sample["arithmetic_mean"])):
        raise ValueError("Aperture statistics produced a non-finite mean.")
    return {"statistics": sample, "counts": counts}


def statistics_table(
    metrics: dict[str, object],
    *,
    length_unit: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    dimensionless = {
        "coefficient_of_variation",
        "skewness",
        "excess_kurtosis",
        "closed_or_invalid_sample_fraction",
        "closed_or_invalid_projected_area_fraction",
    }
    squared = {"variance"}
    counts = {key for key in metrics if key.endswith("_samples")}
    for key, value in metrics.items():
        unit = (
            "1"
            if key in dimensionless
            else f"{length_unit}^2"
            if key in squared
            else "count"
            if key in counts
            else length_unit
        )
        rows.append({"metric": key, "value": value, "unit": unit})
    return rows
