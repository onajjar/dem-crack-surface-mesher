"""Benchmark baseline versus Python-interpolated hole runs in Cast3M.

Each case starts from the same CSV inputs and hole parameters.  The baseline
uses its original ``INT_COMP``/``DISPLACE`` section; the optimized case bulk
loads complete Python-generated, radially inflated hole-fill meshes. Outputs
stay under ``_runtime`` and are not committed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import castem_pipeline_gui_t13 as baseline  # noqa: E402
from platform_runtime import castem_command, resolve_castem_exe  # noqa: E402
from python_hole_interpolation import (  # noqa: E402
    build_python_holes_dgibi,
    generated_program_uses_python_holes,
)

INPUTS = {
    "xrange": ROOT / "examples" / "input" / "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    "yrange": ROOT / "examples" / "input" / "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    "zfit_zmax": ROOT / "examples" / "input" / "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    "zfit_zmin": ROOT / "examples" / "input" / "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refinements",
        default="1,2,4",
        help="comma-separated nelem_x/nelem_y values (default: 1,2,4)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "_runtime" / "hole-optimization-benchmark",
        help="isolated output directory",
    )
    parser.add_argument("--clean", action="store_true", help="remove prior benchmark output")
    parser.add_argument(
        "--reuse-baseline",
        action="store_true",
        help="retain verified baseline cases and rerun only optimized cases",
    )
    return parser.parse_args()


def parse_refinements(raw: str) -> tuple[int, ...]:
    try:
        values = tuple(int(value.strip()) for value in raw.split(",") if value.strip())
    except ValueError as exc:
        raise ValueError("--refinements must be comma-separated positive integers.") from exc
    if not values or any(value < 1 for value in values):
        raise ValueError("--refinements must contain at least one positive integer.")
    if len(set(values)) != len(values):
        raise ValueError("--refinements must not contain duplicates.")
    return values


def bdf_card_count(path: Path, card: str) -> int:
    with path.open("r", encoding="utf-8", errors="ignore") as stream:
        return sum(line.startswith(card) for line in stream)


def reused_baseline_case(output: Path, previous: dict[str, object], refinement: int) -> dict[str, object]:
    matches = [
        dict(case)
        for case in previous.get("cases", [])  # type: ignore[union-attr]
        if case.get("mode") == "baseline" and case.get("refinement") == refinement
    ]
    if len(matches) != 1:
        raise RuntimeError(f"No unique recorded baseline case exists for refinement {refinement}.")
    case = matches[0]
    case_dir = output / f"baseline-r{refinement}"
    surface = case_dir / "castem_mesh_surf_min.bdf"
    volume = case_dir / "castem_mesh_v.bdf"
    if not surface.is_file() or not volume.is_file():
        raise FileNotFoundError(f"Baseline BDF outputs are missing for refinement {refinement}.")
    case["surface_quad_count"] = bdf_card_count(surface, "CQUAD4")
    case["volume_hex_count"] = bdf_card_count(volume, "CHEXA")
    case["volume_mesh_exists"] = True
    case["successful"] = case.get("return_code") == 0
    case["reused_from_previous_verified_run"] = True
    return case


def make_params(refinement: int) -> baseline.CastemMainParams:
    return baseline.CastemMainParams(
        re_ti=60,
        re_crpa=1,
        re_smfa=0.05,
        re_numspa=50,
        re_opmin=1.0e-6,
        nelem_x=refinement,
        nelem_y=refinement,
        nelem_z=1,
        num_el_fill=5,
        re_fact_hole=5.0,
        opti_visu=0,
        opti_med=0,
        opti_stl=0,
        holes_enabled=True,
        holes=(baseline.Hole(-0.20, 0.20, 0.07), baseline.Hole(0.20, -0.20, 0.07)),
    )


def stage_csvs(case_dir: Path) -> None:
    expected = {
        "xrange": "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        "yrange": "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        "zfit_zmax": "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        "zfit_zmin": "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    }
    for name, source in INPUTS.items():
        baseline.safe_copy(source, case_dir / expected[name])


def run_case(
    case_dir: Path, mode: str, refinement: int, executable: Path
) -> dict[str, object]:
    case_dir.mkdir(parents=True, exist_ok=False)
    stage_csvs(case_dir)
    params = make_params(refinement)
    template = (ROOT / "source_codes" / "castem_tool.dgibi").read_text(encoding="utf-8")

    interpolation_seconds = 0.0
    points_per_hole: list[int] = []
    hole_fill_nodes: int | None = None
    hole_fill_quads: int | None = None
    radial_fractions: list[float] = []
    if mode == "baseline":
        program = baseline.patch_dgibi_main_program(template, params)
    elif mode == "python":
        started_interpolation = time.perf_counter()
        program, hole_meshes = build_python_holes_dgibi(
            template,
            params,
            INPUTS["xrange"],
            INPUTS["yrange"],
            INPUTS["zfit_zmin"],
            INPUTS["zfit_zmax"],
            baseline.patch_dgibi_main_program,
            hole_mesh_directory=case_dir,
        )
        interpolation_seconds = time.perf_counter() - started_interpolation
        if hole_meshes is None or not generated_program_uses_python_holes(program):
            raise RuntimeError("Python-hole program generation failed validation.")
        points_per_hole = list(hole_meshes.points_per_hole)
        hole_fill_nodes = len(hole_meshes.min_mesh.points)
        hole_fill_quads = len(hole_meshes.min_mesh.quads)
        radial_fractions = [round(float(value), 9) for value in hole_meshes.radial_fractions]
    else:
        raise ValueError(f"Unsupported benchmark mode: {mode}")

    dgibi = case_dir / f"castem_tool_{mode}.dgibi"
    dgibi.write_text(program, encoding="utf-8")
    started_castem = time.perf_counter()
    with (case_dir / "castem-console.log").open("w", encoding="utf-8") as console:
        completed = subprocess.run(
            castem_command(executable, dgibi),
            cwd=case_dir,
            stdout=console,
            stderr=subprocess.STDOUT,
            check=False,
        )
    castem_seconds = time.perf_counter() - started_castem
    volume = case_dir / "castem_mesh_v.bdf"
    surface = case_dir / "castem_mesh_surf_min.bdf"
    successful = completed.returncode == 0 and volume.is_file() and surface.is_file()
    return {
        "mode": mode,
        "refinement": refinement,
        "return_code": completed.returncode,
        "castem_seconds": round(castem_seconds, 6),
        "python_interpolation_seconds": round(interpolation_seconds, 6),
        "points_per_hole": points_per_hole,
        "hole_fill_nodes_per_surface": hole_fill_nodes,
        "hole_fill_quads_per_surface": hole_fill_quads,
        "radial_layer_fractions_outer_to_hole": radial_fractions,
        "volume_mesh_exists": volume.is_file(),
        "surface_quad_count": bdf_card_count(surface, "CQUAD4") if surface.is_file() else None,
        "volume_hex_count": bdf_card_count(volume, "CHEXA") if volume.is_file() else None,
        "successful": successful,
    }


def main() -> int:
    args = parse_args()
    refinements = parse_refinements(args.refinements)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if args.clean and args.reuse_baseline:
        raise ValueError("--clean and --reuse-baseline cannot be used together.")
    if args.clean and output.exists():
        shutil.rmtree(output)
    if output.exists() and any(output.iterdir()) and not args.reuse_baseline:
        raise RuntimeError(f"Output directory is not empty: {output}. Use --clean to reuse it.")
    if missing := [name for name, source in INPUTS.items() if not source.is_file()]:
        raise FileNotFoundError("Missing benchmark input: " + ", ".join(missing))

    output.mkdir(parents=True, exist_ok=True)
    executable = resolve_castem_exe("25")
    previous: dict[str, object] = {}
    if args.reuse_baseline:
        benchmark_path = output / "benchmark.json"
        if not benchmark_path.is_file():
            raise FileNotFoundError("--reuse-baseline requires an existing benchmark.json.")
        previous = json.loads(benchmark_path.read_text(encoding="utf-8"))
    cases: list[dict[str, object]] = []
    for refinement in refinements:
        if args.reuse_baseline:
            baseline_case = reused_baseline_case(output, previous, refinement)
            python_directory = output / f"python-r{refinement}"
            if python_directory.exists():
                shutil.rmtree(python_directory)
        else:
            baseline_case = run_case(output / f"baseline-r{refinement}", "baseline", refinement, executable)
            python_directory = output / f"python-r{refinement}"
        python_case = run_case(python_directory, "python", refinement, executable)
        if not baseline_case["successful"] or not python_case["successful"]:
            cases.extend((baseline_case, python_case))
            break
        baseline_seconds = float(baseline_case["castem_seconds"])
        python_seconds = float(python_case["castem_seconds"])
        python_case["speedup_vs_baseline"] = round(baseline_seconds / python_seconds, 3)
        python_case["same_surface_quad_count"] = (
            baseline_case["surface_quad_count"] == python_case["surface_quad_count"]
        )
        python_case["same_volume_hex_count"] = (
            baseline_case["volume_hex_count"] == python_case["volume_hex_count"]
        )
        cases.extend((baseline_case, python_case))

    report = {"refinements": list(refinements), "cases": cases}
    (output / "benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if cases and all(bool(case["successful"]) for case in cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
