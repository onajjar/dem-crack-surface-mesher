"""Geometrical aperture definitions for matching structured crack walls."""

from __future__ import annotations

import numpy as np

from .geometry import unit_normals
from .model import CharacterizationConfig, PreparedSurface


def calculate_apertures(
    surface: PreparedSurface,
    config: CharacterizationConfig,
) -> tuple[dict[str, np.ndarray], np.ndarray, dict[str, dict[str, object]]]:
    """Return every supported aperture definition and shared surface normals.

    ``global_z`` is the signed upper-minus-lower difference at matching
    ``(x, y)`` samples. ``local_normal`` projects that point-paired vertical
    separation onto the upward unit normal of the mid-surface. It is therefore
    a point-pair projection, not a ray/surface intersection algorithm.
    """

    normals = unit_normals(
        surface.mid,
        surface,
        smoothing_sigma=config.normal_smoothing_sigma,
    )
    apertures = {
        "global_z": np.array(surface.raw_aperture, copy=True),
        "local_normal": surface.raw_aperture * normals[..., 2],
    }
    for aperture in apertures.values():
        aperture[~surface.valid_mask] = np.nan
    shared = {
        "normal_basis": "mid-surface",
        "normal_estimator": "second-order finite differences on physical x/y axes",
        "normal_smoothing_sigma_grid_points": config.normal_smoothing_sigma,
        "boundary_treatment": "second-order one-sided finite differences",
        "unaligned_surface_treatment": (
            "not applicable: the application supplies point-aligned upper and lower grids"
        ),
    }
    definitions = {
        "global_z": {
            "method": "global_z",
            "description": (
                "upper minus lower wall along global Z at matching x-y samples"
            ),
            **shared,
        },
        "local_normal": {
            "method": "local_normal",
            "description": (
                "point-paired wall separation projected onto the finite-difference "
                "unit normal of the crack mid-surface"
            ),
            **shared,
        },
    }
    return apertures, normals, definitions
