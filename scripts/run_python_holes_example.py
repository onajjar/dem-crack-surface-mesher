"""Run the documented two-hole example through the Python interpolation path."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import castem_pipeline_gui_t13 as baseline  # noqa: E402
from python_hole_interpolation import (  # noqa: E402
    build_python_holes_dgibi,
    generated_program_uses_python_holes,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove the isolated runtime directory before the run",
    )
    parser.add_argument(
        "--refinement",
        type=int,
        default=1,
        help="use this value for nelem_x and nelem_y (default: 1)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "_runtime" / "python-holes-output",
        help="isolated output directory (default: _runtime/python-holes-output)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.refinement < 1:
        raise ValueError("--refinement must be >= 1")
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if args.clean and output.exists():
        shutil.rmtree(output)
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"Output directory is not empty: {output}. Use --clean to reuse it.")
    output.mkdir(parents=True, exist_ok=True)

    inputs = {
        "xrange": ROOT / "examples" / "input" / "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        "yrange": ROOT / "examples" / "input" / "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        "zfit_zmax": ROOT / "examples" / "input" / "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        "zfit_zmin": ROOT / "examples" / "input" / "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    }
    if missing := [name for name, source in inputs.items() if not source.is_file()]:
        raise FileNotFoundError("Missing example input: " + ", ".join(missing))

    params = baseline.CastemMainParams(
        re_ti=60,
        re_crpa=1,
        re_smfa=0.05,
        re_numspa=50,
        re_opmin=1.0e-6,
        nelem_x=args.refinement,
        nelem_y=args.refinement,
        nelem_z=1,
        num_el_fill=5,
        re_fact_hole=5.0,
        opti_visu=0,
        opti_med=0,
        opti_stl=0,
        holes_enabled=True,
        holes=(baseline.Hole(-0.20, 0.20, 0.07), baseline.Hole(0.20, -0.20, 0.07)),
    )
    names = {
        "xrange": "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        "yrange": "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        "zfit_zmax": "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        "zfit_zmin": "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    }
    for name, source in inputs.items():
        baseline.safe_copy(source, output / names[name])

    started_interpolation = time.perf_counter()
    program, hole_meshes = build_python_holes_dgibi(
        (ROOT / "source_codes" / "castem_tool.dgibi").read_text(encoding="utf-8"),
        params,
        inputs["xrange"],
        inputs["yrange"],
        inputs["zfit_zmin"],
        inputs["zfit_zmax"],
        baseline.patch_dgibi_main_program,
        hole_mesh_directory=output,
    )
    interpolation_seconds = time.perf_counter() - started_interpolation
    if hole_meshes is None or not generated_program_uses_python_holes(program):
        raise RuntimeError("The optimized Python-hole DGIBI was not generated correctly.")

    dgibi = output / "castem_tool_python_holes.dgibi"
    dgibi.write_text(program, encoding="utf-8")
    executable = baseline.resolve_castem_exe("25")
    started_castem = time.perf_counter()
    with (output / "castem-console.log").open("w", encoding="utf-8") as console:
        completed = subprocess.run(
            ["cmd.exe", "/c", str(executable), dgibi.name],
            cwd=output,
            stdout=console,
            stderr=subprocess.STDOUT,
            check=False,
        )
    castem_seconds = time.perf_counter() - started_castem

    report = {
        "return_code": completed.returncode,
        "refinement": args.refinement,
        "python_interpolation_seconds": round(interpolation_seconds, 6),
        "castem_seconds": round(castem_seconds, 6),
        "points_per_hole": list(hole_meshes.points_per_hole),
        "hole_fill_nodes_per_surface": len(hole_meshes.min_mesh.points),
        "hole_fill_quads_per_surface": len(hole_meshes.min_mesh.quads),
        "radial_layer_fractions_outer_to_hole": [
            round(float(value), 9) for value in hole_meshes.radial_fractions
        ],
        "generated_program_has_no_int_comp_or_displace": generated_program_uses_python_holes(program),
        "volume_mesh_exists": (output / "castem_mesh_v.bdf").is_file(),
    }
    (output / "run-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["return_code"] == 0 and report["volume_mesh_exists"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
