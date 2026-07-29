"""Surface geometry, normals, areas, orientation, and connectivity."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter, label

from .model import PreparedSurface


def control_widths(axis: np.ndarray) -> np.ndarray:
    """Projected control-volume widths centered at structured-grid nodes."""

    widths = np.empty_like(axis, dtype=float)
    widths[1:-1] = 0.5 * (axis[2:] - axis[:-2])
    widths[0] = 0.5 * (axis[1] - axis[0])
    widths[-1] = 0.5 * (axis[-1] - axis[-2])
    return widths


def projected_area_weights(surface: PreparedSurface) -> np.ndarray:
    return np.outer(control_widths(surface.y_axis), control_widths(surface.x_axis))


def surface_gradients(
    height: np.ndarray,
    surface: PreparedSurface,
    smoothing_sigma: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return dz/dx and dz/dy on the physical, possibly nonuniform axes."""

    values = np.asarray(height, dtype=float)
    if smoothing_sigma > 0:
        values = gaussian_filter(values, sigma=smoothing_sigma, mode="nearest")
    dz_dy, dz_dx = np.gradient(values, surface.y_axis, surface.x_axis, edge_order=2)
    return dz_dx, dz_dy


def unit_normals(
    height: np.ndarray,
    surface: PreparedSurface,
    smoothing_sigma: float = 0.0,
) -> np.ndarray:
    """Estimate upward normals from centered finite differences of a height graph."""

    dz_dx, dz_dy = surface_gradients(height, surface, smoothing_sigma)
    normal = np.stack((-dz_dx, -dz_dy, np.ones_like(height)), axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    return normal


def actual_area_weights(
    height: np.ndarray,
    surface: PreparedSurface,
    smoothing_sigma: float = 0.0,
) -> np.ndarray:
    dz_dx, dz_dy = surface_gradients(height, surface, smoothing_sigma)
    return projected_area_weights(surface) * np.sqrt(1.0 + dz_dx**2 + dz_dy**2)


def fitted_plane(surface: PreparedSurface, height: np.ndarray) -> dict[str, object]:
    """Fit z = ax + by + c and return its global unit normal."""

    valid = surface.valid_mask & np.isfinite(height)
    design = np.column_stack(
        (surface.x[valid], surface.y[valid], np.ones(np.count_nonzero(valid)))
    )
    coefficients, *_ = np.linalg.lstsq(design, height[valid], rcond=None)
    a, b, c = (float(item) for item in coefficients)
    normal = np.array([-a, -b, 1.0])
    normal /= np.linalg.norm(normal)
    return {
        "slope_x": a,
        "slope_y": b,
        "intercept": c,
        "normal_x": float(normal[0]),
        "normal_y": float(normal[1]),
        "normal_z": float(normal[2]),
        "dip_degrees": float(np.degrees(np.arccos(np.clip(normal[2], -1.0, 1.0)))),
        "azimuth_degrees": float(np.degrees(np.arctan2(normal[1], normal[0])) % 360.0),
    }


def orientation_statistics(normals: np.ndarray, valid: np.ndarray) -> dict[str, float]:
    selected = normals[valid]
    mean = selected.mean(axis=0)
    resultant = float(np.linalg.norm(mean))
    if resultant > np.finfo(float).tiny:
        mean /= resultant
    angles = np.degrees(
        np.arccos(np.clip(selected @ mean, -1.0, 1.0))
    )
    return {
        "mean_normal_x": float(mean[0]),
        "mean_normal_y": float(mean[1]),
        "mean_normal_z": float(mean[2]),
        "mean_resultant_length": resultant,
        "angular_dispersion_degrees": float(np.std(angles)),
        "angular_p95_degrees": float(np.percentile(angles, 95)),
    }


def open_region_statistics(open_mask: np.ndarray, surface: PreparedSurface) -> dict[str, object]:
    """Report four-neighbor open-region connectivity on the projected grid."""

    structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=int)
    labels, count = label(open_mask, structure=structure)
    area_weights = projected_area_weights(surface)
    regions: list[dict[str, float | int]] = []
    for index in range(1, count + 1):
        mask = labels == index
        rows, cols = np.where(mask)
        regions.append(
            {
                "region": index,
                "samples": int(np.count_nonzero(mask)),
                "projected_area": float(np.sum(area_weights[mask])),
                "x_extent": float(surface.x_axis[cols.max()] - surface.x_axis[cols.min()]),
                "y_extent": float(surface.y_axis[rows.max()] - surface.y_axis[rows.min()]),
            }
        )
    regions.sort(key=lambda item: float(item["projected_area"]), reverse=True)
    return {
        "open_regions": count,
        "disconnected_open_regions": max(0, count - 1),
        "regions": regions,
    }


def surface_geometry_metrics(
    surface: PreparedSurface,
    normals: np.ndarray,
    aperture: np.ndarray,
) -> dict[str, object]:
    projected = projected_area_weights(surface)
    lower_area = actual_area_weights(surface.lower, surface)
    upper_area = actual_area_weights(surface.upper, surface)
    mid_area = actual_area_weights(surface.mid, surface)
    valid = surface.valid_mask & np.isfinite(aperture)
    projected_area = float(np.sum(projected[valid]))
    mid_actual_area = float(np.sum(mid_area[valid]))
    raw_positive = np.where(valid, np.maximum(aperture, 0.0), 0.0)
    return {
        "projected_crack_area": projected_area,
        "lower_wall_area": float(np.sum(lower_area[valid])),
        "upper_wall_area": float(np.sum(upper_area[valid])),
        "mid_surface_area": mid_actual_area,
        "surface_area_ratio": mid_actual_area / projected_area,
        "crack_volume_projected": float(np.sum(projected * raw_positive)),
        "mean_plane": fitted_plane(surface, surface.mid),
        "normal_orientation": orientation_statistics(normals, valid),
    }
