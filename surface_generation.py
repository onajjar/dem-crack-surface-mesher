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

from python_hole_interpolation import load_surface_csvs

SUPPORTED_SURFACE_MODES = {"csv", "deap", "fractal", "constant"}


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
    rms_height: float = 5.0e-5
    mean_aperture: float = 2.0e-4
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

        h = self.hurst_exponent
        dimension = self.fractal_dimension
        if h is None and dimension is None:
            raise ValueError("Fractal mode requires hurst_exponent or fractal_dimension.")
        if h is not None:
            h = float(h)
            if not np.isfinite(h) or not 0.0 < h < 1.0:
                raise ValueError("hurst_exponent must be finite and strictly between 0 and 1.")
        if dimension is not None:
            dimension = float(dimension)
            if not np.isfinite(dimension) or not 2.0 < dimension < 3.0:
                raise ValueError("fractal_dimension must be finite and strictly between 2 and 3.")
            dimension_h = 3.0 - dimension
            if h is not None and not np.isclose(h, dimension_h, rtol=0.0, atol=1.0e-12):
                raise ValueError("fractal_dimension and hurst_exponent must satisfy D = 3 - H.")
            h = dimension_h
        assert h is not None
        return h

    @property
    def resolved_fractal_dimension(self) -> float:
        return 3.0 - self.resolved_hurst_exponent


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


def _self_affine_field(source: SurfaceSource) -> np.ndarray:
    """Synthesize an isotropic Gaussian self-affine field with target RMS.

    For a 2-D surface graph, the power spectral density follows
    ``S(k) proportional to k^-(2H+2)``.  Filtering white-noise Fourier
    amplitudes by ``k^-(H+1)`` therefore supplies the requested scaling.
    """

    if source.points_x < 4 or source.points_y < 4:
        raise ValueError("Fractal synthesis requires at least 4 points in each direction.")
    h = source.resolved_hurst_exponent
    rms_height = _finite_number(source.rms_height, "rms_height")
    if rms_height < 0.0:
        raise ValueError("rms_height must be >= 0.")
    seed = _integer(source.random_seed, "random_seed", 0)
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal((source.points_y, source.points_x))
    spectrum = np.fft.rfft2(noise)

    dx = float(source.size_x) / (source.points_x - 1)
    dy = float(source.size_y) / (source.points_y - 1)
    kx = 2.0 * np.pi * np.fft.rfftfreq(source.points_x, d=dx)
    ky = 2.0 * np.pi * np.fft.fftfreq(source.points_y, d=dy)
    radial_wavenumber = np.hypot(ky[:, None], kx[None, :])
    spectral_filter = np.zeros_like(radial_wavenumber)
    nonzero = radial_wavenumber > 0.0
    spectral_filter[nonzero] = radial_wavenumber[nonzero] ** (-(h + 1.0))
    spectrum *= spectral_filter
    spectrum[0, 0] = 0.0

    field = np.fft.irfft2(spectrum, s=noise.shape).real
    field -= float(field.mean())
    current_rms = float(np.sqrt(np.mean(field * field)))
    if rms_height == 0.0:
        return np.zeros_like(field)
    if not np.isfinite(current_rms) or current_rms <= np.finfo(float).tiny:
        raise RuntimeError("Fractal synthesis produced a degenerate field.")
    return field * (rms_height / current_rms)


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
            aperture = _finite_number(source.mean_aperture, "mean_aperture")
            if aperture <= 0.0:
                raise ValueError("mean_aperture must be > 0 for a volume mesh.")
            mean_surface = _self_affine_field(source)
            zmin = mean_surface - aperture / 2.0
            zmax = mean_surface + aperture / 2.0
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
