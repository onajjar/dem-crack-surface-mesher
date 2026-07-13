"""Run the scientific Cast3M pipeline from an INI file, without creating a GUI."""

from __future__ import annotations

import argparse
from configparser import ConfigParser
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

import castem_pipeline_gui_t13 as baseline
from castem_pipeline_gui_python_holes import (
    archive_existing_mesh_outputs,
    existing_mesh_outputs,
    missing_mesh_outputs,
)
from python_hole_interpolation import (
    HoleGeometry,
    build_python_holes_dgibi,
    detect_hole_rings,
    generated_program_uses_python_holes,
    load_surface_csvs,
    normalize_hole_geometry,
    parse_hole_spec,
)


SUPPORTED_OPERATIONS = {"mesh", "fiss", "both", "mesh_and_fiss"}
SUPPORTED_MESH_MODES = {"python", "reference"}
SUPPORTED_FISS_MODELS = {
    "POISEU_BLASIUS",
    "POISEU_COLEBROOK",
    "POISEU_GELAIN_2008",
    "POISEU_GELAIN_2012",
    "POISEU_RIZKALLA",
    "FROTTEMENT1",
    "FROTTEMENT2",
    "FROTTEMENT3",
    "FROTTEMENT4",
}


@dataclass(frozen=True)
class HeadlessSetup:
    config_path: Path
    operation: str
    castem_version: str
    workdir: Path
    archive_existing: bool
    mesh_mode: str
    merge_bdfs: bool
    mesh_template: Path
    fiss_template: Path
    csv_x: Path
    csv_y: Path
    csv_zmin: Path
    csv_zmax: Path
    params: baseline.CastemMainParams
    fiss: baseline.FissSetup


def _path(base: Path, value: str) -> Path:
    candidate = Path(value.strip()).expanduser()
    return (candidate if candidate.is_absolute() else base / candidate).resolve()


def _number(section, key: str) -> float:
    return baseline.parse_float(section.get(key))


def _build_fiss(section) -> baseline.FissSetup:
    model = section.get("model", "POISEU_GELAIN_2012").strip().upper()
    p_mode = section.get("pressure_mode", "range").strip().lower()
    t_mode = section.get("temperature_mode", "range").strip().lower()

    rugo = rec = fk = fa = fb = fc = fd = fk_k = None
    if model == "POISEU_BLASIUS":
        rugo = 0.0
    elif model == "POISEU_COLEBROOK":
        rugo = _number(section, "roughness")
    elif model in {"POISEU_GELAIN_2008", "POISEU_GELAIN_2012", "POISEU_RIZKALLA"}:
        rec = _number(section, "critical_reynolds")
    elif model in {"FROTTEMENT1", "FROTTEMENT2"}:
        rec = _number(section, "critical_reynolds")
        fk = _number(section, "fk")
        fa = _number(section, "fa")
        fb = _number(section, "fb")
        fc = _number(section, "fc")
        fd = _number(section, "fd")
    elif model in {"FROTTEMENT3", "FROTTEMENT4"}:
        rugo = _number(section, "roughness")
        fk_k = _number(section, "fk_k")

    if p_mode == "single":
        p_in = _number(section, "pressure_in")
        p_ini = p_fin = p_step = None
    else:
        p_in = None
        p_ini = _number(section, "pressure_start")
        p_fin = _number(section, "pressure_end")
        p_step = _number(section, "pressure_step")

    if t_mode == "single":
        t_in = _number(section, "temperature_in")
        t_ini = t_fin = t_step = None
    else:
        t_in = None
        t_ini = _number(section, "temperature_start")
        t_fin = _number(section, "temperature_end")
        t_step = _number(section, "temperature_step")

    return baseline.FissSetup(
        model=model,
        gas=section.get("gas", "PARF").strip().upper(),
        cond=section.get("condensation", "MASS").strip().upper(),
        rugo=rugo,
        rec=rec,
        fk=fk,
        fa=fa,
        fb=fb,
        fc=fc,
        fd=fd,
        fk_k=fk_k,
        temp_wall=_number(section, "wall_temperature"),
        p_aval=_number(section, "downstream_pressure"),
        psteam=_number(section, "steam_pressure"),
        num_elem_y=section.getint("line_subdivisions"),
        p_mode=p_mode,
        p_in=p_in,
        p_ini=p_ini,
        p_fin=p_fin,
        p_step=p_step,
        t_mode=t_mode,
        t_in=t_in,
        t_ini=t_ini,
        t_fin=t_fin,
        t_step=t_step,
    )


def load_setup(path: Path) -> HeadlessSetup:
    config_path = path.expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file does not exist: {config_path}")
    parser = ConfigParser(interpolation=None, inline_comment_prefixes=("#", ";"))
    with config_path.open("r", encoding="utf-8-sig") as stream:
        parser.read_file(stream)
    required = {"run", "files", "naming", "mesh", "holes", "fiss"}
    missing = sorted(required.difference(parser.sections()))
    if missing:
        raise ValueError("Missing configuration section(s): " + ", ".join(missing))

    run = parser["run"]
    files = parser["files"]
    naming = parser["naming"]
    mesh = parser["mesh"]
    holes_section = parser["holes"]
    base = config_path.parent

    holes: list[tuple[int, HoleGeometry]] = []
    for key, value in holes_section.items():
        match = re.fullmatch(r"hole(\d+)", key.strip(), flags=re.IGNORECASE)
        if not match:
            continue
        hole_index = int(match.group(1))
        holes.append((hole_index, parse_hole_spec(value, hole_index)))
    holes.sort(key=lambda item: item[0])

    params = baseline.CastemMainParams(
        re_ti=naming.getint("ti"),
        re_crpa=naming.getint("crpa"),
        re_smfa=_number(naming, "smfa"),
        re_numspa=naming.getint("numspa"),
        re_opmin=_number(naming, "opmin"),
        nelem_x=mesh.getint("elements_x"),
        nelem_y=mesh.getint("elements_y"),
        nelem_z=mesh.getint("elements_z"),
        re_tol=_number(mesh, "geometric_tolerance"),
        re_fact_z=_number(mesh, "z_inflation_factor"),
        num_el_fill=mesh.getint("hole_radial_cells"),
        re_fact_hole=_number(mesh, "hole_outer_inner_ratio"),
        opti_visu=int(mesh.getboolean("open_gmsh")),
        opti_med=int(mesh.getboolean("export_med")),
        opti_stl=int(mesh.getboolean("export_stl")),
        holes_enabled=holes_section.getboolean("enabled"),
        holes=[
            baseline.Hole(hole.cx, hole.cy, hole.selection_radius)
            for _index, hole in holes
        ],
    )
    params.hole_shapes = [hole for _index, hole in holes]

    return HeadlessSetup(
        config_path=config_path,
        operation=run.get("operation", "mesh").strip().lower(),
        castem_version=run.get("castem_version", "25").strip(),
        workdir=_path(base, run.get("working_directory")),
        archive_existing=run.getboolean("archive_existing_outputs", fallback=True),
        mesh_mode=mesh.get("mode", "python").strip().lower(),
        merge_bdfs=mesh.getboolean("merge_bdfs", fallback=True),
        mesh_template=_path(base, files.get("mesh_template")),
        fiss_template=_path(base, files.get("fiss_template")),
        csv_x=_path(base, files.get("x_csv")),
        csv_y=_path(base, files.get("y_csv")),
        csv_zmin=_path(base, files.get("zmin_csv")),
        csv_zmax=_path(base, files.get("zmax_csv")),
        params=params,
        fiss=_build_fiss(parser["fiss"]),
    )


def _validate_fiss(fiss: baseline.FissSetup) -> None:
    if fiss.model not in SUPPORTED_FISS_MODELS:
        raise ValueError(f"Unsupported FISS model: {fiss.model}")
    if fiss.gas not in {"PARF", "REEL"}:
        raise ValueError("FISS gas must be PARF or REEL.")
    if fiss.cond not in {"MASS", "FILM"}:
        raise ValueError("FISS condensation must be MASS or FILM.")
    if fiss.p_mode not in {"single", "range"} or fiss.t_mode not in {"single", "range"}:
        raise ValueError("FISS pressure_mode and temperature_mode must be single or range.")
    if fiss.num_elem_y < 1:
        raise ValueError("FISS line_subdivisions must be >= 1.")
    if fiss.p_mode == "range" and (fiss.p_step is None or fiss.p_step <= 0):
        raise ValueError("FISS pressure_step must be > 0 in range mode.")
    if fiss.t_mode == "range" and (fiss.t_step is None or fiss.t_step <= 0):
        raise ValueError("FISS temperature_step must be > 0 in range mode.")


def validate_setup(setup: HeadlessSetup, *, check_castem: bool = False) -> tuple[int, ...]:
    if setup.operation not in SUPPORTED_OPERATIONS:
        raise ValueError("operation must be mesh, fiss, both, or mesh_and_fiss.")
    if setup.mesh_mode not in SUPPORTED_MESH_MODES:
        raise ValueError("mesh mode must be python or reference.")
    for source in (setup.csv_x, setup.csv_y, setup.csv_zmin, setup.csv_zmax):
        if not source.is_file():
            raise FileNotFoundError(f"CSV input does not exist: {source}")
    if setup.operation in {"mesh", "both", "mesh_and_fiss"} and not setup.mesh_template.is_file():
        raise FileNotFoundError(f"Mesh DGIBI template does not exist: {setup.mesh_template}")
    if setup.operation in {"fiss", "both", "mesh_and_fiss"} and not setup.fiss_template.is_file():
        raise FileNotFoundError(f"FISS DGIBI template does not exist: {setup.fiss_template}")

    p = setup.params
    if p.re_smfa <= 0 or p.re_opmin < 0 or p.re_tol <= 0:
        raise ValueError("smfa and geometric_tolerance must be > 0; opmin must be >= 0.")
    if min(p.nelem_x, p.nelem_y, p.nelem_z, p.num_el_fill) < 1:
        raise ValueError("mesh element counts and hole_radial_cells must be >= 1.")
    if not math.isfinite(p.re_fact_z) or p.re_fact_z <= 0:
        raise ValueError("z_inflation_factor must be finite and > 0.")
    if not math.isfinite(p.re_fact_hole) or p.re_fact_hole <= 0:
        raise ValueError("hole_outer_inner_ratio must be finite and > 0.")
    if p.holes_enabled and not p.holes:
        raise ValueError("At least one holeN entry is required when holes are enabled.")
    geometries = tuple(
        normalize_hole_geometry(hole, index)
        for index, hole in enumerate(getattr(p, "hole_shapes", p.holes), start=1)
    )
    if setup.mesh_mode == "reference" and any(hole.shape != "circle" for hole in geometries):
        raise ValueError("Rectangle, triangle, and regular-polygon holes require mesh mode = python.")
    if setup.operation in {"fiss", "both", "mesh_and_fiss"} and any(
        hole.shape != "circle" for hole in geometries
    ):
        raise ValueError("The preserved FISS workflow currently supports circular holes only.")

    points_per_hole: tuple[int, ...] = ()
    if p.holes_enabled and setup.mesh_mode == "python":
        x, y, _zmin, _zmax = load_surface_csvs(
            setup.csv_x, setup.csv_y, setup.csv_zmin, setup.csv_zmax
        )
        rings = detect_hole_rings(
            x,
            y,
            geometries,
            tolerance=p.re_tol,
            nelem_x=p.nelem_x,
            nelem_y=p.nelem_y,
        )
        if any(len(ring.outer_xy) != len(ring.xy) for ring in rings):
            raise RuntimeError("Hole-wall and square-interface edge counts are not conformal.")
        points_per_hole = tuple(len(ring.xy) for ring in rings)
    _validate_fiss(setup.fiss)
    if check_castem:
        baseline.resolve_castem_exe(setup.castem_version)
    return points_per_hole


def _csv_names(p: baseline.CastemMainParams) -> dict[str, str]:
    stem = f"ti{p.re_ti}_crpa{p.re_crpa}_smfa{p.re_smfa_int}_numsp{p.re_numspa}_opmin{p.re_opmin_int}"
    return {
        "x": f"xrange_{stem}.csv",
        "y": f"yrange_{stem}.csv",
        "zmin": f"zfit_zmin_{stem}.csv",
        "zmax": f"zfit_zmax_{stem}.csv",
    }


def _copy_csv_inputs(setup: HeadlessSetup, destination: Path) -> None:
    names = _csv_names(setup.params)
    for source, name in (
        (setup.csv_x, names["x"]),
        (setup.csv_y, names["y"]),
        (setup.csv_zmin, names["zmin"]),
        (setup.csv_zmax, names["zmax"]),
    ):
        baseline.safe_copy(source, destination / name)


def _run_castem(executable: Path, dgibi: Path, cwd: Path, log_path: Path) -> tuple[int, float]:
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            ["cmd.exe", "/c", str(executable), dgibi.name],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            console_encoding = sys.stdout.encoding or "utf-8"
            safe_line = line.encode(console_encoding, errors="replace").decode(console_encoding)
            sys.stdout.write(safe_line)
            sys.stdout.flush()
        return process.wait(), time.perf_counter() - started


def _combined_name(p: baseline.CastemMainParams) -> str:
    return (
        f"combined_ti{p.re_ti}_crpa{p.re_crpa}_smfa{p.re_smfa_int}_"
        f"numsp{p.re_numspa}_opmin{p.re_opmin_int}.bdf"
    )


def run_mesh(setup: HeadlessSetup, executable: Path) -> dict[str, object]:
    workdir = setup.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    prior = existing_mesh_outputs(workdir)
    if prior and not setup.archive_existing:
        raise RuntimeError("Existing mesh outputs found; enable archive_existing_outputs or select another workdir.")
    if prior:
        archive_existing_mesh_outputs(workdir, lambda message: print(message, end=""))
    _copy_csv_inputs(setup, workdir)

    template = setup.mesh_template.read_text(encoding="utf-8", errors="ignore")
    hole_meshes = None
    if setup.mesh_mode == "python" and setup.params.holes_enabled:
        program, hole_meshes = build_python_holes_dgibi(
            template,
            setup.params,
            setup.csv_x,
            setup.csv_y,
            setup.csv_zmin,
            setup.csv_zmax,
            baseline.patch_dgibi_main_program,
            hole_mesh_directory=workdir,
        )
        if hole_meshes is None or not generated_program_uses_python_holes(program):
            raise RuntimeError("The conformal Python-hole DGIBI was not generated correctly.")
        mode_suffix = "_python_holes"
    else:
        program = baseline.patch_dgibi_main_program(template, setup.params)
        mode_suffix = "_reference"

    p = setup.params
    dgibi = workdir / (
        f"{setup.mesh_template.stem}{mode_suffix}_ti{p.re_ti}_crpa{p.re_crpa}_"
        f"smfa{p.re_smfa_int}_numsp{p.re_numspa}_opmin{p.re_opmin_int}.dgibi"
    )
    dgibi.write_text(program, encoding="utf-8")
    return_code, elapsed = _run_castem(executable, dgibi, workdir, workdir / "castem-console.log")
    missing = missing_mesh_outputs(workdir, p) if return_code == 0 else ()

    final_bdf: Path | None = None
    if return_code == 0 and not missing:
        if setup.merge_bdfs:
            combined = baseline.merge_bdfs(workdir, lambda message: print(message, end=""))
            if combined is not None:
                final_bdf = workdir / _combined_name(p)
                if final_bdf.exists() and final_bdf != combined:
                    final_bdf.unlink()
                if final_bdf != combined:
                    combined.replace(final_bdf)
        else:
            volume = workdir / "castem_mesh_v.bdf"
            final_bdf = volume if volume.is_file() else None

    if p.opti_visu and final_bdf is not None and final_bdf.is_file():
        gmsh = baseline.resolve_gmsh_exe()
        subprocess.Popen([str(gmsh), str(final_bdf)], cwd=str(workdir))

    return {
        "return_code": return_code,
        "elapsed_seconds": round(elapsed, 6),
        "mode": setup.mesh_mode,
        "generated_dgibi": dgibi.name,
        "hole_wall_edges_per_hole": list(hole_meshes.points_per_hole) if hole_meshes else [],
        "square_interface_edges_per_hole": list(hole_meshes.points_per_hole) if hole_meshes else [],
        "interface_counts_match": True if hole_meshes is not None else None,
        "missing_outputs": list(missing),
        "final_bdf": final_bdf.name if final_bdf else None,
        "success": return_code == 0 and not missing and final_bdf is not None,
    }


def _next_calculation_directory(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    indices = []
    for path in base.glob("Calcul*"):
        match = re.fullmatch(r"Calcul(\d+)", path.name) if path.is_dir() else None
        if match:
            indices.append(int(match.group(1)))
    result = base / f"Calcul{max(indices, default=0) + 1}"
    result.mkdir()
    return result


def run_fiss(setup: HeadlessSetup, executable: Path) -> dict[str, object]:
    calculation = _next_calculation_directory(setup.workdir / setup.fiss.model)
    _copy_csv_inputs(setup, calculation)
    template = setup.fiss_template.read_text(encoding="utf-8", errors="ignore")
    program = baseline.patch_dgibi_main_program(template, setup.params)
    program = baseline.App._patch_fiss_vars(None, program, setup.fiss)
    p = setup.params
    dgibi = calculation / (
        f"{setup.fiss_template.stem}_{setup.fiss.model}_ti{p.re_ti}_crpa{p.re_crpa}_"
        f"smfa{p.re_smfa_int}_numsp{p.re_numspa}_opmin{p.re_opmin_int}.dgibi"
    )
    dgibi.write_text(program, encoding="utf-8")
    return_code, elapsed = _run_castem(executable, dgibi, calculation, calculation / "castem-console.log")
    return {
        "return_code": return_code,
        "elapsed_seconds": round(elapsed, 6),
        "model": setup.fiss.model,
        "calculation_directory": str(calculation.relative_to(setup.workdir)),
        "generated_dgibi": dgibi.name,
        "success": return_code == 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="INI text file containing every run option")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate configuration, CSV geometry, and hole topology without starting Cast3M",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        setup = load_setup(args.config)
        points_per_hole = validate_setup(setup, check_castem=not args.validate_only)
        summary: dict[str, object] = {
            "config": setup.config_path.name,
            "operation": setup.operation,
            "mesh_mode": setup.mesh_mode,
            "workdir": str(setup.workdir),
            "hole_shapes": [
                hole.shape for hole in getattr(setup.params, "hole_shapes", ())
            ],
            "hole_wall_edges_per_hole": list(points_per_hole),
            "square_interface_edges_per_hole": list(points_per_hole),
            "interface_counts_match": True if points_per_hole else None,
        }
        if args.validate_only:
            summary["valid"] = True
            print(json.dumps(summary, indent=2))
            return 0

        executable = baseline.resolve_castem_exe(setup.castem_version)
        if setup.operation in {"mesh", "both", "mesh_and_fiss"}:
            summary["mesh"] = run_mesh(setup, executable)
        if setup.operation in {"fiss", "both", "mesh_and_fiss"}:
            mesh_result = summary.get("mesh")
            if isinstance(mesh_result, dict) and not mesh_result.get("success"):
                raise RuntimeError("Mesh run failed; FISS was not started.")
            summary["fiss"] = run_fiss(setup, executable)
        setup.workdir.mkdir(parents=True, exist_ok=True)
        report = setup.workdir / "headless-run-report.json"
        report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2))
        success = all(
            not isinstance(value, dict) or value.get("success", True)
            for key, value in summary.items()
            if key in {"mesh", "fiss"}
        )
        return 0 if success else 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
