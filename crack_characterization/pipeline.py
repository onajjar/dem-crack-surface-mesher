"""Orchestration of the reusable characterization stages."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from surface_generation import SurfaceGrid, write_surface_grid

from .aperture import calculate_apertures
from .export import export_results
from .flow_metrics import (
    ProfileSet,
    equivalent_hydraulic_aperture,
    geometrical_tortuosity,
)
from .geometry import (
    open_region_statistics,
    projected_area_weights,
    surface_geometry_metrics,
)
from .model import (
    AnalysisResult,
    CancellationCallback,
    CharacterizationConfig,
    PreparedSurface,
    ProgressCallback,
    SyntheticConfig,
)
from .roughness import roughness_analysis
from .statistics import aperture_statistics, statistics_table
from .synthetic_surface import generate_synthetic_surface
from .validation import prepare_surface
from .visualization import export_figures
from .wavelet import export_wavelet_decomposition, wavelet_decomposition

SOFTWARE_VERSION = "0.1.0"


def _notify(
    progress: ProgressCallback | None,
    fraction: float,
    message: str,
    cancelled: CancellationCallback | None,
) -> None:
    if cancelled is not None and cancelled():
        raise InterruptedError("Crack characterization was cancelled.")
    if progress is not None:
        progress(fraction, message)


def _roughness_table(
    roughness: dict[str, object],
    length_unit: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for surface_name, metrics in roughness.items():
        assert isinstance(metrics, dict)
        for metric, value in metrics.items():
            if "slope" in metric or "anisotropy" in metric:
                unit = "1"
            elif "correlation_length" in metric or "roughness" in metric or "height" in metric:
                unit = length_unit
            else:
                unit = "1"
            rows.append(
                {
                    "surface": surface_name,
                    "metric": metric,
                    "value": value,
                    "unit": unit,
                }
            )
    return rows


def _orientation_table(
    geometry: dict[str, object],
    length_unit: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    plane = geometry["mean_plane"]
    normals = geometry["normal_orientation"]
    for metric, value in {**plane, **normals}.items():
        unit = (
            "degrees"
            if "degrees" in metric
            else length_unit
            if metric == "intercept"
            else "1"
        )
        rows.append({"metric": metric, "value": value, "unit": unit})
    return rows


def _synthetic_validation_rows(
    target: SyntheticConfig,
    achieved: AnalysisResult,
) -> list[dict[str, object]]:
    aperture = achieved.summary["aperture"]["statistics"]
    roughness = achieved.summary["roughness"]["mid"]
    counts = achieved.summary["aperture"]["counts"]
    comparisons = {
        "mean_aperture": (target.mean_aperture, aperture["arithmetic_mean"]),
        "aperture_standard_deviation": (
            target.aperture_std,
            aperture["standard_deviation"],
        ),
        "minimum_aperture": (target.minimum_aperture, aperture["minimum"]),
        "maximum_aperture": (target.maximum_aperture, aperture["maximum"]),
        "mid_surface_rms": (
            target.mid_surface_rms,
            roughness["root_mean_square_roughness_rq"],
        ),
        "contact_fraction": (
            target.contact_fraction,
            counts["closed_or_invalid_sample_fraction"],
        ),
    }
    rows: list[dict[str, object]] = []
    for metric, (target_value, achieved_value) in comparisons.items():
        if target_value is None:
            error = None
            relative = None
        else:
            error = float(achieved_value) - float(target_value)
            relative = error / float(target_value) if target_value != 0 else None
        rows.append(
            {
                "metric": metric,
                "target": target_value,
                "achieved": achieved_value,
                "absolute_error": error,
                "relative_error": relative,
            }
        )
    return rows


def _directional_tortuosity(
    surface: PreparedSurface,
    profiles_xy: dict[str, ProfileSet],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Evaluate geometrical tortuosity automatically along global X and Y."""

    directional_summaries: dict[str, object] = {}
    rows: list[dict[str, object]] = []
    for label, profiles in profiles_xy.items():
        directional_summary, directional_rows = geometrical_tortuosity(
            surface,
            profiles,
            direction_label=label,
        )
        directional_summaries[label] = directional_summary
        rows.extend(directional_rows)
    x_summary = directional_summaries["X"]
    y_summary = directional_summaries["Y"]
    assert isinstance(x_summary, dict)
    assert isinstance(y_summary, dict)
    summaries: dict[str, object] = {
        "lower": y_summary["lower"],
        "upper": y_summary["upper"],
        "mid": y_summary["mid"],
        "mid_transverse": x_summary["mid"],
        "directions": directional_summaries,
        "automatic_directions": ["X", "Y"],
    }
    summaries["definition"] = (
        "geometrical profile length divided by projected profile length"
    )
    return summaries, rows


def _all_hydraulic_directions(
    surface: PreparedSurface,
    apertures: dict[str, np.ndarray],
    config: CharacterizationConfig,
) -> tuple[
    dict[str, dict[str, dict[str, object]]],
    list[dict[str, object]],
    dict[str, ProfileSet],
]:
    """Evaluate both apertures in X/Y plus any legacy configured direction."""

    requested = ["X", "Y"]
    configured = config.flow_direction.strip().upper()
    if configured not in requested:
        requested.append(configured)
    summaries: dict[str, dict[str, dict[str, object]]] = {}
    rows: list[dict[str, object]] = []
    profiles_by_direction: dict[str, ProfileSet] = {}
    for aperture_method, aperture in apertures.items():
        method_summaries: dict[str, dict[str, object]] = {}
        for direction in requested:
            direction_config = replace(config, flow_direction=direction)
            hydraulic, direction_rows, profiles = equivalent_hydraulic_aperture(
                surface,
                aperture,
                direction_config,
            )
            method_summaries[direction] = hydraulic
            profiles_by_direction.setdefault(direction, profiles)
            for row in direction_rows:
                rows.append(
                    {
                        "aperture_definition": aperture_method,
                        "direction": direction,
                        **row,
                    }
                )
        summaries[aperture_method] = method_summaries
    return summaries, rows, profiles_by_direction


def characterize_surface(
    grid: SurfaceGrid,
    config: CharacterizationConfig | None = None,
    *,
    output_directory: Path | None = None,
    synthetic_config: SyntheticConfig | None = None,
    progress: ProgressCallback | None = None,
    cancelled: CancellationCallback | None = None,
    _nested: bool = False,
) -> AnalysisResult:
    """Characterize the same ``SurfaceGrid`` consumed by the mesh pipeline."""

    config = (config or CharacterizationConfig()).validated()
    _notify(progress, 0.03, "Validating structured crack walls", cancelled)
    surface = prepare_surface(grid, config)
    apertures, normals, aperture_definitions = calculate_apertures(
        surface,
        config,
    )
    preferred_method = "local_normal"
    aperture = apertures[preferred_method]
    _notify(
        progress,
        0.15,
        "Calculating both global-Z and local-normal aperture statistics",
        cancelled,
    )
    aperture_results = {
        method: aperture_statistics(
            surface,
            values,
            cutoff=config.aperture_cutoff,
        )
        for method, values in apertures.items()
    }
    aperture_result = aperture_results[preferred_method]
    _notify(
        progress,
        0.27,
        "Resolving X/Y cubic-law paths for both aperture definitions",
        cancelled,
    )
    hydraulic_directions, flow_rows, profiles_by_direction = (
        _all_hydraulic_directions(
            surface,
            apertures,
            config,
        )
    )
    selected_method = config.aperture_method
    selected_direction = config.flow_direction.strip().upper()
    hydraulic = hydraulic_directions[selected_method][selected_direction]
    _notify(progress, 0.40, "Calculating directional geometrical tortuosity", cancelled)
    tortuosity, tortuosity_rows = _directional_tortuosity(
        surface,
        {key: profiles_by_direction[key] for key in ("X", "Y")},
    )
    _notify(progress, 0.52, "Calculating roughness and Hurst diagnostics", cancelled)
    roughness, hurst_rows, roughness_arrays, roughness_warnings = roughness_analysis(
        surface,
        profiles_by_direction["X"],
        config,
    )
    _notify(
        progress,
        0.64,
        "Decomposing crack surfaces into additive wavelet scales",
        cancelled,
    )
    wavelet_summary, wavelet_rows, wavelet_results, wavelet_warnings = (
        wavelet_decomposition(
            surface,
            {
                "lower_wall": surface.lower,
                "upper_wall": surface.upper,
                "mid_surface": surface.mid,
                "aperture_global_z": apertures["global_z"],
                "aperture_local_normal": apertures["local_normal"],
            },
        )
    )
    _notify(progress, 0.72, "Calculating geometry, orientation, and connectivity", cancelled)
    geometry = surface_geometry_metrics(surface, normals, aperture)
    valid_open = np.isfinite(aperture) & (aperture > config.aperture_cutoff)
    connectivity = open_region_statistics(valid_open, surface)
    projected = projected_area_weights(surface)
    positive = np.where(valid_open, aperture, 0.0)
    smooth_reference = aperture_result["statistics"]["arithmetic_mean"]
    conductance_integral = float(np.sum(projected * positive**3))
    smooth_conductance = float(np.sum(projected) * smooth_reference**3)
    gradients_y, gradients_x = np.gradient(
        aperture,
        surface.y_axis,
        surface.x_axis,
        edge_order=2,
    )
    finite_gradients = np.isfinite(gradients_x) & np.isfinite(gradients_y)
    additional = {
        "hydraulic_conductance_proxy_integral_b_cubed": conductance_integral,
        "normalized_conductance_relative_to_mean_parallel_plates": (
            conductance_integral / smooth_conductance if smooth_conductance > 0 else None
        ),
        "aperture_gradient_x_mean": float(np.nanmean(gradients_x)),
        "aperture_gradient_x_standard_deviation": float(np.nanstd(gradients_x)),
        "aperture_gradient_y_mean": float(np.nanmean(gradients_y)),
        "aperture_gradient_y_standard_deviation": float(np.nanstd(gradients_y)),
        "aperture_gradient_magnitude_mean": float(
            np.mean(np.hypot(gradients_x[finite_gradients], gradients_y[finite_gradients]))
        ),
        "bottleneck_grid_index": [
            int(value)
            for value in np.unravel_index(np.nanargmin(aperture), aperture.shape)
        ],
        "bottleneck_coordinates": [
            float(surface.x[np.unravel_index(np.nanargmin(aperture), aperture.shape)]),
            float(surface.y[np.unravel_index(np.nanargmin(aperture), aperture.shape)]),
        ],
    }
    warnings = [*surface.warnings, *roughness_warnings, *wavelet_warnings]
    for method, directions in hydraulic_directions.items():
        for direction, direction_summary in directions.items():
            closed_paths = direction_summary["closed_or_disconnected_paths"]
            if closed_paths:
                warnings.append(
                    f"{closed_paths} {direction}-direction paths for {method} aperture "
                    "contain opening at or below the cutoff and were assigned zero "
                    "path conductance."
                )
    summary: dict[str, Any] = {
        "schema_version": 1,
        "software": {
            "name": "dem-cfd-crack-geometry-to-mesh-converter",
            "characterization_version": SOFTWARE_VERSION,
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "mode": surface.source_mode,
            "points_x": surface.shape[1],
            "points_y": surface.shape[0],
            "x_range": [float(surface.x_axis[0]), float(surface.x_axis[-1])],
            "y_range": [float(surface.y_axis[0]), float(surface.y_axis[-1])],
            "length_unit": config.length_unit,
            "metadata": surface.source_metadata,
        },
        "configuration": asdict(config),
        "preprocessing": {
            "rectilinear_grid": True,
            "matching_wall_grids": True,
            "interpolate_missing": config.interpolate_missing,
            "invalid_samples_preserved_in_counts": True,
        },
        "analysis_mode": {
            "automatic": True,
            "aperture_definitions": ["global_z", "local_normal"],
            "directions": ["X", "Y"],
            "hurst_methods": ["structure_function", "power_spectral_density"],
            "user_analysis_inputs_required": False,
        },
        "aperture_definition": aperture_definitions[preferred_method],
        "aperture_definitions": aperture_definitions,
        "aperture": aperture_result,
        "apertures": aperture_results,
        "hydraulic": hydraulic,
        "hydraulic_by_aperture_and_direction": hydraulic_directions,
        "tortuosity": tortuosity,
        "roughness": roughness,
        "wavelet_decomposition": wavelet_summary,
        "geometry": geometry,
        "connectivity": connectivity,
        "additional_metrics": additional,
        "scientific_scope": {
            "geometrical_tortuosity_only": True,
            "hydraulic_values_are_cubic_law_proxies": True,
            "requires_cfd_validation": True,
        },
    }
    aperture_rows: list[dict[str, Any]] = []
    for method, method_result in aperture_results.items():
        combined_aperture = {
            **method_result["statistics"],
            **method_result["counts"],
        }
        aperture_rows.extend(
            {
                "aperture_definition": method,
                **row,
            }
            for row in statistics_table(
                combined_aperture,
                length_unit=config.length_unit,
            )
        )
    tables: dict[str, list[dict[str, Any]]] = {
        "aperture_statistics": aperture_rows,
        "directional_tortuosity": tortuosity_rows,
        "flow_path_equivalent_aperture": flow_rows,
        "hurst_analysis": hurst_rows,
        "roughness_statistics": _roughness_table(roughness, config.length_unit),
        "wavelet_decomposition": wavelet_rows,
        "surface_orientation_statistics": _orientation_table(
            geometry,
            config.length_unit,
        ),
        "synthetic_surface_validation": [],
    }
    arrays = {
        "aperture": aperture,
        "aperture_global_z": apertures["global_z"],
        "aperture_local_normal": apertures["local_normal"],
        "mid_surface": surface.mid,
        "normal_x": normals[..., 0],
        "normal_y": normals[..., 1],
        "normal_z": normals[..., 2],
        **roughness_arrays,
    }
    result = AnalysisResult(
        summary=summary,
        tables=tables,
        arrays=arrays,
        warnings=warnings,
        output_directory=output_directory,
    )

    if synthetic_config is not None and not _nested:
        _notify(progress, 0.77, "Generating and verifying synthetic crack", cancelled)
        synthetic_config.validated()
        synthetic_directory = (
            (output_directory or Path.cwd() / "characterization_output") / "synthetic"
        )
        validation_rows: list[dict[str, object]] = []
        realization_records: list[dict[str, object]] = []
        for index in range(synthetic_config.realizations):
            _notify(
                progress,
                0.77 + 0.08 * index / synthetic_config.realizations,
                (
                    "Generating and verifying synthetic realization "
                    f"{index + 1}/{synthetic_config.realizations}"
                ),
                cancelled,
            )
            realization_directory = (
                synthetic_directory
                if synthetic_config.realizations == 1
                else synthetic_directory / f"realization_{index + 1:03d}"
            )
            synthetic = generate_synthetic_surface(
                synthetic_config,
                realization_index=index,
            )
            csv_files = write_surface_grid(
                synthetic,
                realization_directory / "surface_csv",
            )
            verification = characterize_surface(
                synthetic,
                replace(
                    config,
                    generate_figures=False,
                    hurst_bootstrap_samples=min(
                        20,
                        config.hurst_bootstrap_samples,
                    ),
                ),
                output_directory=realization_directory / "verification",
                progress=None,
                cancelled=cancelled,
                _nested=True,
            )
            realization_validation = _synthetic_validation_rows(
                synthetic_config,
                verification,
            )
            for row in realization_validation:
                row["realization"] = index + 1
            validation_rows.extend(realization_validation)
            realization_records.append(
                {
                    "realization": index + 1,
                    "random_seed": synthetic_config.random_seed + index,
                    "csv_files": {
                        key: str(value)
                        for key, value in asdict(csv_files).items()
                    },
                    "validation": realization_validation,
                }
            )
        result.tables["synthetic_surface_validation"] = validation_rows
        synthetic_summary: dict[str, object] = {
            "configuration": asdict(synthetic_config),
            "realizations": realization_records,
        }
        if synthetic_config.realizations == 1:
            synthetic_summary["csv_files"] = realization_records[0]["csv_files"]
            synthetic_summary["validation"] = validation_rows
        result.summary["synthetic_surface"] = synthetic_summary
    _notify(progress, 0.86, "Writing characterization exports", cancelled)
    if output_directory is not None:
        if not _nested:
            result.exported_files.update(
                export_wavelet_decomposition(
                    surface,
                    wavelet_results,
                    output_directory,
                    generate_figures=config.generate_figures,
                    figure_dpi=config.figure_dpi,
                )
            )
        if config.generate_figures:
            _notify(progress, 0.88, "Rendering publication-quality figures", cancelled)
            result.exported_files.update(
                export_figures(surface, aperture, result, config, output_directory)
            )
        _notify(progress, 0.96, "Writing tables and reproducibility report", cancelled)
        result.exported_files.update(export_results(result, config, output_directory))
    _notify(progress, 1.0, "Characterization complete", cancelled)
    return result
