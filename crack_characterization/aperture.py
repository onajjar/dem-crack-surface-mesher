"""Geometrical aperture definitions for matching structured crack walls."""

from __future__ import annotations

import numpy as np

from .geometry import unit_normals
from .model import CharacterizationConfig, PreparedSurface


def calculate_aperture(
    surface: PreparedSurface,
    config: CharacterizationConfig,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    """Return aperture, mid-surface normals, and definition metadata.

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
    if config.aperture_method == "global_z":
        aperture = np.array(surface.raw_aperture, copy=True)
        description = "upper minus lower wall along global Z at matching x-y samples"
    else:
        aperture = surface.raw_aperture * normals[..., 2]
        description = (
            "point-paired wall separation projected onto the finite-difference "
            "unit normal of the crack mid-surface"
        )
    aperture[~surface.valid_mask] = np.nan
    metadata = {
        "method": config.aperture_method,
        "description": description,
        "normal_basis": "mid-surface",
        "normal_estimator": "second-order finite differences on physical x/y axes",
        "normal_smoothing_sigma_grid_points": config.normal_smoothing_sigma,
        "boundary_treatment": "second-order one-sided finite differences",
        "unaligned_surface_treatment": (
            "not applicable: the application supplies point-aligned upper and lower grids"
        ),
    }
    return aperture, normals, metadata
