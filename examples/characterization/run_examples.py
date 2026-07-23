"""Generate, characterize, and validate the four documented example cases."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crack_characterization import (  # noqa: E402
    CharacterizationConfig,
    SyntheticConfig,
    characterize_surface,
    generate_synthetic_surface,
)
from surface_generation import SurfaceGrid, write_surface_grid  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent


def _load(case: str) -> tuple[Path, dict[str, object]]:
    directory = EXAMPLES / case
    return directory, json.loads(
        (directory / "config.json").read_text(encoding="utf-8")
    )


def _regular_grid(config: dict[str, object]) -> tuple[np.ndarray, np.ndarray]:
    x = np.linspace(0.0, float(config["size_x"]), int(config["points_x"]))
    y = np.linspace(0.0, float(config["size_y"]), int(config["points_y"]))
    return np.meshgrid(x, y)


def _planar(config: dict[str, object]) -> SurfaceGrid:
    x, y = _regular_grid(config)
    aperture = float(config["aperture"])
    return SurfaceGrid(
        x=x,
        y=y,
        zmin=np.full_like(x, -aperture / 2.0),
        zmax=np.full_like(x, aperture / 2.0),
        mode="example_planar_constant",
        metadata={"analytical_reference": True},
    )


def _anisotropic(config: dict[str, object], seed: int | None = None) -> SurfaceGrid:
    return generate_synthetic_surface(
        SyntheticConfig(
            points_x=int(config["points_x"]),
            points_y=int(config["points_y"]),
            size_x=float(config["size_x"]),
            size_y=float(config["size_y"]),
            mean_aperture=float(config["mean_aperture"]),
            aperture_std=float(config["aperture_standard_deviation"]),
            mid_surface_rms=float(config["mid_surface_rms"]),
            hurst_x=float(config["hurst_x"]),
            hurst_y=float(config["hurst_y"]),
            correlation_length_x=float(config["correlation_length_x"]),
            correlation_length_y=float(config["correlation_length_y"]),
            minimum_aperture=float(config["minimum_aperture"]),
            random_seed=int(config["random_seed"] if seed is None else seed),
        )
    )


def _bottleneck(config: dict[str, object]) -> SurfaceGrid:
    x, y = _regular_grid(config)
    aperture = np.full_like(x, float(config["background_aperture"]))
    band = np.abs(x - float(config["bottleneck_x"])) <= 0.5 * float(
        config["bottleneck_width"]
    )
    aperture[band] = float(config["bottleneck_aperture"])
    mid = 1.5e-5 * np.sin(2.0 * np.pi * x / float(config["size_x"]))
    return SurfaceGrid(
        x=x,
        y=y,
        zmin=mid - aperture / 2.0,
        zmax=mid + aperture / 2.0,
        mode="example_hydraulic_bottleneck",
        metadata={"analytical_bottleneck_band": True},
    )


def _characterization_config(config: dict[str, object]) -> CharacterizationConfig:
    return CharacterizationConfig(
        aperture_method=str(config["aperture_method"]),
        flow_direction=str(config["flow_direction"]),
        length_unit=str(config["length_unit"]),
        aperture_cutoff=1.0e-12,
        hurst_bootstrap_samples=50,
        random_seed=int(config["random_seed"]),
        publication_formats=("png", "pdf"),
        figure_dpi=180,
    )


def _reference_payload(result) -> dict[str, object]:
    aperture = result.summary["aperture"]["statistics"]
    hydraulic = result.summary["hydraulic"]
    tortuosity = result.summary["tortuosity"]["mid"]
    return {
        "arithmetic_mean_aperture": aperture["arithmetic_mean"],
        "aperture_standard_deviation": aperture["standard_deviation"],
        "cubic_mean_aperture": aperture["global_cubic_mean"],
        "flow_path_equivalent_aperture": hydraulic[
            "global_equivalent_hydraulic_aperture"
        ],
        "mean_mid_surface_geometrical_tortuosity": tortuosity["mean"],
        "warnings": result.warnings,
    }


def _run_case(
    directory: Path,
    config: dict[str, object],
    grid: SurfaceGrid,
    *,
    synthetic: SyntheticConfig | None = None,
) -> object:
    output = directory / "generated_output"
    write_surface_grid(grid, output / "surface_csv")
    result = characterize_surface(
        grid,
        _characterization_config(config),
        output_directory=output,
        synthetic_config=synthetic,
        progress=lambda fraction, message: print(
            f"[{directory.name} {fraction:5.1%}] {message}"
        ),
    )
    (directory / "expected_results.json").write_text(
        json.dumps(_reference_payload(result), indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(
        output / "aperture_characterization.png",
        directory / "reference_summary.png",
    )
    return result


def main() -> int:
    planar_dir, planar_config = _load("1_planar_constant")
    _run_case(planar_dir, planar_config, _planar(planar_config))

    rough_dir, rough_config = _load("2_anisotropic_rough")
    rough_grid = _anisotropic(rough_config)
    rough_result = _run_case(rough_dir, rough_config, rough_grid)

    bottleneck_dir, bottleneck_config = _load("3_hydraulic_bottleneck")
    _run_case(
        bottleneck_dir,
        bottleneck_config,
        _bottleneck(bottleneck_config),
    )

    synthetic_dir, synthetic_config = _load("4_synthetic_from_characteristics")
    measured_aperture = rough_result.summary["aperture"]["statistics"]
    measured_roughness = rough_result.summary["roughness"]["mid"]
    target = SyntheticConfig(
        points_x=int(synthetic_config["points_x"]),
        points_y=int(synthetic_config["points_y"]),
        size_x=float(rough_config["size_x"]),
        size_y=float(rough_config["size_y"]),
        mean_aperture=float(measured_aperture["arithmetic_mean"]),
        aperture_std=float(measured_aperture["standard_deviation"]),
        mid_surface_rms=float(measured_roughness["root_mean_square_roughness_rq"]),
        hurst_x=float(rough_config["hurst_x"]),
        hurst_y=float(rough_config["hurst_y"]),
        correlation_length_x=float(rough_config["correlation_length_x"]),
        correlation_length_y=float(rough_config["correlation_length_y"]),
        minimum_aperture=float(rough_config["minimum_aperture"]),
        random_seed=int(synthetic_config["random_seed"]),
    )
    synthetic_grid = generate_synthetic_surface(target)
    _run_case(
        synthetic_dir,
        synthetic_config,
        synthetic_grid,
        synthetic=target,
    )
    print("All characterization examples completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
