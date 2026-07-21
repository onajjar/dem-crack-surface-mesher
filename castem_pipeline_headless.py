"""Run the scientific Cast3M pipeline from an INI file, without creating a GUI."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path

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
    normalize_hole_geometry,
    parse_hole_spec,
)
from surface_generation import (
    SUPPORTED_SURFACE_MODES,
    SurfaceGrid,
    SurfaceSource,
    build_surface_grid,
    write_surface_grid,
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
    surface_source: SurfaceSource
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


def _optional_number(section, key: str) -> float | None:
    value = section.get(key, fallback="").strip()
    return baseline.parse_float(value) if value else None


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
    workdir = _path(base, run.get("working_directory"))

    surface_section = parser["surface"] if parser.has_section("surface") else None
    surface_mode = (
        surface_section.get("mode", "csv").strip().lower()
        if surface_section is not None
        else "csv"
    )
    if surface_mode in {"constant_z", "plane", "planar"}:
        surface_mode = "constant"
    if surface_mode not in SUPPORTED_SURFACE_MODES:
        raise ValueError("surface mode must be csv, fractal, or constant.")

    if surface_mode == "csv":
        csv_x = _path(base, files.get("x_csv"))
        csv_y = _path(base, files.get("y_csv"))
        csv_zmin = _path(base, files.get("zmin_csv"))
        csv_zmax = _path(base, files.get("zmax_csv"))
        surface_source = SurfaceSource(
            mode="csv",
            csv_x=csv_x,
            csv_y=csv_y,
            csv_zmin=csv_zmin,
            csv_zmax=csv_zmax,
        )
    else:
        if surface_section is None:
            raise ValueError("Generated surface modes require a [surface] section.")
        generated_directory = workdir / "_generated_surface_inputs"
        csv_x = generated_directory / "xrange_generated.csv"
        csv_y = generated_directory / "yrange_generated.csv"
        csv_zmin = generated_directory / "zfit_zmin_generated.csv"
        csv_zmax = generated_directory / "zfit_zmax_generated.csv"
        surface_source = SurfaceSource(
            mode=surface_mode,
            points_x=surface_section.getint("points_x", fallback=50),
            points_y=surface_section.getint("points_y", fallback=50),
            size_x=_number(surface_section, "size_x"),
            size_y=_number(surface_section, "size_y"),
            center_x=baseline.parse_float(surface_section.get("center_x", "0.0")),
            center_y=baseline.parse_float(surface_section.get("center_y", "0.0")),
            hurst_exponent=_optional_number(surface_section, "hurst_exponent"),
            fractal_dimension=_optional_number(surface_section, "fractal_dimension"),
            rms_height=baseline.parse_float(surface_section.get("rms_height", "5e-5")),
            mean_aperture=baseline.parse_float(surface_section.get("mean_aperture", "2e-4")),
            random_seed=surface_section.getint("random_seed", fallback=20260721),
            constant_zmin=baseline.parse_float(surface_section.get("constant_zmin", "0.0")),
            constant_zmax=baseline.parse_float(surface_section.get("constant_zmax", "2e-4")),
        )

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
        workdir=workdir,
        archive_existing=run.getboolean("archive_existing_outputs", fallback=True),
        mesh_mode=mesh.get("mode", "python").strip().lower(),
        merge_bdfs=mesh.getboolean("merge_bdfs", fallback=True),
        mesh_template=_path(base, files.get("mesh_template")),
        fiss_template=_path(base, files.get("fiss_template")),
        surface_source=surface_source,
        csv_x=csv_x,
        csv_y=csv_y,
        csv_zmin=csv_zmin,
        csv_zmax=csv_zmax,
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


def validate_setup(
    setup: HeadlessSetup,
    *,
    check_castem: bool = False,
    surface_grid: SurfaceGrid | None = None,
) -> tuple[int, ...]:
    if setup.operation not in SUPPORTED_OPERATIONS:
        raise ValueError("operation must be mesh, fiss, both, or mesh_and_fiss.")
    if setup.mesh_mode not in SUPPORTED_MESH_MODES:
        raise ValueError("mesh mode must be python or reference.")
    surface_grid = surface_grid or build_surface_grid(setup.surface_source)
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
    if p.holes_enabled and setup.mesh_mode == "reference" and any(
        hole.shape != "circle" for hole in geometries
    ):
        raise ValueError("Rectangle, triangle, and regular-polygon holes require mesh mode = python.")
    if (
        p.holes_enabled
        and setup.operation in {"fiss", "both", "mesh_and_fiss"}
        and any(hole.shape != "circle" for hole in geometries)
    ):
        raise ValueError("The preserved FISS workflow currently supports circular holes only.")

    points_per_hole: tuple[int, ...] = ()
    if p.holes_enabled and setup.mesh_mode == "python":
        rings = detect_hole_rings(
            surface_grid.x,
            surface_grid.y,
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


def _materialize_surface_inputs(
    setup: HeadlessSetup, surface_grid: SurfaceGrid | None = None
) -> SurfaceGrid:
    """Write generated sources once, preserving the downstream CSV contract."""

    grid = surface_grid or build_surface_grid(setup.surface_source)
    if setup.surface_source.normalized_mode != "csv":
        files = write_surface_grid(grid, setup.csv_x.parent)
        expected = (setup.csv_x, setup.csv_y, setup.csv_zmin, setup.csv_zmax)
        actual = (files.x, files.y, files.zmin, files.zmax)
        if actual != expected:
            raise RuntimeError("Generated surface paths do not match the configured runtime paths.")
    return grid


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


def run_mesh(
    setup: HeadlessSetup,
    executable: Path,
    surface_grid: SurfaceGrid | None = None,
) -> dict[str, object]:
    workdir = setup.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    surface_grid = _materialize_surface_inputs(setup, surface_grid)
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
        "surface_mode": setup.surface_source.normalized_mode,
        "surface_grid_points": [surface_grid.shape[1], surface_grid.shape[0]],
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


def run_fiss(
    setup: HeadlessSetup,
    executable: Path,
    surface_grid: SurfaceGrid | None = None,
) -> dict[str, object]:
    _materialize_surface_inputs(setup, surface_grid)
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="INI text file containing every run option")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate configuration, loaded or generated surface geometry, and hole topology without starting Cast3M",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the headless pipeline, optionally with arguments from another launcher."""
    args = parse_args(argv)
    try:
        setup = load_setup(args.config)
        surface_grid = build_surface_grid(setup.surface_source)
        points_per_hole = validate_setup(
            setup,
            check_castem=not args.validate_only,
            surface_grid=surface_grid,
        )
        summary: dict[str, object] = {
            "config": setup.config_path.name,
            "operation": setup.operation,
            "mesh_mode": setup.mesh_mode,
            "surface_mode": setup.surface_source.normalized_mode,
            "workdir": str(setup.workdir),
            "hole_shapes": [
                hole.shape for hole in getattr(setup.params, "hole_shapes", ())
            ],
            "hole_wall_edges_per_hole": list(points_per_hole),
            "square_interface_edges_per_hole": list(points_per_hole),
            "interface_counts_match": True if points_per_hole else None,
        }
        summary["surface_grid_points"] = [surface_grid.shape[1], surface_grid.shape[0]]
        summary["surface_size"] = [
            float(surface_grid.x.max() - surface_grid.x.min()),
            float(surface_grid.y.max() - surface_grid.y.min()),
        ]
        source = setup.surface_source
        if source.normalized_mode == "fractal":
            summary["hurst_exponent"] = round(
                source.resolved_hurst_exponent, 12
            )
            summary["fractal_dimension"] = round(
                source.resolved_fractal_dimension, 12
            )
            summary["surface_parameters"] = {
                "center": [source.center_x, source.center_y],
                "rms_height": source.rms_height,
                "mean_aperture": source.mean_aperture,
                "random_seed": source.random_seed,
            }
        elif source.normalized_mode == "constant":
            summary["surface_parameters"] = {
                "center": [source.center_x, source.center_y],
                "constant_zmin": source.constant_zmin,
                "constant_zmax": source.constant_zmax,
            }
        else:
            summary["surface_files"] = [
                setup.csv_x.name,
                setup.csv_y.name,
                setup.csv_zmin.name,
                setup.csv_zmax.name,
            ]
        if args.validate_only:
            summary["valid"] = True
            print(json.dumps(summary, indent=2))
            return 0

        executable = baseline.resolve_castem_exe(setup.castem_version)
        if setup.operation in {"mesh", "both", "mesh_and_fiss"}:
            summary["mesh"] = run_mesh(setup, executable, surface_grid)
        if setup.operation in {"fiss", "both", "mesh_and_fiss"}:
            mesh_result = summary.get("mesh")
            if isinstance(mesh_result, dict) and not mesh_result.get("success"):
                raise RuntimeError("Mesh run failed; FISS was not started.")
            summary["fiss"] = run_fiss(setup, executable, surface_grid)
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
