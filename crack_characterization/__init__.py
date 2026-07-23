"""Validated characterization of structured reconstructed crack surfaces."""

from .model import (
    AnalysisResult,
    CharacterizationConfig,
    HurstFit,
    PreparedSurface,
    SyntheticConfig,
)
from .pipeline import characterize_surface
from .synthetic_surface import generate_synthetic_surface

__all__ = [
    "AnalysisResult",
    "CharacterizationConfig",
    "HurstFit",
    "PreparedSurface",
    "SyntheticConfig",
    "characterize_surface",
    "generate_synthetic_surface",
]

__version__ = "0.1.0"
