"""Reproducible anisotropic spectral crack-surface synthesis."""

from __future__ import annotations

import numpy as np

from surface_generation import SurfaceGrid, validate_surface_grid

from .model import SyntheticConfig


def _spectral_field(
    shape: tuple[int, int],
    size: tuple[float, float],
    *,
    hurst_x: float,
    hurst_y: float,
    correlation_x: float | None,
    correlation_y: float | None,
    rng: np.random.Generator,
) -> np.ndarray:
    points_y, points_x = shape
    size_x, size_y = size
    dx = size_x / (points_x - 1)
    dy = size_y / (points_y - 1)
    kx = 2.0 * np.pi * np.fft.rfftfreq(points_x, d=dx)
    ky = 2.0 * np.pi * np.fft.fftfreq(points_y, d=dy)
    scale_x = correlation_x or size_x / 4.0
    scale_y = correlation_y or size_y / 4.0
    anisotropic_radius = np.hypot(
        ky[:, None] * scale_y,
        kx[None, :] * scale_x,
    )
    angle_weight = np.divide(
        (kx[None, :] * scale_x) ** 2,
        anisotropic_radius**2,
        out=np.full_like(anisotropic_radius, 0.5),
        where=anisotropic_radius > 0,
    )
    local_hurst = hurst_x * angle_weight + hurst_y * (1.0 - angle_weight)
    spectral_filter = np.zeros_like(anisotropic_radius)
    nonzero = anisotropic_radius > 0
    spectral_filter[nonzero] = anisotropic_radius[nonzero] ** (
        -(local_hurst[nonzero] + 1.0)
    )
    noise = rng.standard_normal(shape)
    spectrum = np.fft.rfft2(noise) * spectral_filter
    spectrum[0, 0] = 0.0
    field = np.fft.irfft2(spectrum, s=shape).real
    field -= np.mean(field)
    std = float(np.std(field))
    if std <= np.finfo(float).tiny:
        raise RuntimeError("Synthetic spectral filter produced a degenerate field.")
    return field / std


def generate_synthetic_surface(
    config: SyntheticConfig,
    *,
    realization_index: int = 0,
) -> SurfaceGrid:
    """Generate a new mid-surface and aperture field on the Cast3M CSV grid.

    Upper and lower walls are reconstructed by symmetric global-Z offsets from
    the synthetic mid-surface. This preserves the existing structured-grid
    contract; local-normal separation is recalculated during verification.
    """

    config.validated()
    if not 0 <= realization_index < config.realizations:
        raise ValueError("realization_index is outside the configured realization count.")
    rng = np.random.default_rng(config.random_seed + realization_index)
    x_axis = np.linspace(-config.size_x / 2.0, config.size_x / 2.0, config.points_x)
    y_axis = np.linspace(-config.size_y / 2.0, config.size_y / 2.0, config.points_y)
    x, y = np.meshgrid(x_axis, y_axis)
    mid_unit = _spectral_field(
        x.shape,
        (config.size_x, config.size_y),
        hurst_x=config.hurst_x,
        hurst_y=config.hurst_y,
        correlation_x=config.correlation_length_x,
        correlation_y=config.correlation_length_y,
        rng=rng,
    )
    aperture_unit = _spectral_field(
        x.shape,
        (config.size_x, config.size_y),
        hurst_x=min(0.95, config.hurst_x + 0.05),
        hurst_y=min(0.95, config.hurst_y + 0.05),
        correlation_x=config.correlation_length_x,
        correlation_y=config.correlation_length_y,
        rng=rng,
    )
    slope_x, slope_y = config.mean_plane_slopes
    mid = (
        config.mid_surface_rms * mid_unit
        + slope_x * x
        + slope_y * y
    )
    aperture = config.mean_aperture + config.aperture_std * aperture_unit
    aperture = np.maximum(aperture, config.minimum_aperture)
    if config.maximum_aperture is not None:
        aperture = np.minimum(aperture, config.maximum_aperture)
    if config.contact_fraction > 0:
        count = int(round(aperture.size * config.contact_fraction))
        if count:
            contact = np.argpartition(aperture.ravel(), count - 1)[:count]
            aperture.ravel()[contact] = 0.0
    if config.positive_aperture:
        aperture = np.maximum(aperture, 0.0)
    lower = mid - 0.5 * aperture
    upper = mid + 0.5 * aperture
    grid = SurfaceGrid(
        x=x,
        y=y,
        zmin=lower,
        zmax=upper,
        mode="characterization_synthetic",
        metadata={
            "generator": "anisotropic Gaussian spectral synthesis",
            "random_seed": config.random_seed + realization_index,
            "targets": {
                "mean_aperture": config.mean_aperture,
                "aperture_std": config.aperture_std,
                "mid_surface_rms": config.mid_surface_rms,
                "hurst_x": config.hurst_x,
                "hurst_y": config.hurst_y,
                "correlation_length_x": config.correlation_length_x,
                "correlation_length_y": config.correlation_length_y,
                "contact_fraction": config.contact_fraction,
            },
        },
    )
    validate_surface_grid(grid)
    return grid
