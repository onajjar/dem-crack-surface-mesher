"""Orchestration of the reusable characterization stages."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from surface_generation import SurfaceGrid, write_surface_grid

from .aperture import calculate_aperture
from .export import export_results
from .flow_metrics import (
    ProfileSet,
    build_profile_set,
    equivalent_hydraulic_aperture,
    geometrical_tortuosity,
    resolve_in_plane_direction,
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
    flow_profiles: ProfileSet,
    config: CharacterizationConfig,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Evaluate the required flow, transverse, X, Y, and selected directions."""

    direction_sets: dict[str, ProfileSet] = {
        "flow": flow_profiles,
        "transverse": build_profile_set(
            surface,
            flow_profiles.transverse_xy,
            -flow_profiles.direction_xy,
        ),
    }
    for label in ("X", "Y"):
        direction, transverse, _ = resolve_in_plane_direction(
            surface,
            label,
            config.custom_tortuosity_vector,
        )
        direction_sets[label] = build_profile_set(surface, direction, transverse)

    selected = config.tortuosity_direction.strip().lower()
    selected_label = {
        "flow": "flow",
        "transverse": "transverse",
        "x": "X",
        "y": "Y",
    }.get(selected)
    if selected_label is None:
        requested = "custom" if selected == "custom" else selected.upper()
        direction, transverse, _ = resolve_in_plane_direction(
            surface,
            requested,
            config.custom_tortuosity_vector,
        )
        selected_label = f"selected_{requested}"
        direction_sets[selected_label] = build_profile_set(
            surface,
            direction,
            transverse,
        )

    directional_summaries: dict[str, object] = {}
    rows: list[dict[str, object]] = []
    for label, profiles in direction_sets.items():
        directional_summary, directional_rows = geometrical_tortuosity(
            surface,
            profiles,
            direction_label=label,
        )
        directional_summaries[label] = directional_summary
        rows.extend(directional_rows)
    flow_summary = directional_summaries["flow"]
    transverse_summary = directional_summaries["transverse"]
    assert isinstance(flow_summary, dict)
    assert isinstance(transverse_summary, dict)
    summaries: dict[str, object] = {
        "lower": flow_summary["lower"],
        "upper": flow_summary["upper"],
        "mid": flow_summary["mid"],
        "mid_transverse": transverse_summary["mid"],
        "directions": directional_summaries,
        "selected_direction": selected_label,
    }
    summaries["definition"] = (
        "geometrical profile length divided by projected profile length"
    )
    return summaries, rows


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
    aperture, normals, aperture_definition = calculate_aperture(surface, config)
    _notify(progress, 0.15, "Calculating aperture statistics", cancelled)
    aperture_result = aperture_statistics(
        surface,
        aperture,
        cutoff=config.aperture_cutoff,
    )
    _notify(progress, 0.27, "Resolving flow paths and cubic-law resistance", cancelled)
    hydraulic, flow_rows, flow_profiles = equivalent_hydraulic_aperture(
        surface,
        aperture,
        config,
    )
    _notify(progress, 0.40, "Calculating directional geometrical tortuosity", cancelled)
    tortuosity, tortuosity_rows = _directional_tortuosity(
        surface,
        flow_profiles,
        config,
    )
    _notify(progress, 0.52, "Calculating roughness and Hurst diagnostics", cancelled)
    roughness, hurst_rows, roughness_arrays, roughness_warnings = roughness_analysis(
        surface,
        flow_profiles,
        config,
    )
    _notify(progress, 0.70, "Calculating geometry, orientation, and connectivity", cancelled)
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
    warnings = [*surface.warnings, *roughness_warnings]
    if hydraulic["closed_or_disconnected_paths"]:
        warnings.append(
            f"{hydraulic['closed_or_disconnected_paths']} flow paths contain aperture "
            "at or below the cutoff and were assigned zero path conductance."
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
        "aperture_definition": aperture_definition,
        "aperture": aperture_result,
        "hydraulic": hydraulic,
        "tortuosity": tortuosity,
        "roughness": roughness,
        "geometry": geometry,
        "connectivity": connectivity,
        "additional_metrics": additional,
        "scientific_scope": {
            "geometrical_tortuosity_only": True,
            "hydraulic_values_are_cubic_law_proxies": True,
            "requires_cfd_validation": True,
        },
    }
    combined_aperture = {
        **aperture_result["statistics"],
        **aperture_result["counts"],
    }
    tables: dict[str, list[dict[str, Any]]] = {
        "aperture_statistics": statistics_table(
            combined_aperture,
            length_unit=config.length_unit,
        ),
        "directional_tortuosity": tortuosity_rows,
        "flow_path_equivalent_aperture": flow_rows,
        "hurst_analysis": hurst_rows,
        "roughness_statistics": _roughness_table(roughness, config.length_unit),
        "surface_orientation_statistics": _orientation_table(
            geometry,
            config.length_unit,
        ),
        "synthetic_surface_validation": [],
    }
    arrays = {
        "aperture": aperture,
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
        if config.generate_figures:
            _notify(progress, 0.88, "Rendering publication-quality figures", cancelled)
            result.exported_files.update(
                export_figures(surface, aperture, result, config, output_directory)
            )
        _notify(progress, 0.96, "Writing tables and reproducibility report", cancelled)
        result.exported_files.update(export_results(result, config, output_directory))
    _notify(progress, 1.0, "Characterization complete", cancelled)
    return result
