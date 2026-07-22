"""Validate integrated Python DEAP fitting against four archived MATLAB surfaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path
from typing import Sequence

import h5py
import numpy as np
import scipy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from castem_pipeline_headless import load_setup, validate_setup  # noqa: E402
from surface_generation import build_surface_grid  # noqa: E402

CASE_NAMES = ("1_simple", "2_large", "3_rebar", "4_brazilian")
ABSOLUTE_TOLERANCE_M = 1.0e-12


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metrics(actual: np.ndarray, reference: np.ndarray) -> dict[str, object]:
    residual = actual - reference
    max_abs_error = float(np.max(np.abs(residual)))
    return {
        "shape": list(actual.shape),
        "value_count": int(actual.size),
        "max_abs_error_m": max_abs_error,
        "mean_error_m": float(np.mean(residual)),
        "rmse_m": float(np.sqrt(np.mean(residual * residual))),
        "within_absolute_tolerance": max_abs_error <= ABSOLUTE_TOLERANCE_M,
    }


def validate_examples() -> tuple[dict[str, object], dict[str, dict[str, np.ndarray]]]:
    cases: dict[str, object] = {}
    plot_data: dict[str, dict[str, np.ndarray]] = {}
    overall_passed = True

    for name in CASE_NAMES:
        case_root = ROOT / "examples" / "deap" / name
        setup = load_setup(case_root / "run.ini")
        started = time.perf_counter()
        fitted = build_surface_grid(setup.surface_source)
        validate_setup(setup, surface_grid=fitted)
        elapsed = time.perf_counter() - started

        csv_setup = load_setup(case_root / "run.ini", surface_mode_override="csv")
        reference = build_surface_grid(csv_setup.surface_source)
        validate_setup(csv_setup, surface_grid=reference)
        actual_arrays = {
            "xrange": fitted.x,
            "yrange": fitted.y,
            "zfit_zmin": fitted.zmin,
            "zfit_zmax": fitted.zmax,
        }
        reference_arrays = {
            "xrange": reference.x,
            "yrange": reference.y,
            "zfit_zmin": reference.zmin,
            "zfit_zmax": reference.zmax,
        }
        comparisons = {
            key: _metrics(actual_arrays[key], reference_arrays[key])
            for key in actual_arrays
        }
        opening = fitted.opening
        physical_checks = {
            "all_outputs_finite": all(
                bool(np.all(np.isfinite(values))) for values in actual_arrays.values()
            ),
            "nonnegative_opening": bool(np.all(opening >= 0.0)),
            "minimum_opening_m": float(np.min(opening)),
            "maximum_opening_m": float(np.max(opening)),
        }
        case_passed = all(
            bool(metric["within_absolute_tolerance"])
            for metric in comparisons.values()
        ) and all(physical_checks[key] for key in ("all_outputs_finite", "nonnegative_opening"))
        overall_passed = overall_passed and case_passed

        source_paths = {
            "results/deap_post.h5": setup.workdir / "deap_post.h5",
            "results/deap_output.h5": setup.workdir / "deap_output.h5",
            f"reference/{csv_setup.csv_x.name}": csv_setup.csv_x,
            f"reference/{csv_setup.csv_y.name}": csv_setup.csv_y,
            f"reference/{csv_setup.csv_zmin.name}": csv_setup.csv_zmin,
            f"reference/{csv_setup.csv_zmax.name}": csv_setup.csv_zmax,
        }
        if (setup.workdir / "input.boundary").is_file():
            source_paths["results/input.boundary"] = setup.workdir / "input.boundary"

        cases[name] = {
            "passed": case_passed,
            "elapsed_seconds": round(elapsed, 6),
            "configuration": {
                "time_step": setup.surface_source.deap_time_step,
                "component": setup.surface_source.deap_component,
                "span": setup.surface_source.deap_span,
                "grid_resolution": setup.surface_source.deap_grid_resolution,
                "opening_threshold_m": setup.surface_source.deap_opening_threshold,
                "orientation": setup.surface_source.deap_orientation,
                "bounding_box_m": list(setup.surface_source.deap_bounding_box or ()),
            },
            "fit_metadata": fitted.metadata,
            "comparisons": comparisons,
            "physical_checks": physical_checks,
            "mode_switch_verified": {
                "deap_mode": setup.surface_source.normalized_mode,
                "csv_mode": csv_setup.surface_source.normalized_mode,
                "same_surface_contract": case_passed,
            },
            "source_sha256": {
                label: _sha256(path) for label, path in source_paths.items()
            },
        }
        plot_data[name] = {
            "x": fitted.x,
            "y": fitted.y,
            "reference_mean": (reference.zmin + reference.zmax) / 2.0,
            "python_mean": (fitted.zmin + fitted.zmax) / 2.0,
            "face_error": np.maximum(
                np.abs(fitted.zmin - reference.zmin),
                np.abs(fitted.zmax - reference.zmax),
            ),
        }

    report: dict[str, object] = {
        "title": "Integrated Python DEAP surface validation",
        "passed": overall_passed,
        "overall_assessment": "verified" if overall_passed else "needs_revision",
        "acceptance_criterion": {
            "description": (
                "Every grid and fitted face value must agree with the archived "
                "MATLAB CSV at the absolute tolerance; values must be finite and "
                "openings nonnegative."
            ),
            "absolute_tolerance_m": ABSOLUTE_TOLERANCE_M,
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "h5py": h5py.__version__,
        },
        "cases": cases,
        "scope": [
            "Integrated headless configuration and surface-source abstraction",
            "Raw DEAP HDF5 to Python quadratic LOESS surface",
            "Existing-CSV bypass path",
            "Four archived application parameter sets",
        ],
        "not_claimed": [
            "MATLAB is not executed by this validator.",
            "The CSV references are archived outputs produced by the legacy MATLAB workflow.",
        ],
    }
    return report, plot_data


def render_comparison(plot_data: dict[str, dict[str, np.ndarray]], output: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    fig, axes = plt.subplots(len(CASE_NAMES), 3, figsize=(14, 15), constrained_layout=True)
    for row, name in enumerate(CASE_NAMES):
        values = plot_data[name]
        reference = values["reference_mean"]
        python_surface = values["python_mean"]
        residual = values["face_error"]
        lower = min(float(np.min(reference)), float(np.min(python_surface)))
        upper = max(float(np.max(reference)), float(np.max(python_surface)))
        for column, (surface, title) in enumerate(
            ((reference, "MATLAB reference mean"), (python_surface, "Python mean"))
        ):
            image = axes[row, column].pcolormesh(
                values["x"],
                values["y"],
                surface,
                shading="auto",
                cmap="viridis",
                vmin=lower,
                vmax=upper,
            )
            fig.colorbar(image, ax=axes[row, column], label="z (m)")
            axes[row, column].set_title(title)
        positive = residual[residual > 0.0]
        floor = max(float(np.min(positive)) if positive.size else 1.0e-18, 1.0e-18)
        ceiling = max(float(np.max(residual)), floor * 10.0)
        error_image = axes[row, 2].pcolormesh(
            values["x"],
            values["y"],
            np.maximum(residual, floor),
            shading="auto",
            cmap="magma",
            norm=LogNorm(vmin=floor, vmax=ceiling),
        )
        fig.colorbar(error_image, ax=axes[row, 2], label="max face error (m)")
        axes[row, 2].set_title(f"Absolute residual (max {np.max(residual):.2e} m)")
        axes[row, 0].set_ylabel(f"{name}\nsurface y (m)")
        for column in range(3):
            axes[row, column].set_xlabel("surface x (m)")
            axes[row, column].set_aspect("equal", adjustable="box")
    fig.suptitle(
        "Integrated Python fit versus archived MATLAB LOESS surfaces",
        fontsize=15,
        fontweight="bold",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, facecolor="white")
    plt.close(fig)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "docs" / "validation" / "deap-surface-report.json",
    )
    parser.add_argument(
        "--plot",
        type=Path,
        default=ROOT / "docs" / "assets" / "deap-surface-comparison.png",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report, plot_data = validate_examples()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    render_comparison(plot_data, args.plot)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
