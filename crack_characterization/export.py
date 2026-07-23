"""Machine-readable tables and reproducible Markdown report export."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .model import AnalysisResult, CharacterizationConfig


def _json_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None if np.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    return value


def _flatten(value: Any, prefix: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten(item, path))
    elif not isinstance(value, (list, tuple, np.ndarray)):
        rows.append({"metric": prefix, "value": _json_value(value)})
    return rows


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _json_value(row.get(key)) for key in fields})


def _markdown_report(
    result: AnalysisResult,
    config: CharacterizationConfig,
    exported: dict[str, Path],
) -> str:
    summary = result.summary
    aperture = summary["aperture"]["statistics"]
    hydraulic = summary["hydraulic"]
    tortuosity = summary["tortuosity"]["mid"]
    lines = [
        "# Advanced crack characterization report",
        "",
        f"- Generated: {summary['generated_at_utc']}",
        f"- Source mode: `{summary['source']['mode']}`",
        f"- Grid: {summary['source']['points_x']} × {summary['source']['points_y']} points",
        f"- Coordinate unit: `{config.length_unit}`",
        f"- Aperture definition: `{config.aperture_method}`",
        f"- Selected flow direction: `{config.flow_direction}`",
        f"- Configured hydraulic cutoff: {config.aperture_cutoff:.8g} {config.length_unit}",
        "",
        "## Principal results",
        "",
        "| Quantity | Value | Interpretation |",
        "|---|---:|---|",
        (
            f"| Arithmetic mean aperture | {aperture['arithmetic_mean']:.8g} "
            f"{config.length_unit} | Geometrical statistic |"
        ),
        (
            f"| Cubic-mean aperture | {aperture['global_cubic_mean']:.8g} "
            f"{config.length_unit} | Global conductance proxy; not a series-flow equivalent |"
        ),
        (
            f"| Area-weighted cubic mean | "
            f"{aperture['projected_area_weighted_cubic_mean']:.8g} "
            f"{config.length_unit} | Projected-area-weighted conductance proxy |"
        ),
        (
            f"| Flow-path equivalent aperture | "
            f"{hydraulic['global_equivalent_hydraulic_aperture']:.8g} "
            f"{config.length_unit} | Cubic-law series/parallel proxy; requires CFD validation |"
        ),
        (
            f"| Mean mid-surface tortuosity | {tortuosity['mean']:.8g} | "
            "Purely geometrical profile tortuosity |"
        ),
        "",
        "## Definitions and assumptions",
        "",
        "- Arithmetic aperture is the mean of valid geometrical openings.",
        "- Cubic mean is `(mean(b^3))^(1/3)`; the area-weighted form uses projected node-control areas.",
        "- Each flow path uses the inverse cubic mean of resistance in series. Paths are combined in parallel by projected transverse width.",
        "- Geometrical tortuosity is profile arc length divided by projected length. It is not called hydraulic tortuosity.",
        "- Local-normal aperture projects paired global-Z wall separation onto normals estimated from the mid-surface.",
        "- Hurst fits report method, scaling range, sample count, R², bootstrap interval, and reliability warnings.",
        "",
        "## Warnings and exclusions",
        "",
    ]
    lines.extend(
        [f"- {warning}" for warning in result.warnings]
        or ["- No numerical warnings were emitted."]
    )
    lines.extend(["", "## Exported artifacts", ""])
    for name, path in sorted(exported.items()):
        lines.append(f"- `{name}`: `{path.name}`")
    lines.extend(
        [
            "",
            "## Scientific scope",
            "",
            "Hydraulic quantities in this report are geometry-based cubic-law proxies. "
            "They are not CFD results and must be validated for contact, inertial, "
            "compressibility, or strongly three-dimensional flow effects.",
            "",
        ]
    )
    return "\n".join(lines)


def export_results(
    result: AnalysisResult,
    config: CharacterizationConfig,
    output_directory: Path,
) -> dict[str, Path]:
    """Write the required JSON/CSV files and a human-readable report."""

    output_directory.mkdir(parents=True, exist_ok=True)
    table_names = {
        "aperture_statistics": "aperture_statistics.csv",
        "directional_tortuosity": "directional_tortuosity.csv",
        "flow_path_equivalent_aperture": "flow_path_equivalent_aperture.csv",
        "hurst_analysis": "hurst_analysis.csv",
        "roughness_statistics": "roughness_statistics.csv",
        "surface_orientation_statistics": "surface_orientation_statistics.csv",
        "synthetic_surface_validation": "synthetic_surface_validation.csv",
    }
    exported: dict[str, Path] = {}
    summary_path = output_directory / "characterization_summary.json"
    summary_payload = _json_value(result.summary)
    summary_payload["warnings"] = result.warnings
    summary_payload["export_timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    summary_path.write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    exported["characterization_summary_json"] = summary_path

    flat_path = output_directory / "characterization_summary.csv"
    _write_rows(flat_path, _flatten(result.summary))
    exported["characterization_summary_csv"] = flat_path
    for key, filename in table_names.items():
        path = output_directory / filename
        _write_rows(path, result.tables.get(key, []))
        exported[key] = path
    report_path = output_directory / "characterization_report.md"
    all_exported = {**result.exported_files, **exported}
    report_path.write_text(
        _markdown_report(result, config, all_exported),
        encoding="utf-8",
    )
    exported["characterization_report"] = report_path
    return exported
