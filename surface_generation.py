"""Structured crack-surface sources for the enhanced Cast3M workflow.

The preserved Cast3M programs consume four equally shaped CSV matrices.  This
module keeps that contract while allowing the matrices to come from existing
files, fitted DEAP discrete-simulation results, a reproducible self-affine
spectral synthesis, or two constant planes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
from scipy.special import ndtri

from python_hole_interpolation import load_surface_csvs

SUPPORTED_SURFACE_MODES = {"csv", "deap", "fractal", "constant"}
SUPPORTED_HEIGHT_DISTRIBUTIONS = {"gaussian", "uniform", "laplace", "lognormal"}


@dataclass(frozen=True)
class SurfaceSource:
    """Complete definition of one structured crack-surface source."""

    mode: str = "csv"
    csv_x: Path | None = None
    csv_y: Path | None = None
    csv_zmin: Path | None = None
    csv_zmax: Path | None = None
    points_x: int = 50
    points_y: int = 50
    size_x: float = 1.2
    size_y: float = 0.9
    center_x: float = 0.0
    center_y: float = 0.0
    hurst_exponent: float | None = 0.8
    fractal_dimension: float | None = None
    hurst_exponent_x: float | None = None
    hurst_exponent_y: float | None = None
    rms_height: float = 5.0e-5
    lower_wall_rms: float | None = None
    upper_wall_rms: float | None = None
    mean_aperture: float = 2.0e-4
    minimum_aperture: float = 1.0e-12
    wall_correlation: float = 1.0
    rolloff_wavelength_x: float | None = None
    rolloff_wavelength_y: float | None = None
    height_distribution: str = "gaussian"
    lognormal_shape: float = 0.75
    random_seed: int = 20260721
    constant_zmin: float = 0.0
    constant_zmax: float = 2.0e-4
    deap_results_dir: Path | None = None
    deap_time_step: int = 1
    deap_component: int = 1
    deap_span: float = 0.05
    deap_grid_resolution: int = 50
    deap_opening_threshold: float = 1.0e-8
    deap_orientation: str = "ZX"
    deap_magnification: float = 1.0
    deap_bounding_box: tuple[float, float, float, float, float, float] | None = None

    @property
    def normalized_mode(self) -> str:
        return self.mode.strip().lower().replace("-", "_")

    @property
    def resolved_hurst_exponent(self) -> float:
        """Return H, accepting either H or the graph dimension D = 3 - H."""

        return self.resolved_hurst_exponents[0]

    @property
    def resolved_hurst_exponents(self) -> tuple[float, float]:
        """Return directional ``(Hx, Hy)`` values with legacy H/D fallback."""

        h = self.hurst_exponent
        dimension = self.fractal_dimension
        if h is not None:
            h = _hurst_exponent(h, "hurst_exponent")
        if dimension is not None:
            dimension = float(dimension)
            if not np.isfinite(dimension) or not 2.0 < dimension < 3.0:
                raise ValueError("fractal_dimension must be finite and strictly between 2 and 3.")
            dimension_h = 3.0 - dimension
            if h is not None and not np.isclose(h, dimension_h, rtol=0.0, atol=1.0e-12):
                raise ValueError("fractal_dimension and hurst_exponent must satisfy D = 3 - H.")
            h = dimension_h
        hx = (
            _hurst_exponent(self.hurst_exponent_x, "hurst_exponent_x")
            if self.hurst_exponent_x is not None
            else None
        )
        hy = (
            _hurst_exponent(self.hurst_exponent_y, "hurst_exponent_y")
            if self.hurst_exponent_y is not None
            else None
        )
        if hx is None:
            hx = h if h is not None else hy
        if hy is None:
            hy = h if h is not None else hx
        if hx is None or hy is None:
            raise ValueError(
                "Fractal mode requires hurst_exponent/fractal_dimension or "
                "directional hurst_exponent_x and hurst_exponent_y."
            )
        return hx, hy

    @property
    def resolved_fractal_dimension(self) -> float:
        return 3.0 - self.resolved_hurst_exponent

    @property
    def resolved_fractal_dimensions(self) -> tuple[float, float]:
        hx, hy = self.resolved_hurst_exponents
        return 3.0 - hx, 3.0 - hy


@dataclass(frozen=True)
class SurfaceGrid:
    """Four arrays matching the immutable Cast3M CSV input contract."""

    x: np.ndarray
    y: np.ndarray
    zmin: np.ndarray
    zmax: np.ndarray
    mode: str
    metadata: dict[str, object] | None = None

    @property
    def shape(self) -> tuple[int, int]:
        return self.x.shape

    @property
    def opening(self) -> np.ndarray:
        return self.zmax - self.zmin


@dataclass(frozen=True)
class SurfaceFiles:
    x: Path
    y: Path
    zmin: Path
    zmax: Path


def _finite_number(value: float, label: str) -> float:
    number = float(value)
    if not np.isfinite(number):
        raise ValueError(f"{label} must be finite.")
    return number


def _hurst_exponent(value: float, label: str) -> float:
    exponent = _finite_number(value, label)
    if not 0.0 < exponent < 1.0:
        raise ValueError(f"{label} must be finite and strictly between 0 and 1.")
    return exponent


def _integer(value: int, label: str, minimum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer >= {minimum}.")
    integer = int(value)
    if integer != value or integer < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}.")
    return integer


def _coordinate_grids(source: SurfaceSource) -> tuple[np.ndarray, np.ndarray]:
    points_x = _integer(source.points_x, "points_x", 2)
    points_y = _integer(source.points_y, "points_y", 2)
    size_x = _finite_number(source.size_x, "size_x")
    size_y = _finite_number(source.size_y, "size_y")
    if size_x <= 0.0 or size_y <= 0.0:
        raise ValueError("size_x and size_y must be > 0.")
    center_x = _finite_number(source.center_x, "center_x")
    center_y = _finite_number(source.center_y, "center_y")
    x_axis = np.linspace(center_x - size_x / 2.0, center_x + size_x / 2.0, points_x)
    y_axis = np.linspace(center_y - size_y / 2.0, center_y + size_y / 2.0, points_y)
    return np.meshgrid(x_axis, y_axis)


def _spectral_gaussian_field(
    source: SurfaceSource,
    *,
    seed: int,
    target_rms: float = 1.0,
) -> np.ndarray:
    """Synthesize one directional Gaussian spectral field."""

    if source.points_x < 4 or source.points_y < 4:
        raise ValueError("Fractal synthesis requires at least 4 points in each direction.")
    hx, hy = source.resolved_hurst_exponents
    target_rms = _finite_number(target_rms, "target_rms")
    if target_rms < 0.0:
        raise ValueError("target_rms must be >= 0.")
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal((source.points_y, source.points_x))
    spectrum = np.fft.rfft2(noise)

    dx = float(source.size_x) / (source.points_x - 1)
    dy = float(source.size_y) / (source.points_y - 1)
    kx = 2.0 * np.pi * np.fft.rfftfreq(source.points_x, d=dx)
    ky = 2.0 * np.pi * np.fft.fftfreq(source.points_y, d=dy)
    rolloff_x = source.rolloff_wavelength_x
    rolloff_y = source.rolloff_wavelength_y
    if (rolloff_x is None) != (rolloff_y is None):
        raise ValueError(
            "rolloff_wavelength_x and rolloff_wavelength_y must be supplied together."
        )
    isotropic_legacy = (
        np.isclose(hx, hy, rtol=0.0, atol=1.0e-15)
        and rolloff_x is None
        and rolloff_y is None
    )
    if isotropic_legacy:
        spectral_radius = np.hypot(ky[:, None], kx[None, :])
        local_hurst = np.full_like(spectral_radius, hx)
        filter_radius = spectral_radius
    else:
        if rolloff_x is None:
            reference_x = 2.0 * np.pi / float(source.size_x)
            reference_y = 2.0 * np.pi / float(source.size_y)
            has_rolloff = False
        else:
            rolloff_x = _finite_number(rolloff_x, "rolloff_wavelength_x")
            rolloff_y = _finite_number(rolloff_y, "rolloff_wavelength_y")
            if rolloff_x <= 0.0 or rolloff_y <= 0.0:
                raise ValueError("roll-off wavelengths must be > 0.")
            reference_x = 2.0 * np.pi / rolloff_x
            reference_y = 2.0 * np.pi / rolloff_y
            has_rolloff = True
        qx = kx[None, :] / reference_x
        qy = ky[:, None] / reference_y
        spectral_radius = np.hypot(qy, qx)
        x_weight = np.divide(
            qx * qx,
            spectral_radius * spectral_radius,
            out=np.full_like(spectral_radius, 0.5),
            where=spectral_radius > 0.0,
        )
        local_hurst = hx * x_weight + hy * (1.0 - x_weight)
        filter_radius = (
            np.maximum(spectral_radius, 1.0) if has_rolloff else spectral_radius
        )
    spectral_filter = np.zeros_like(spectral_radius)
    nonzero = spectral_radius > 0.0
    spectral_filter[nonzero] = filter_radius[nonzero] ** (
        -(local_hurst[nonzero] + 1.0)
    )
    spectrum *= spectral_filter
    spectrum[0, 0] = 0.0

    field = np.fft.irfft2(spectrum, s=noise.shape).real
    field -= float(field.mean())
    current_rms = float(np.sqrt(np.mean(field * field)))
    if target_rms == 0.0:
        return np.zeros_like(field)
    if not np.isfinite(current_rms) or current_rms <= np.finfo(float).tiny:
        raise RuntimeError("Fractal synthesis produced a degenerate field.")
    return field * (target_rms / current_rms)


def _height_distribution(source: SurfaceSource) -> str:
    distribution = source.height_distribution.strip().lower().replace("-", "_")
    aliases = {"normal": "gaussian", "log_normal": "lognormal"}
    distribution = aliases.get(distribution, distribution)
    if distribution not in SUPPORTED_HEIGHT_DISTRIBUTIONS:
        choices = ", ".join(sorted(SUPPORTED_HEIGHT_DISTRIBUTIONS))
        raise ValueError(f"height_distribution must be one of: {choices}.")
    return distribution


def _transform_height_distribution(
    field: np.ndarray,
    distribution: str,
    *,
    lognormal_shape: float,
) -> np.ndarray:
    """Rank-map a Gaussian field to a requested marginal and unit RMS."""

    if distribution == "gaussian":
        return field
    flat = field.ravel()
    order = np.argsort(flat, kind="mergesort")
    probabilities = (np.arange(flat.size, dtype=float) + 0.5) / flat.size
    if distribution == "uniform":
        quantiles = probabilities - 0.5
    elif distribution == "laplace":
        centered = probabilities - 0.5
        quantiles = -np.sign(centered) * np.log1p(-2.0 * np.abs(centered))
    else:
        shape = _finite_number(lognormal_shape, "lognormal_shape")
        if not 0.0 < shape <= 3.0:
            raise ValueError("lognormal_shape must be > 0 and <= 3.")
        quantiles = np.exp(shape * ndtri(probabilities))
    mapped = np.empty_like(flat)
    mapped[order] = quantiles
    mapped = mapped.reshape(field.shape)
    mapped -= float(mapped.mean())
    rms = float(np.sqrt(np.mean(mapped * mapped)))
    if not np.isfinite(rms) or rms <= np.finfo(float).tiny:
        raise RuntimeError("Height-distribution transform produced a degenerate field.")
    return mapped / rms


def _population_rms(values: np.ndarray) -> float:
    centered = values - float(values.mean())
    return float(np.sqrt(np.mean(centered * centered)))


def _population_skewness(values: np.ndarray) -> float:
    centered = values - float(values.mean())
    rms = float(np.sqrt(np.mean(centered * centered)))
    if rms <= np.finfo(float).tiny:
        return 0.0
    return float(np.mean(centered**3) / rms**3)


def _fractal_walls(
    source: SurfaceSource,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    """Generate correlated opposing rough walls with a positive opening."""

    seed = _integer(source.random_seed, "random_seed", 0)
    legacy_rms = _finite_number(source.rms_height, "rms_height")
    if legacy_rms < 0.0:
        raise ValueError("rms_height must be >= 0.")
    lower_rms = (
        legacy_rms
        if source.lower_wall_rms is None
        else _finite_number(source.lower_wall_rms, "lower_wall_rms")
    )
    upper_rms = (
        legacy_rms
        if source.upper_wall_rms is None
        else _finite_number(source.upper_wall_rms, "upper_wall_rms")
    )
    if lower_rms < 0.0 or upper_rms < 0.0:
        raise ValueError("lower_wall_rms and upper_wall_rms must be >= 0.")
    aperture = _finite_number(source.mean_aperture, "mean_aperture")
    minimum_aperture = _finite_number(source.minimum_aperture, "minimum_aperture")
    if aperture <= 0.0:
        raise ValueError("mean_aperture must be > 0 for a volume mesh.")
    if minimum_aperture <= 0.0 or minimum_aperture >= aperture:
        raise ValueError(
            "minimum_aperture must be > 0 and strictly below mean_aperture."
        )
    correlation = _finite_number(source.wall_correlation, "wall_correlation")
    if not -1.0 <= correlation <= 1.0:
        raise ValueError("wall_correlation must be between -1 and 1.")
    distribution = _height_distribution(source)

    parallel_gaussian = (
        correlation == 1.0
        and lower_rms == upper_rms
        and distribution == "gaussian"
    )
    if parallel_gaussian:
        lower_roughness = _spectral_gaussian_field(
            source,
            seed=seed,
            target_rms=lower_rms,
        )
        upper_roughness = lower_roughness.copy()
    else:
        lower_gaussian = _spectral_gaussian_field(source, seed=seed)
        if correlation == 1.0:
            upper_gaussian = lower_gaussian.copy()
        elif correlation == -1.0:
            upper_gaussian = -lower_gaussian
        else:
            independent = _spectral_gaussian_field(source, seed=seed + 1)
            upper_gaussian = (
                correlation * lower_gaussian
                + np.sqrt(1.0 - correlation * correlation) * independent
            )
            upper_gaussian -= float(upper_gaussian.mean())
            upper_gaussian /= _population_rms(upper_gaussian)
        lower_unit = _transform_height_distribution(
            lower_gaussian,
            distribution,
            lognormal_shape=source.lognormal_shape,
        )
        upper_unit = _transform_height_distribution(
            upper_gaussian,
            distribution,
            lognormal_shape=source.lognormal_shape,
        )
        lower_roughness = lower_rms * lower_unit
        upper_roughness = upper_rms * upper_unit

    mid_surface = 0.5 * (lower_roughness + upper_roughness)
    opening_fluctuation = upper_roughness - lower_roughness
    opening_scale = 1.0
    minimum_unconstrained = aperture + float(opening_fluctuation.min())
    if minimum_unconstrained < minimum_aperture:
        safe_minimum = np.nextafter(minimum_aperture, aperture)
        opening_scale = (aperture - safe_minimum) / (
            aperture - minimum_unconstrained
        )
        opening_fluctuation *= opening_scale
    opening = aperture + opening_fluctuation
    zmin = mid_surface - 0.5 * opening
    zmax = mid_surface + 0.5 * opening
    lower_final = zmin - float(zmin.mean())
    upper_final = zmax - float(zmax.mean())
    lower_final_rms = _population_rms(lower_final)
    upper_final_rms = _population_rms(upper_final)
    if lower_final_rms > np.finfo(float).tiny and upper_final_rms > np.finfo(float).tiny:
        achieved_correlation: float | None = float(
            np.mean(lower_final * upper_final)
            / (lower_final_rms * upper_final_rms)
        )
    else:
        achieved_correlation = None
    hx, hy = source.resolved_hurst_exponents
    dx, dy = source.resolved_fractal_dimensions
    metadata: dict[str, object] = {
        "generator": "directional correlated-wall spectral synthesis",
        "targets": {
            "hurst_exponent_x": hx,
            "hurst_exponent_y": hy,
            "fractal_dimension_x": dx,
            "fractal_dimension_y": dy,
            "rolloff_wavelength_x": source.rolloff_wavelength_x,
            "rolloff_wavelength_y": source.rolloff_wavelength_y,
            "height_distribution": distribution,
            "lognormal_shape": (
                source.lognormal_shape if distribution == "lognormal" else None
            ),
            "lower_wall_rms": lower_rms,
            "upper_wall_rms": upper_rms,
            "wall_correlation": correlation,
            "mean_aperture": aperture,
            "minimum_aperture": minimum_aperture,
            "random_seed": seed,
        },
        "achieved": {
            "lower_wall_rms": lower_final_rms,
            "upper_wall_rms": upper_final_rms,
            "lower_wall_skewness": _population_skewness(lower_final),
            "upper_wall_skewness": _population_skewness(upper_final),
            "wall_correlation": achieved_correlation,
            "mean_aperture": float(opening.mean()),
            "aperture_standard_deviation": float(opening.std()),
            "minimum_aperture": float(opening.min()),
            "maximum_aperture": float(opening.max()),
            "opening_fluctuation_scale": opening_scale,
        },
    }
    return zmin, zmax, metadata


def validate_surface_grid(grid: SurfaceGrid) -> None:
    expected = grid.x.shape
    if len(expected) != 2 or min(expected) < 2:
        raise ValueError("Surface arrays must be two-dimensional with at least 2 x 2 points.")
    for label, values in (
        ("x", grid.x),
        ("y", grid.y),
        ("zmin", grid.zmin),
        ("zmax", grid.zmax),
    ):
        if values.shape != expected:
            raise ValueError(f"Surface arrays must have one shape; x is {expected} but {label} is {values.shape}.")
        if not np.isfinite(values).all():
            raise ValueError(f"Surface array {label} contains non-finite values.")
    if np.any(grid.zmax < grid.zmin):
        raise ValueError("zmax is below zmin at one or more grid points.")


def build_surface_grid(source: SurfaceSource) -> SurfaceGrid:
    """Load or generate a validated structured crack-surface grid."""

    mode = source.normalized_mode
    if mode not in SUPPORTED_SURFACE_MODES:
        raise ValueError("surface mode must be csv, deap, fractal, or constant.")
    metadata: dict[str, object] | None = None
    if mode == "csv":
        paths = (source.csv_x, source.csv_y, source.csv_zmin, source.csv_zmax)
        if any(path is None for path in paths):
            raise ValueError("CSV mode requires x_csv, y_csv, zmin_csv, and zmax_csv.")
        assert all(path is not None for path in paths)
        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(f"CSV input does not exist: {path}")
        x, y, zmin, zmax = load_surface_csvs(*paths)
    elif mode == "deap":
        if source.deap_results_dir is None:
            raise ValueError("DEAP mode requires deap_results_dir.")
        from deap_crack_surface import SurfaceConfig, reconstruct_surface

        result = reconstruct_surface(
            SurfaceConfig(
                case_dir=source.deap_results_dir,
                time_step=source.deap_time_step,
                component=source.deap_component,
                span=source.deap_span,
                grid_resolution=source.deap_grid_resolution,
                opening_threshold=source.deap_opening_threshold,
                orientation=source.deap_orientation.strip().upper(),
                magnification=source.deap_magnification,
                bounding_box=source.deap_bounding_box,
            )
        )
        x, y, zmin, zmax = result.x, result.y, result.z_min, result.z_max
        metadata = result.metadata
    else:
        x, y = _coordinate_grids(source)
        if mode == "fractal":
            zmin, zmax, metadata = _fractal_walls(source)
        else:
            zmin_value = _finite_number(source.constant_zmin, "constant_zmin")
            zmax_value = _finite_number(source.constant_zmax, "constant_zmax")
            if zmax_value <= zmin_value:
                raise ValueError(
                    "constant_zmax must be greater than constant_zmin; equal values create a zero-volume mesh."
                )
            zmin = np.full_like(x, zmin_value)
            zmax = np.full_like(x, zmax_value)
    grid = SurfaceGrid(x=x, y=y, zmin=zmin, zmax=zmax, mode=mode, metadata=metadata)
    validate_surface_grid(grid)
    return grid


def write_surface_grid(
    grid: SurfaceGrid,
    directory: Path,
    names: Mapping[str, str] | None = None,
) -> SurfaceFiles:
    """Write a generated grid as deterministic headerless Cast3M CSV files."""

    validate_surface_grid(grid)
    directory.mkdir(parents=True, exist_ok=True)
    filenames = {
        "x": "xrange_generated.csv",
        "y": "yrange_generated.csv",
        "zmin": "zfit_zmin_generated.csv",
        "zmax": "zfit_zmax_generated.csv",
    }
    if names is not None:
        filenames.update(names)
    files = SurfaceFiles(
        x=directory / filenames["x"],
        y=directory / filenames["y"],
        zmin=directory / filenames["zmin"],
        zmax=directory / filenames["zmax"],
    )
    for path, values in (
        (files.x, grid.x),
        (files.y, grid.y),
        (files.zmin, grid.zmin),
        (files.zmax, grid.zmax),
    ):
        temporary = path.with_suffix(path.suffix + ".tmp")
        np.savetxt(temporary, values, delimiter=",", fmt="%.17g")
        temporary.replace(path)
    return files
