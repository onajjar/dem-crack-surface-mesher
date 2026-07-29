"""Flow-path cubic-law proxies and geometrical profile tortuosity."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from .geometry import control_widths, fitted_plane
from .model import CharacterizationConfig, PreparedSurface
from .statistics import PERCENTILES


@dataclass(frozen=True)
class ProfileSet:
    """Parallel profiles sampled in the surface's XY parameter plane."""

    direction_xy: np.ndarray
    transverse_xy: np.ndarray
    offsets: np.ndarray
    widths: np.ndarray
    coordinates: tuple[np.ndarray, ...]
    projected_distance: tuple[np.ndarray, ...]


def _global_vector(
    direction: str,
    custom: tuple[float, float, float],
    surface: PreparedSurface,
) -> np.ndarray:
    key = direction.strip().upper()
    if key == "AUTO":
        x_extent = float(np.ptp(surface.x_axis))
        y_extent = float(np.ptp(surface.y_axis))
        key = "X" if x_extent >= y_extent else "Y"
    if key == "CUSTOM":
        return np.asarray(custom, dtype=float)
    return {
        "X": np.array([1.0, 0.0, 0.0]),
        "Y": np.array([0.0, 1.0, 0.0]),
        "Z": np.array([0.0, 0.0, 1.0]),
    }[key]


def resolve_in_plane_direction(
    surface: PreparedSurface,
    direction: str,
    custom: tuple[float, float, float],
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    """Project a global direction into the least-squares crack plane."""

    plane = fitted_plane(surface, surface.mid)
    normal = np.array(
        [plane["normal_x"], plane["normal_y"], plane["normal_z"]],
        dtype=float,
    )
    requested = _global_vector(direction, custom, surface)
    requested /= np.linalg.norm(requested)
    tangent = requested - float(requested @ normal) * normal
    xy = tangent[:2]
    if np.linalg.norm(xy) <= 1.0e-12:
        raise ValueError(
            f"Flow direction {direction} has no resolvable projection in the structured "
            "surface plane. Choose X, Y, auto, or a non-normal custom vector."
        )
    xy /= np.linalg.norm(xy)
    transverse = np.array([-xy[1], xy[0]])
    return xy, transverse, {
        "requested_global_vector": requested.tolist(),
        "projected_plane_vector": (tangent / np.linalg.norm(tangent)).tolist(),
        "parameter_plane_direction": xy.tolist(),
        "parameter_plane_transverse": transverse.tolist(),
    }


def _line_box_interval(
    offset: float,
    direction: np.ndarray,
    transverse: np.ndarray,
    x_bounds: tuple[float, float],
    y_bounds: tuple[float, float],
) -> tuple[float, float] | None:
    lower, upper = -np.inf, np.inf
    base = transverse * offset
    for coordinate, bounds in enumerate((x_bounds, y_bounds)):
        component = direction[coordinate]
        if abs(component) <= 1.0e-14:
            if not bounds[0] <= base[coordinate] <= bounds[1]:
                return None
            continue
        first = (bounds[0] - base[coordinate]) / component
        second = (bounds[1] - base[coordinate]) / component
        lower = max(lower, min(first, second))
        upper = min(upper, max(first, second))
    return (float(lower), float(upper)) if upper > lower else None


def build_profile_set(
    surface: PreparedSurface,
    direction_xy: np.ndarray,
    transverse_xy: np.ndarray | None = None,
) -> ProfileSet:
    """Build axis-exact or oblique flow-parallel sampling paths."""

    direction = np.asarray(direction_xy, dtype=float)
    direction /= np.linalg.norm(direction)
    transverse = (
        np.array([-direction[1], direction[0]])
        if transverse_xy is None
        else np.asarray(transverse_xy, dtype=float)
    )
    transverse /= np.linalg.norm(transverse)

    if np.allclose(np.abs(direction), (1.0, 0.0), atol=1.0e-12):
        coords = tuple(
            np.column_stack((surface.x_axis, np.full_like(surface.x_axis, y)))
            for y in surface.y_axis
        )
        distances = tuple(surface.x_axis - surface.x_axis[0] for _ in surface.y_axis)
        return ProfileSet(
            direction,
            transverse,
            surface.y_axis.copy(),
            control_widths(surface.y_axis),
            coords,
            distances,
        )
    if np.allclose(np.abs(direction), (0.0, 1.0), atol=1.0e-12):
        coords = tuple(
            np.column_stack((np.full_like(surface.y_axis, x), surface.y_axis))
            for x in surface.x_axis
        )
        distances = tuple(surface.y_axis - surface.y_axis[0] for _ in surface.x_axis)
        return ProfileSet(
            direction,
            transverse,
            surface.x_axis.copy(),
            control_widths(surface.x_axis),
            coords,
            distances,
        )

    corners = np.array(
        [
            [surface.x_axis[0], surface.y_axis[0]],
            [surface.x_axis[-1], surface.y_axis[0]],
            [surface.x_axis[-1], surface.y_axis[-1]],
            [surface.x_axis[0], surface.y_axis[-1]],
        ]
    )
    projected_offsets = corners @ transverse
    profile_count = max(3, int(round(np.hypot(*surface.shape))))
    offsets = np.linspace(projected_offsets.min(), projected_offsets.max(), profile_count)
    widths = control_widths(offsets)
    sample_count = max(surface.shape) * 2
    coordinates: list[np.ndarray] = []
    distances: list[np.ndarray] = []
    kept_offsets: list[float] = []
    kept_widths: list[float] = []
    for offset, width in zip(offsets, widths, strict=True):
        interval = _line_box_interval(
            float(offset),
            direction,
            transverse,
            (float(surface.x_axis[0]), float(surface.x_axis[-1])),
            (float(surface.y_axis[0]), float(surface.y_axis[-1])),
        )
        if interval is None:
            continue
        s = np.linspace(interval[0], interval[1], sample_count)
        coordinates.append(transverse[None, :] * offset + s[:, None] * direction[None, :])
        distances.append(s - s[0])
        kept_offsets.append(float(offset))
        kept_widths.append(float(width))
    return ProfileSet(
        direction,
        transverse,
        np.asarray(kept_offsets),
        np.asarray(kept_widths),
        tuple(coordinates),
        tuple(distances),
    )


def sample_profiles(
    surface: PreparedSurface,
    values: np.ndarray,
    profiles: ProfileSet,
) -> tuple[np.ndarray, ...]:
    interpolator = RegularGridInterpolator(
        (surface.y_axis, surface.x_axis),
        values,
        bounds_error=False,
        fill_value=np.nan,
    )
    return tuple(
        interpolator(np.column_stack((coordinates[:, 1], coordinates[:, 0])))
        for coordinates in profiles.coordinates
    )


def _series_equivalent(
    distance: np.ndarray,
    aperture: np.ndarray,
    cutoff: float,
) -> tuple[float, float, bool, int]:
    finite = np.isfinite(distance) & np.isfinite(aperture)
    distance = distance[finite]
    aperture = aperture[finite]
    if distance.size < 2:
        return 0.0, float("inf"), True, int(distance.size)
    if np.any(aperture <= cutoff):
        return 0.0, float("inf"), True, int(distance.size)
    ds = np.diff(distance)
    resistance_density = 0.5 * (
        aperture[:-1] ** -3 + aperture[1:] ** -3
    )
    length = float(np.sum(ds))
    normalized_resistance = float(np.sum(ds * resistance_density) / length)
    return normalized_resistance ** (-1.0 / 3.0), normalized_resistance, False, int(
        distance.size
    )


def equivalent_hydraulic_aperture(
    surface: PreparedSurface,
    aperture: np.ndarray,
    config: CharacterizationConfig,
) -> tuple[dict[str, object], list[dict[str, object]], ProfileSet]:
    """Apply series resistance along paths and parallel conductance across paths."""

    direction, transverse, direction_info = resolve_in_plane_direction(
        surface,
        config.flow_direction,
        config.custom_flow_vector,
    )
    profiles = build_profile_set(surface, direction, transverse)
    sampled = sample_profiles(surface, aperture, profiles)
    rows: list[dict[str, object]] = []
    equivalent: list[float] = []
    for index, (distance, values, offset, width) in enumerate(
        zip(
            profiles.projected_distance,
            sampled,
            profiles.offsets,
            profiles.widths,
            strict=True,
        ),
        start=1,
    ):
        eq, resistance, closed, samples = _series_equivalent(
            distance,
            values,
            config.aperture_cutoff,
        )
        equivalent.append(eq)
        rows.append(
            {
                "path": index,
                "transverse_offset": float(offset),
                "path_width": float(width),
                "projected_length": float(distance[-1] - distance[0]),
                "equivalent_aperture": eq,
                "normalized_cubic_resistance": resistance,
                "closed_or_disconnected": closed,
                "samples": samples,
            }
        )
    eq_values = np.asarray(equivalent)
    widths = profiles.widths
    positive_width = widths > 0
    global_eq = float(
        np.cbrt(
            np.sum(widths[positive_width] * eq_values[positive_width] ** 3)
            / np.sum(widths[positive_width])
        )
    )
    positive = eq_values[eq_values > 0]
    resistance_values = np.array(
        [float(row["normalized_cubic_resistance"]) for row in rows]
    )
    largest = int(np.argmax(resistance_values)) + 1
    smallest = int(np.argmin(resistance_values)) + 1
    summary = {
        **direction_info,
        "path_count": len(rows),
        "closed_or_disconnected_paths": int(np.count_nonzero(eq_values == 0)),
        "global_equivalent_hydraulic_aperture": global_eq,
        "path_equivalent_mean": float(np.mean(eq_values)),
        "path_equivalent_minimum": float(np.min(eq_values)),
        "path_equivalent_maximum": float(np.max(eq_values)),
        "path_equivalent_standard_deviation": float(np.std(eq_values)),
        "positive_path_equivalent_mean": float(np.mean(positive)) if positive.size else None,
        "largest_resistance_path": largest,
        "smallest_resistance_path": smallest,
        "hydraulic_assumption": (
            "local cubic-law resistances in series along each path; path conductances "
            "combined in parallel using projected transverse control widths"
        ),
        "cfd_validated": False,
    }
    return summary, rows, profiles


def _summary(values: np.ndarray) -> dict[str, float | int]:
    finite = values[np.isfinite(values)]
    result: dict[str, float | int] = {
        "valid_profiles": int(finite.size),
        "mean": float(np.mean(finite)),
        "median": float(np.median(finite)),
        "minimum": float(np.min(finite)),
        "maximum": float(np.max(finite)),
        "standard_deviation": float(np.std(finite)),
    }
    result.update(
        {f"percentile_{value}": float(np.percentile(finite, value)) for value in PERCENTILES}
    )
    return result


def geometrical_tortuosity(
    surface: PreparedSurface,
    profiles: ProfileSet,
    *,
    direction_label: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Calculate profile-length/projected-length tortuosity for all three walls."""

    rows: list[dict[str, object]] = []
    summaries: dict[str, object] = {}
    for surface_name, height in (
        ("lower", surface.lower),
        ("upper", surface.upper),
        ("mid", surface.mid),
    ):
        sampled = sample_profiles(surface, height, profiles)
        values: list[float] = []
        for index, (distance, elevation, offset) in enumerate(
            zip(profiles.projected_distance, sampled, profiles.offsets, strict=True),
            start=1,
        ):
            valid = np.isfinite(distance) & np.isfinite(elevation)
            s = distance[valid]
            z = elevation[valid]
            if s.size < 2:
                tortuosity = np.nan
                profile_length = np.nan
                projected_length = np.nan
            else:
                ds = np.diff(s)
                dz = np.diff(z)
                profile_length = float(np.sum(np.hypot(ds, dz)))
                projected_length = float(np.sum(np.abs(ds)))
                tortuosity = profile_length / projected_length
            values.append(tortuosity)
            rows.append(
                {
                    "surface": surface_name,
                    "direction": direction_label,
                    "profile": index,
                    "transverse_offset": float(offset),
                    "profile_length": profile_length,
                    "projected_length": projected_length,
                    "geometrical_tortuosity": tortuosity,
                }
            )
        summaries[surface_name] = _summary(np.asarray(values))
    summaries["parameter_plane_direction"] = profiles.direction_xy.tolist()
    return summaries, rows
