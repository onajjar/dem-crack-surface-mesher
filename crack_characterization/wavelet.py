"""Reconstruction-preserving multiscale wavelet decomposition of crack fields."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pywt
from scipy.interpolate import griddata

matplotlib.use("Agg")
from matplotlib import pyplot as plt

from .model import PreparedSurface

DEFAULT_WAVELET = "db2"
FALLBACK_WAVELET = "haar"
EXTENSION_MODE = "symmetric"
MAX_LEVELS = 5

WAVELET_EXPORT_README = """# Additive wavelet decomposition

This directory contains automatic two-dimensional decompositions of the lower
wall, upper wall, mid-surface, global-Z aperture, and local-normal aperture.
No wavelet parameters are required in the interface.

For each field, the full-resolution component files obey

```
wavelet_target_surface.csv
  = approximation_level_J.csv
  + sum(detail_level_j_combined.csv, j = 1 ... J)
```

At every level, the combined detail is also the sum of the horizontal,
vertical, and diagonal files. Level 1 is the finest scale; increasing levels
represent progressively larger structures. Detail surfaces are signed
oscillatory components and should not be interpreted as crack openings in
isolation.

Use `manifest.json` to discover the available fields. Each field's
`metadata.json` records the wavelet, boundary mode, approximate physical
wavelength bands, and floating-point reconstruction errors. Shared
`x_coordinates.csv` and `y_coordinates.csv` preserve the input grid.

The complete equations, assumptions, and limitations are in
`../characterization_equations.md`.
"""


@dataclass
class WaveletFieldResult:
    """One full-resolution additive decomposition."""

    name: str
    original: np.ndarray
    target: np.ndarray
    approximation: np.ndarray
    details: dict[int, np.ndarray]
    directional_details: dict[tuple[int, str], np.ndarray]
    reconstruction: np.ndarray
    reconstruction_error: np.ndarray
    metadata: dict[str, Any]


def _fill_nonfinite(
    surface: PreparedSurface,
    values: np.ndarray,
) -> tuple[np.ndarray, int]:
    finite = np.isfinite(values)
    missing = int(values.size - np.count_nonzero(finite))
    if missing == 0:
        return np.array(values, copy=True, dtype=float), 0
    if np.count_nonzero(finite) < 3:
        raise ValueError("Wavelet decomposition requires at least three finite values.")
    points = np.column_stack((surface.x[finite], surface.y[finite]))
    targets = np.column_stack((surface.x[~finite], surface.y[~finite]))
    estimates = griddata(points, values[finite], targets, method="linear")
    unresolved = ~np.isfinite(estimates)
    if np.any(unresolved):
        estimates[unresolved] = griddata(
            points,
            values[finite],
            targets[unresolved],
            method="nearest",
        )
    completed = np.array(values, copy=True, dtype=float)
    completed[~finite] = estimates
    return completed, missing


def _selected_wavelet(shape: tuple[int, int]) -> tuple[str, int]:
    wavelet = DEFAULT_WAVELET
    supported = int(pywt.dwtn_max_level(shape, wavelet))
    if supported < 1:
        wavelet = FALLBACK_WAVELET
        supported = int(pywt.dwtn_max_level(shape, wavelet))
    if supported < 1:
        raise ValueError(
            "The grid is too small for a two-dimensional wavelet decomposition."
        )
    return wavelet, min(supported, MAX_LEVELS)


def _zero_coefficients(coefficients):
    return [
        np.zeros_like(item)
        if isinstance(item, np.ndarray)
        else tuple(np.zeros_like(part) for part in item)
        for item in coefficients
    ]


def _reconstruct_component(
    coefficients,
    *,
    wavelet: str,
    shape: tuple[int, int],
    approximation: bool = False,
    detail_index: int | None = None,
    orientation_index: int | None = None,
) -> np.ndarray:
    selected = _zero_coefficients(coefficients)
    if approximation:
        selected[0] = coefficients[0]
    elif detail_index is not None:
        if orientation_index is None:
            selected[detail_index] = coefficients[detail_index]
        else:
            parts = list(selected[detail_index])
            parts[orientation_index] = coefficients[detail_index][orientation_index]
            selected[detail_index] = tuple(parts)
    reconstructed = pywt.waverec2(
        selected,
        wavelet=wavelet,
        mode=EXTENSION_MODE,
    )
    return np.asarray(reconstructed[: shape[0], : shape[1]], dtype=float)


def _spacing_metadata(axis: np.ndarray) -> dict[str, float | bool]:
    spacing = np.diff(axis)
    mean = float(np.mean(spacing))
    return {
        "mean": mean,
        "minimum": float(np.min(spacing)),
        "maximum": float(np.max(spacing)),
        "uniform": bool(
            np.allclose(
                spacing,
                mean,
                rtol=1.0e-8,
                atol=max(abs(mean), 1.0) * 1.0e-12,
            )
        ),
    }


def _wavelength_band(
    level: int,
    *,
    spacing_x: float,
    spacing_y: float,
) -> dict[str, float]:
    return {
        "wavelength_x_min": float((2**level) * spacing_x),
        "wavelength_x_max": float((2 ** (level + 1)) * spacing_x),
        "wavelength_y_min": float((2**level) * spacing_y),
        "wavelength_y_max": float((2 ** (level + 1)) * spacing_y),
    }


def _component_row(
    field: str,
    component: str,
    values: np.ndarray,
    target: np.ndarray,
    *,
    level: int | None,
    orientation: str,
    wavelength: dict[str, float | None],
) -> dict[str, object]:
    total_sum_squares = float(np.sum(target**2))
    component_sum_squares = float(np.sum(values**2))
    return {
        "field": field,
        "component": component,
        "level": level,
        "orientation": orientation,
        **wavelength,
        "mean": float(np.mean(values)),
        "standard_deviation": float(np.std(values)),
        "root_mean_square": float(np.sqrt(np.mean(values**2))),
        "minimum": float(np.min(values)),
        "maximum": float(np.max(values)),
        "l2_norm": float(np.linalg.norm(values)),
        "squared_l2_fraction_of_target": (
            component_sum_squares / total_sum_squares
            if total_sum_squares > np.finfo(float).tiny
            else None
        ),
    }


def decompose_wavelet_field(
    surface: PreparedSurface,
    name: str,
    values: np.ndarray,
) -> tuple[WaveletFieldResult, list[dict[str, object]], list[str]]:
    """Decompose one field into additive coarse and detail surfaces."""

    original = np.asarray(values, dtype=float)
    target, filled = _fill_nonfinite(surface, original)
    wavelet, level_count = _selected_wavelet(target.shape)
    coefficients = pywt.wavedec2(
        target,
        wavelet=wavelet,
        mode=EXTENSION_MODE,
        level=level_count,
    )
    approximation = _reconstruct_component(
        coefficients,
        wavelet=wavelet,
        shape=target.shape,
        approximation=True,
    )
    details: dict[int, np.ndarray] = {}
    directional: dict[tuple[int, str], np.ndarray] = {}
    orientation_names = ("horizontal", "vertical", "diagonal")
    for coefficient_index in range(1, len(coefficients)):
        level = level_count - coefficient_index + 1
        details[level] = _reconstruct_component(
            coefficients,
            wavelet=wavelet,
            shape=target.shape,
            detail_index=coefficient_index,
        )
        for orientation_index, orientation in enumerate(orientation_names):
            directional[(level, orientation)] = _reconstruct_component(
                coefficients,
                wavelet=wavelet,
                shape=target.shape,
                detail_index=coefficient_index,
                orientation_index=orientation_index,
            )
    reconstruction = np.array(approximation, copy=True)
    for detail in details.values():
        reconstruction += detail
    error = reconstruction - target
    error_l2 = float(np.linalg.norm(error))
    target_l2 = float(np.linalg.norm(target))
    spacing_x = _spacing_metadata(surface.x_axis)
    spacing_y = _spacing_metadata(surface.y_axis)
    levels: list[dict[str, object]] = []
    rows: list[dict[str, object]] = []
    coarse_min_x = float((2 ** (level_count + 1)) * spacing_x["mean"])
    coarse_min_y = float((2 ** (level_count + 1)) * spacing_y["mean"])
    coarse_wavelength: dict[str, float | None] = {
        "wavelength_x_min": coarse_min_x,
        "wavelength_x_max": None,
        "wavelength_y_min": coarse_min_y,
        "wavelength_y_max": None,
    }
    rows.append(
        _component_row(
            name,
            f"approximation_level_{level_count:02d}",
            approximation,
            target,
            level=level_count,
            orientation="coarse",
            wavelength=coarse_wavelength,
        )
    )
    for level in sorted(details):
        wavelength = _wavelength_band(
            level,
            spacing_x=float(spacing_x["mean"]),
            spacing_y=float(spacing_y["mean"]),
        )
        levels.append({"level": level, **wavelength})
        rows.append(
            _component_row(
                name,
                f"detail_level_{level:02d}_combined",
                details[level],
                target,
                level=level,
                orientation="combined",
                wavelength=wavelength,
            )
        )
        for orientation in orientation_names:
            rows.append(
                _component_row(
                    name,
                    f"detail_level_{level:02d}_{orientation}",
                    directional[(level, orientation)],
                    target,
                    level=level,
                    orientation=orientation,
                    wavelength=wavelength,
                )
            )
    metadata: dict[str, Any] = {
        "field": name,
        "shape": [int(target.shape[0]), int(target.shape[1])],
        "wavelet": wavelet,
        "extension_mode": EXTENSION_MODE,
        "levels": level_count,
        "maximum_levels_exported": MAX_LEVELS,
        "invalid_samples_filled_for_transform": filled,
        "spacing_x": spacing_x,
        "spacing_y": spacing_y,
        "wavelength_interpretation": (
            "Approximate dyadic bands from mean grid spacing; exact only for "
            "uniformly sampled axes."
        ),
        "detail_wavelength_bands": levels,
        "coarse_wavelength_minimum": {
            "x": coarse_min_x,
            "y": coarse_min_y,
        },
        "additive_identity": (
            f"wavelet_target_surface = approximation_level_{level_count:02d} "
            "+ sum(detail_level_01_combined ... "
            f"detail_level_{level_count:02d}_combined)"
        ),
        "reconstruction_maximum_absolute_error": float(np.max(np.abs(error))),
        "reconstruction_root_mean_square_error": float(
            np.sqrt(np.mean(error**2))
        ),
        "reconstruction_relative_l2_error": (
            error_l2 / target_l2 if target_l2 > np.finfo(float).tiny else error_l2
        ),
    }
    warnings: list[str] = []
    if filled:
        warnings.append(
            f"wavelet {name}: filled {filled} non-finite values by linear "
            "interpolation with nearest-neighbor boundary fallback; the additive "
            "identity reconstructs the completed transform target."
        )
    if not spacing_x["uniform"] or not spacing_y["uniform"]:
        warnings.append(
            f"wavelet {name}: nonuniform sampling detected; dyadic wavelength "
            "bands are approximate values based on mean grid spacing."
        )
    result = WaveletFieldResult(
        name=name,
        original=original,
        target=target,
        approximation=approximation,
        details=details,
        directional_details=directional,
        reconstruction=reconstruction,
        reconstruction_error=error,
        metadata=metadata,
    )
    return result, rows, warnings


def wavelet_decomposition(
    surface: PreparedSurface,
    fields: dict[str, np.ndarray],
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[WaveletFieldResult],
    list[str],
]:
    """Decompose every requested input field using one automatic policy."""

    results: list[WaveletFieldResult] = []
    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    summary_fields: dict[str, object] = {}
    for name, values in fields.items():
        result, field_rows, field_warnings = decompose_wavelet_field(
            surface,
            name,
            values,
        )
        results.append(result)
        rows.extend(field_rows)
        warnings.extend(field_warnings)
        summary_fields[name] = result.metadata
    summary = {
        "automatic": True,
        "fields": list(fields),
        "preferred_wavelet": DEFAULT_WAVELET,
        "small_grid_fallback_wavelet": FALLBACK_WAVELET,
        "extension_mode": EXTENSION_MODE,
        "maximum_levels": MAX_LEVELS,
        "components_sum_to_transform_target": True,
        "field_results": summary_fields,
    }
    return summary, rows, results, warnings


def _write_matrix(path: Path, values: np.ndarray) -> None:
    np.savetxt(path, values, delimiter=",", fmt="%.17g")


def _component_figure(
    result: WaveletFieldResult,
    x_axis: np.ndarray,
    y_axis: np.ndarray,
    path: Path,
    *,
    dpi: int,
) -> None:
    panels: list[tuple[str, np.ndarray, bool]] = [
        ("Wavelet target", result.target, False),
        (
            f"Coarse approximation L{result.metadata['levels']}",
            result.approximation,
            False,
        ),
    ]
    panels.extend(
        (f"Detail L{level}", result.details[level], True)
        for level in sorted(result.details)
    )
    panels.extend(
        [
            ("Reconstruction", result.reconstruction, False),
            ("Reconstruction error", result.reconstruction_error, True),
        ]
    )
    columns = min(4, len(panels))
    rows = math.ceil(len(panels) / columns)
    figure, axes = plt.subplots(
        rows,
        columns,
        figsize=(4.1 * columns, 3.4 * rows),
        constrained_layout=True,
        squeeze=False,
    )
    extent = [
        float(x_axis[0]),
        float(x_axis[-1]),
        float(y_axis[0]),
        float(y_axis[-1]),
    ]
    for axis, (title, values, symmetric) in zip(
        axes.ravel(),
        panels,
        strict=False,
    ):
        if symmetric:
            maximum = float(np.max(np.abs(values)))
            maximum = max(maximum, np.finfo(float).tiny)
            image = axis.imshow(
                values,
                origin="lower",
                extent=extent,
                aspect="auto",
                cmap="coolwarm",
                vmin=-maximum,
                vmax=maximum,
            )
        else:
            image = axis.imshow(
                values,
                origin="lower",
                extent=extent,
                aspect="auto",
                cmap="viridis",
            )
        axis.set_title(title)
        axis.set_xlabel("X")
        axis.set_ylabel("Y")
        figure.colorbar(image, ax=axis, shrink=0.76)
    for axis in axes.ravel()[len(panels) :]:
        axis.set_visible(False)
    figure.suptitle(
        f"Additive 2D wavelet decomposition — {result.name}",
        fontsize=14,
        fontweight="bold",
    )
    figure.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(figure)


def export_wavelet_decomposition(
    surface: PreparedSurface,
    results: list[WaveletFieldResult],
    output_directory: Path,
    *,
    generate_figures: bool,
    figure_dpi: int,
) -> dict[str, Path]:
    """Write all additive component surfaces and reconstruction evidence."""

    root = output_directory / "wavelet_decomposition"
    root.mkdir(parents=True, exist_ok=True)
    _write_matrix(root / "x_coordinates.csv", surface.x)
    _write_matrix(root / "y_coordinates.csv", surface.y)
    readme_path = root / "README.md"
    readme_path.write_text(WAVELET_EXPORT_README, encoding="utf-8")
    exported: dict[str, Path] = {
        "wavelet_decomposition_directory": root,
        "wavelet_decomposition_readme": readme_path,
    }
    manifest: dict[str, object] = {
        "description": (
            "Each field directory contains full-resolution additive components. "
            "The coarse approximation plus every combined detail level reconstructs "
            "wavelet_target_surface.csv."
        ),
        "readme": "README.md",
        "coordinates": {
            "x": "x_coordinates.csv",
            "y": "y_coordinates.csv",
        },
        "fields": {},
    }
    for result in results:
        field_directory = root / result.name
        field_directory.mkdir(parents=True, exist_ok=True)
        _write_matrix(field_directory / "input_surface.csv", result.original)
        _write_matrix(field_directory / "wavelet_target_surface.csv", result.target)
        level_count = int(result.metadata["levels"])
        _write_matrix(
            field_directory / f"approximation_level_{level_count:02d}.csv",
            result.approximation,
        )
        for level in sorted(result.details):
            _write_matrix(
                field_directory / f"detail_level_{level:02d}_combined.csv",
                result.details[level],
            )
            for orientation in ("horizontal", "vertical", "diagonal"):
                _write_matrix(
                    field_directory
                    / f"detail_level_{level:02d}_{orientation}.csv",
                    result.directional_details[(level, orientation)],
                )
        _write_matrix(
            field_directory / "reconstructed_surface.csv",
            result.reconstruction,
        )
        _write_matrix(
            field_directory / "reconstruction_error.csv",
            result.reconstruction_error,
        )
        metadata_path = field_directory / "metadata.json"
        metadata_path.write_text(
            json.dumps(result.metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        exported[f"wavelet_{result.name}_metadata"] = metadata_path
        figure_path: Path | None = None
        if generate_figures:
            figure_path = field_directory / "wavelet_components.png"
            _component_figure(
                result,
                surface.x_axis,
                surface.y_axis,
                figure_path,
                dpi=figure_dpi,
            )
            exported[f"wavelet_{result.name}_figure"] = figure_path
        manifest["fields"][result.name] = {
            "directory": result.name,
            "metadata": f"{result.name}/metadata.json",
            "figure": (
                f"{result.name}/wavelet_components.png"
                if figure_path is not None
                else None
            ),
            "levels": level_count,
            "reconstruction_maximum_absolute_error": result.metadata[
                "reconstruction_maximum_absolute_error"
            ],
        }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    exported["wavelet_decomposition_manifest"] = manifest_path
    return exported
