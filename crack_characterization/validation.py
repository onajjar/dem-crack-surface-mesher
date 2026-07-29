"""Coordinate, wall-ordering, and missing-data validation."""

from __future__ import annotations

import numpy as np
from scipy.interpolate import griddata

from surface_generation import SurfaceGrid

from .model import CharacterizationConfig, PreparedSurface


def _rectilinear_axes(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x_axis = np.asarray(x[0, :], dtype=float)
    y_axis = np.asarray(y[:, 0], dtype=float)
    x_scale = max(float(np.ptp(x_axis)), 1.0)
    y_scale = max(float(np.ptp(y_axis)), 1.0)
    if not np.allclose(x, x_axis[None, :], rtol=1.0e-10, atol=1.0e-12 * x_scale):
        raise ValueError(
            "Characterization currently requires a rectilinear x grid; "
            "the supplied rows contain inconsistent x coordinates."
        )
    if not np.allclose(y, y_axis[:, None], rtol=1.0e-10, atol=1.0e-12 * y_scale):
        raise ValueError(
            "Characterization currently requires a rectilinear y grid; "
            "the supplied columns contain inconsistent y coordinates."
        )
    return x_axis, y_axis


def _fill_missing(
    x: np.ndarray,
    y: np.ndarray,
    values: np.ndarray,
    label: str,
    warnings: list[str],
) -> np.ndarray:
    finite = np.isfinite(values)
    missing = int(values.size - np.count_nonzero(finite))
    if missing == 0:
        return values
    if np.count_nonzero(finite) < 3:
        raise ValueError(f"{label} has fewer than three finite samples.")
    points = np.column_stack((x[finite], y[finite]))
    targets = np.column_stack((x[~finite], y[~finite]))
    filled = np.array(values, copy=True)
    estimates = griddata(points, values[finite], targets, method="linear")
    unresolved = ~np.isfinite(estimates)
    if np.any(unresolved):
        estimates[unresolved] = griddata(
            points,
            values[finite],
            targets[unresolved],
            method="nearest",
        )
    filled[~finite] = estimates
    warnings.append(
        f"{label}: interpolated {missing} missing values using linear interpolation "
        "with nearest-neighbor boundary fallback."
    )
    return filled


def prepare_surface(
    grid: SurfaceGrid,
    config: CharacterizationConfig,
) -> PreparedSurface:
    """Validate and consistently order the application's reconstructed surface."""

    config.validated()
    arrays = {
        "x": np.asarray(grid.x, dtype=float),
        "y": np.asarray(grid.y, dtype=float),
        "lower": np.asarray(grid.zmin, dtype=float),
        "upper": np.asarray(grid.zmax, dtype=float),
    }
    shape = arrays["x"].shape
    if len(shape) != 2 or min(shape) < 3:
        raise ValueError("Characterization requires a structured grid of at least 3 x 3 points.")
    for label, values in arrays.items():
        if values.shape != shape:
            raise ValueError(
                f"All coordinate and wall arrays must match; x is {shape}, "
                f"but {label} is {values.shape}."
            )
    if not np.isfinite(arrays["x"]).all() or not np.isfinite(arrays["y"]).all():
        raise ValueError("Coordinate arrays contain NaN or infinite values.")

    x_axis, y_axis = _rectilinear_axes(arrays["x"], arrays["y"])
    dx = np.diff(x_axis)
    dy = np.diff(y_axis)
    if np.any(dx == 0) or np.any(dy == 0):
        raise ValueError("Duplicated x or y coordinates create zero-width grid cells.")
    if not (np.all(dx > 0) or np.all(dx < 0)):
        raise ValueError("The x sampling is non-monotonic and cannot be ordered safely.")
    if not (np.all(dy > 0) or np.all(dy < 0)):
        raise ValueError("The y sampling is non-monotonic and cannot be ordered safely.")
    if np.all(dx < 0):
        for key in arrays:
            arrays[key] = arrays[key][:, ::-1]
        x_axis = x_axis[::-1]
    if np.all(dy < 0):
        for key in arrays:
            arrays[key] = arrays[key][::-1, :]
        y_axis = y_axis[::-1]

    warnings: list[str] = []
    if config.interpolate_missing:
        arrays["lower"] = _fill_missing(
            arrays["x"], arrays["y"], arrays["lower"], "lower wall", warnings
        )
        arrays["upper"] = _fill_missing(
            arrays["x"], arrays["y"], arrays["upper"], "upper wall", warnings
        )

    finite_walls = np.isfinite(arrays["lower"]) & np.isfinite(arrays["upper"])
    missing_count = int(finite_walls.size - np.count_nonzero(finite_walls))
    if missing_count:
        warnings.append(
            f"{missing_count} wall pairs are non-finite and remain excluded from all metrics."
        )
    raw_aperture = arrays["upper"] - arrays["lower"]
    negative = finite_walls & (raw_aperture < 0)
    if np.any(negative) and not config.allow_negative_aperture:
        finite_walls &= ~negative
        warnings.append(
            f"{np.count_nonzero(negative)} negative-aperture samples were reported and excluded."
        )
    elif np.any(negative):
        warnings.append(
            f"{np.count_nonzero(negative)} negative-aperture samples were retained by request; "
            "hydraulic metrics still exclude them."
        )
    mid = 0.5 * (arrays["lower"] + arrays["upper"])
    return PreparedSurface(
        x=arrays["x"],
        y=arrays["y"],
        lower=arrays["lower"],
        upper=arrays["upper"],
        mid=mid,
        raw_aperture=raw_aperture,
        valid_mask=finite_walls,
        x_axis=x_axis,
        y_axis=y_axis,
        warnings=warnings,
        source_mode=grid.mode,
        source_metadata=grid.metadata,
    )
