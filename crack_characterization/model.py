"""Shared configuration and result models for crack characterization."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

ProgressCallback = Callable[[float, str], None]
CancellationCallback = Callable[[], bool]


@dataclass(frozen=True)
class CharacterizationConfig:
    """Numerical and reporting options for one characterization run.

    Coordinates and openings are never rescaled. ``length_unit`` is metadata
    attached to values and plots and must describe the units of the input CSVs.
    """

    aperture_method: str = "local_normal"
    flow_direction: str = "Y"
    custom_flow_vector: tuple[float, float, float] = (1.0, 1.0, 0.0)
    tortuosity_direction: str = "flow"
    custom_tortuosity_vector: tuple[float, float, float] = (1.0, 1.0, 0.0)
    aperture_cutoff: float = 1.0e-12
    allow_negative_aperture: bool = False
    interpolate_missing: bool = False
    length_unit: str = "m"
    normal_smoothing_sigma: float = 0.0
    hurst_min_lag: int = 1
    hurst_max_scale_fraction: float = 0.25
    hurst_bootstrap_samples: int = 100
    random_seed: int = 20260723
    publication_formats: tuple[str, ...] = ("png",)
    figure_dpi: int = 220
    generate_figures: bool = True

    def validated(self) -> CharacterizationConfig:
        aperture_method = self.aperture_method.strip().lower().replace("-", "_")
        if aperture_method not in {"global_z", "local_normal"}:
            raise ValueError("aperture_method must be global_z or local_normal.")
        direction = self.flow_direction.strip().upper()
        if direction not in {"X", "Y", "Z", "CUSTOM", "AUTO"}:
            raise ValueError("flow_direction must be X, Y, Z, custom, or auto.")
        tortuosity = self.tortuosity_direction.strip().lower()
        if tortuosity not in {"flow", "transverse", "x", "y", "z", "custom"}:
            raise ValueError(
                "tortuosity_direction must be flow, transverse, X, Y, Z, or custom."
            )
        if not np.isfinite(self.aperture_cutoff) or self.aperture_cutoff < 0.0:
            raise ValueError("aperture_cutoff must be finite and >= 0.")
        if not np.isfinite(self.normal_smoothing_sigma) or self.normal_smoothing_sigma < 0:
            raise ValueError("normal_smoothing_sigma must be finite and >= 0.")
        if self.hurst_min_lag < 1:
            raise ValueError("hurst_min_lag must be >= 1.")
        if not 0.0 < self.hurst_max_scale_fraction <= 0.5:
            raise ValueError("hurst_max_scale_fraction must be in (0, 0.5].")
        if self.hurst_bootstrap_samples < 0:
            raise ValueError("hurst_bootstrap_samples must be >= 0.")
        if not self.length_unit.strip():
            raise ValueError("length_unit must not be empty.")
        formats = tuple(item.lower() for item in self.publication_formats)
        if not formats or any(item not in {"png", "pdf", "svg"} for item in formats):
            raise ValueError("publication_formats may contain png, pdf, and svg.")
        if self.figure_dpi < 72:
            raise ValueError("figure_dpi must be >= 72.")
        for label, vector in (
            ("custom_flow_vector", self.custom_flow_vector),
            ("custom_tortuosity_vector", self.custom_tortuosity_vector),
        ):
            values = np.asarray(vector, dtype=float)
            if values.shape != (3,) or not np.isfinite(values).all():
                raise ValueError(f"{label} must contain three finite components.")
            if np.linalg.norm(values) <= np.finfo(float).tiny:
                raise ValueError(f"{label} must not be the zero vector.")
        return self


@dataclass(frozen=True)
class SyntheticConfig:
    """Targets for one statistically representative synthetic realization."""

    points_x: int
    points_y: int
    size_x: float
    size_y: float
    mean_aperture: float
    aperture_std: float
    mid_surface_rms: float
    hurst_x: float = 0.8
    hurst_y: float = 0.8
    correlation_length_x: float | None = None
    correlation_length_y: float | None = None
    minimum_aperture: float = 0.0
    maximum_aperture: float | None = None
    contact_fraction: float = 0.0
    positive_aperture: bool = True
    mean_plane_slopes: tuple[float, float] = (0.0, 0.0)
    random_seed: int = 20260723
    realizations: int = 1

    def validated(self) -> SyntheticConfig:
        if min(self.points_x, self.points_y) < 8:
            raise ValueError("Synthetic grids require at least 8 points per direction.")
        values = (
            self.size_x,
            self.size_y,
            self.mean_aperture,
            self.aperture_std,
            self.mid_surface_rms,
            self.minimum_aperture,
        )
        if not np.isfinite(values).all():
            raise ValueError("Synthetic dimensions and aperture targets must be finite.")
        if self.size_x <= 0 or self.size_y <= 0:
            raise ValueError("Synthetic surface dimensions must be > 0.")
        if self.mean_aperture < 0 or self.aperture_std < 0 or self.mid_surface_rms < 0:
            raise ValueError("Synthetic aperture and roughness targets must be >= 0.")
        if not 0 < self.hurst_x < 1 or not 0 < self.hurst_y < 1:
            raise ValueError("Synthetic Hurst exponents must be strictly between 0 and 1.")
        if not 0 <= self.contact_fraction < 1:
            raise ValueError("contact_fraction must be in [0, 1).")
        if self.maximum_aperture is not None and self.maximum_aperture < self.minimum_aperture:
            raise ValueError("maximum_aperture must be >= minimum_aperture.")
        if self.realizations < 1:
            raise ValueError("realizations must be >= 1.")
        return self


@dataclass
class PreparedSurface:
    """Validated, consistently ordered structured crack walls."""

    x: np.ndarray
    y: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    mid: np.ndarray
    raw_aperture: np.ndarray
    valid_mask: np.ndarray
    x_axis: np.ndarray
    y_axis: np.ndarray
    warnings: list[str] = field(default_factory=list)
    source_mode: str = "unknown"
    source_metadata: dict[str, Any] | None = None

    @property
    def shape(self) -> tuple[int, int]:
        return self.x.shape


@dataclass(frozen=True)
class HurstFit:
    """One directional scaling fit with diagnostics."""

    method: str
    surface: str
    direction: str
    exponent: float | None
    slope: float | None
    intercept: float | None
    r_squared: float | None
    confidence_low: float | None
    confidence_high: float | None
    points_used: int
    scale_min: float | None
    scale_max: float | None
    reliable: bool
    warning: str | None
    scale: np.ndarray = field(repr=False)
    response: np.ndarray = field(repr=False)
    fitted_response: np.ndarray = field(repr=False)


@dataclass
class AnalysisResult:
    """Complete in-memory characterization and its exported artifacts."""

    summary: dict[str, Any]
    tables: dict[str, list[dict[str, Any]]]
    arrays: dict[str, np.ndarray]
    warnings: list[str]
    output_directory: Path | None = None
    exported_files: dict[str, Path] = field(default_factory=dict)
