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
from chamber_geometry import (
    ChamberParameters,
    patch_chamber_program,
)
from crack_characterization import (
    CharacterizationConfig,
    SyntheticConfig,
    characterize_surface,
)
from dataset_naming import DatasetNaming, parse_csv_set_metadata
from python_hole_interpolation import (
    HoleGeometry,
    build_python_holes_dgibi,
    detect_hole_rings,
    generated_program_uses_python_holes,
    normalize_hole_geometry,
    parse_hole_spec,
)
from stl_export import (
    active_native_stl_sort_lines,
    comment_native_stl_export,
    export_boundary_bdfs_to_stl,
    export_report,
)
from surface_generation import (
    SUPPORTED_SURFACE_MODES,
    SurfaceGrid,
    SurfaceSource,
    build_surface_grid,
    write_surface_grid,
)

SUPPORTED_OPERATIONS = {
    "mesh",
    "fiss",
    "both",
    "mesh_and_fiss",
    "characterize",
    "characterize_and_mesh",
}
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
    open_gmsh: bool
    mesh_template: Path
    fiss_template: Path
    surface_source: SurfaceSource
    csv_x: Path
    csv_y: Path
    csv_zmin: Path
    csv_zmax: Path
    params: baseline.CastemMainParams
    chambers: ChamberParameters
    fiss: baseline.FissSetup
    characterization_enabled: bool
    characterization_output: Path
    characterization: CharacterizationConfig
    synthetic: SyntheticConfig | None


def _path(base: Path, value: str) -> Path:
    candidate = Path(value.strip()).expanduser()
    return (candidate if candidate.is_absolute() else base / candidate).resolve()


def _number(section, key: str) -> float:
    return baseline.parse_float(section.get(key))


def _optional_number(section, key: str) -> float | None:
    value = section.get(key, fallback="").strip()
    return baseline.parse_float(value) if value else None


def _optional_bounding_box(section, key: str = "bounding_box") -> tuple[float, ...] | None:
    value = section.get(key, fallback="").strip()
    if not value:
        return None
    parts = [part for part in re.split(r"[,\s]+", value) if part]
    if len(parts) != 6:
        raise ValueError(
            "surface bounding_box must contain Xmin, Xmax, Ymin, Ymax, Zmin, Zmax"
        )
    return tuple(baseline.parse_float(part) for part in parts)


def _vector(section, key: str, fallback: str) -> tuple[float, float, float]:
    parts = [
        part
        for part in re.split(r"[,\s]+", section.get(key, fallback=fallback).strip())
        if part
    ]
    if len(parts) != 3:
        raise ValueError(f"{key} must contain three comma- or space-separated components.")
    return tuple(baseline.parse_float(part) for part in parts)


def _formats(section) -> tuple[str, ...]:
    return tuple(
        value.strip().lower()
        for value in section.get("publication_formats", "png").split(",")
        if value.strip()
    )


def _operation_uses_mesh(operation: str) -> bool:
    return operation in {"mesh", "both", "mesh_and_fiss", "characterize_and_mesh"}


def _operation_uses_fiss(operation: str) -> bool:
    return operation in {"fiss", "both", "mesh_and_fiss"}


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


def load_setup(path: Path, *, surface_mode_override: str | None = None) -> HeadlessSetup:
    config_path = path.expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file does not exist: {config_path}")
    parser = ConfigParser(interpolation=None, inline_comment_prefixes=("#", ";"))
    with config_path.open("r", encoding="utf-8-sig") as stream:
        parser.read_file(stream)
    required = {"run", "files", "mesh", "holes", "fiss"}
    missing = sorted(required.difference(parser.sections()))
    if missing:
        raise ValueError("Missing configuration section(s): " + ", ".join(missing))

    run = parser["run"]
    files = parser["files"]
    naming = parser["naming"] if parser.has_section("naming") else None
    mesh = parser["mesh"]
    holes_section = parser["holes"]
    base = config_path.parent
    workdir = _path(base, run.get("working_directory"))
    operation = run.get("operation", "mesh").strip().lower()

    surface_section = parser["surface"] if parser.has_section("surface") else None
    surface_mode = (
        surface_mode_override.strip().lower()
        if surface_mode_override is not None
        else (
            surface_section.get("mode", "csv").strip().lower()
            if surface_section is not None
            else "csv"
        )
    )
    if surface_mode in {"constant_z", "plane", "planar"}:
        surface_mode = "constant"
    if surface_mode in {"fit", "deap_fit", "python_fit"}:
        surface_mode = "deap"
    if surface_mode not in SUPPORTED_SURFACE_MODES:
        raise ValueError("surface mode must be csv, deap, fractal, or constant.")

    if surface_mode == "csv":
        csv_x = _path(base, files.get("x_csv"))
        csv_y = _path(base, files.get("y_csv"))
        csv_zmin = _path(base, files.get("zmin_csv"))
        csv_zmax = _path(base, files.get("zmax_csv"))
        dataset_naming = parse_csv_set_metadata((csv_x, csv_y, csv_zmin, csv_zmax))
        surface_source = SurfaceSource(
            mode="csv",
            csv_x=csv_x,
            csv_y=csv_y,
            csv_zmin=csv_zmin,
            csv_zmax=csv_zmax,
        )
    elif surface_mode == "deap":
        if surface_section is None:
            raise ValueError("DEAP fitting requires a [surface] section.")
        if naming is None:
            raise ValueError("DEAP fitting requires the five values in a [naming] section.")
        dataset_naming = DatasetNaming(
            ti=naming.getint("ti"),
            crpa=naming.getint("crpa"),
            smfa=_number(naming, "smfa"),
            numspa=naming.getint("numspa"),
            opmin=_number(naming, "opmin"),
        )
        generated_directory = workdir / "_generated_surface_inputs"
        csv_x = generated_directory / "xrange_generated.csv"
        csv_y = generated_directory / "yrange_generated.csv"
        csv_zmin = generated_directory / "zfit_zmin_generated.csv"
        csv_zmax = generated_directory / "zfit_zmax_generated.csv"
        surface_source = SurfaceSource(
            mode="deap",
            deap_results_dir=workdir,
            deap_time_step=dataset_naming.ti,
            deap_component=dataset_naming.crpa,
            deap_span=dataset_naming.smfa,
            deap_grid_resolution=dataset_naming.numspa,
            deap_opening_threshold=dataset_naming.opmin,
            deap_orientation=surface_section.get("orientation", "ZX").strip().upper(),
            deap_magnification=baseline.parse_float(
                surface_section.get("magnification", "1.0")
            ),
            deap_bounding_box=_optional_bounding_box(surface_section),
        )
    else:
        if surface_section is None:
            raise ValueError("Generated surface modes require a [surface] section.")
        dataset_naming = DatasetNaming(60, 1, 0.05, 50, 1e-6)
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
        re_ti=dataset_naming.ti,
        re_crpa=dataset_naming.crpa,
        re_smfa=dataset_naming.smfa,
        re_numspa=dataset_naming.numspa,
        re_opmin=dataset_naming.opmin,
        nelem_x=mesh.getint("elements_x"),
        nelem_y=mesh.getint("elements_y"),
        nelem_z=mesh.getint("elements_z"),
        re_tol=_number(mesh, "geometric_tolerance"),
        re_fact_z=_number(mesh, "z_inflation_factor"),
        num_el_fill=mesh.getint("hole_radial_cells"),
        re_fact_hole=_number(mesh, "hole_outer_inner_ratio"),
        opti_visu=0,
        opti_med=int(mesh.getboolean("export_med")),
        opti_stl=int(mesh.getboolean("export_stl")),
        holes_enabled=holes_section.getboolean("enabled"),
        holes=[
            baseline.Hole(hole.cx, hole.cy, hole.selection_radius)
            for _index, hole in holes
        ],
    )
    params.hole_shapes = [hole for _index, hole in holes]
    chambers_section = (
        parser["chambers"] if parser.has_section("chambers") else None
    )
    if chambers_section is None:
        chambers = ChamberParameters()
    else:
        chambers = ChamberParameters(
            enabled=chambers_section.getboolean("enabled", fallback=False),
            height=baseline.parse_float(
                chambers_section.get("height", "0.20")
            ),
            inlet_length=baseline.parse_float(
                chambers_section.get("inlet_length", "0.20")
            ),
            outlet_length=baseline.parse_float(
                chambers_section.get("outlet_length", "0.20")
            ),
            inlet_height_elements=chambers_section.getint(
                "inlet_height_elements", fallback=10
            ),
            outlet_height_elements=chambers_section.getint(
                "outlet_height_elements", fallback=10
            ),
            inlet_length_elements=chambers_section.getint(
                "inlet_length_elements", fallback=10
            ),
            outlet_length_elements=chambers_section.getint(
                "outlet_length_elements", fallback=10
            ),
            inlet_height_ratio=baseline.parse_float(
                chambers_section.get("inlet_height_ratio", "5.0")
            ),
            outlet_height_ratio=baseline.parse_float(
                chambers_section.get("outlet_height_ratio", "5.0")
            ),
            inlet_length_ratio=baseline.parse_float(
                chambers_section.get("inlet_length_ratio", "5.0")
            ),
            outlet_length_ratio=baseline.parse_float(
                chambers_section.get("outlet_length_ratio", "5.0")
            ),
        )
    params.chambers = chambers

    characterization_section = (
        parser["characterization"] if parser.has_section("characterization") else None
    )
    characterization_requested = operation in {"characterize", "characterize_and_mesh"}
    characterization_enabled = (
        characterization_section.getboolean("enabled", fallback=False)
        if characterization_section is not None
        else False
    ) or characterization_requested
    if characterization_section is None:
        characterization = CharacterizationConfig()
        characterization_output = workdir / "characterization"
    else:
        characterization = CharacterizationConfig(
            aperture_method=characterization_section.get(
                "aperture_method", "local_normal"
            ),
            flow_direction=characterization_section.get("flow_direction", "Y"),
            custom_flow_vector=_vector(
                characterization_section,
                "custom_flow_vector",
                "1, 1, 0",
            ),
            tortuosity_direction=characterization_section.get(
                "tortuosity_direction", "flow"
            ),
            custom_tortuosity_vector=_vector(
                characterization_section,
                "custom_tortuosity_vector",
                "1, 1, 0",
            ),
            aperture_cutoff=baseline.parse_float(
                characterization_section.get("aperture_cutoff", "1e-12")
            ),
            allow_negative_aperture=characterization_section.getboolean(
                "allow_negative_aperture", fallback=False
            ),
            interpolate_missing=characterization_section.getboolean(
                "interpolate_missing", fallback=False
            ),
            length_unit=characterization_section.get("length_unit", "m"),
            normal_smoothing_sigma=baseline.parse_float(
                characterization_section.get("normal_smoothing_sigma", "0")
            ),
            hurst_min_lag=characterization_section.getint(
                "hurst_min_lag", fallback=1
            ),
            hurst_max_scale_fraction=baseline.parse_float(
                characterization_section.get("hurst_max_scale_fraction", "0.25")
            ),
            hurst_bootstrap_samples=characterization_section.getint(
                "hurst_bootstrap_samples", fallback=100
            ),
            random_seed=characterization_section.getint(
                "random_seed", fallback=20260723
            ),
            publication_formats=_formats(characterization_section),
            figure_dpi=characterization_section.getint("figure_dpi", fallback=220),
            generate_figures=characterization_section.getboolean(
                "generate_figures", fallback=True
            ),
        )
        characterization_output = _path(
            base,
            characterization_section.get(
                "output_directory",
                str(workdir / "characterization"),
            ),
        )
    characterization.validated()

    synthetic: SyntheticConfig | None = None
    if parser.has_section("synthetic") and parser["synthetic"].getboolean(
        "enabled", fallback=False
    ):
        section = parser["synthetic"]
        synthetic = SyntheticConfig(
            points_x=section.getint("points_x"),
            points_y=section.getint("points_y"),
            size_x=_number(section, "size_x"),
            size_y=_number(section, "size_y"),
            mean_aperture=_number(section, "mean_aperture"),
            aperture_std=_number(section, "aperture_standard_deviation"),
            mid_surface_rms=_number(section, "mid_surface_rms"),
            hurst_x=_number(section, "hurst_x"),
            hurst_y=_number(section, "hurst_y"),
            correlation_length_x=_optional_number(section, "correlation_length_x"),
            correlation_length_y=_optional_number(section, "correlation_length_y"),
            minimum_aperture=baseline.parse_float(
                section.get("minimum_aperture", "0")
            ),
            maximum_aperture=_optional_number(section, "maximum_aperture"),
            contact_fraction=baseline.parse_float(
                section.get("contact_fraction", "0")
            ),
            positive_aperture=section.getboolean(
                "positive_aperture", fallback=True
            ),
            mean_plane_slopes=(
                baseline.parse_float(section.get("mean_plane_slope_x", "0")),
                baseline.parse_float(section.get("mean_plane_slope_y", "0")),
            ),
            random_seed=section.getint("random_seed", fallback=20260723),
            realizations=section.getint("realizations", fallback=1),
        )
        synthetic.validated()

    return HeadlessSetup(
        config_path=config_path,
        operation=operation,
        castem_version=run.get("castem_version", "25").strip(),
        workdir=workdir,
        archive_existing=run.getboolean("archive_existing_outputs", fallback=True),
        mesh_mode=mesh.get("mode", "python").strip().lower(),
        merge_bdfs=mesh.getboolean("merge_bdfs", fallback=True),
        open_gmsh=mesh.getboolean("open_gmsh", fallback=False),
        mesh_template=_path(base, files.get("mesh_template")),
        fiss_template=_path(base, files.get("fiss_template")),
        surface_source=surface_source,
        csv_x=csv_x,
        csv_y=csv_y,
        csv_zmin=csv_zmin,
        csv_zmax=csv_zmax,
        params=params,
        chambers=chambers,
        fiss=_build_fiss(parser["fiss"]),
        characterization_enabled=characterization_enabled,
        characterization_output=characterization_output,
        characterization=characterization,
        synthetic=synthetic,
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
        raise ValueError(
            "operation must be mesh, fiss, both, mesh_and_fiss, characterize, "
            "or characterize_and_mesh."
        )
    if setup.mesh_mode not in SUPPORTED_MESH_MODES:
        raise ValueError("mesh mode must be python or reference.")
    setup.chambers.validated()
    if (
        setup.chambers.enabled
        and _operation_uses_mesh(setup.operation)
        and setup.mesh_mode != "python"
    ):
        raise ValueError("Enabled chambers require mesh mode = python.")
    surface_grid = surface_grid or build_surface_grid(setup.surface_source)
    if _operation_uses_mesh(setup.operation) and not setup.mesh_template.is_file():
        raise FileNotFoundError(f"Mesh DGIBI template does not exist: {setup.mesh_template}")
    if _operation_uses_fiss(setup.operation) and not setup.fiss_template.is_file():
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
        and _operation_uses_fiss(setup.operation)
        and any(hole.shape != "circle" for hole in geometries)
    ):
        raise ValueError("The preserved FISS workflow currently supports circular holes only.")

    points_per_hole: tuple[int, ...] = ()
    if (
        p.holes_enabled
        and setup.mesh_mode == "python"
        and _operation_uses_mesh(setup.operation)
    ):
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
    setup.characterization.validated()
    if setup.operation == "characterize" and not setup.characterization_enabled:
        raise ValueError("Characterize operation requires characterization to be enabled.")
    if check_castem and (
        _operation_uses_mesh(setup.operation) or _operation_uses_fiss(setup.operation)
    ):
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
        if setup.surface_source.normalized_mode == "deap":
            report = {
                "surface_mode": "deap",
                "fit": grid.metadata,
                "generated_files": [path.name for path in actual],
            }
            (setup.csv_x.parent / "deap-fit-report.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
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


def _patch_mesh_program(template: str, params: baseline.CastemMainParams) -> str:
    program = baseline.patch_dgibi_main_program(template, params)
    program = patch_chamber_program(program, getattr(params, "chambers", ChamberParameters()))
    if params.opti_stl:
        program = comment_native_stl_export(program)
        active = active_native_stl_sort_lines(program)
        if active:
            raise RuntimeError(
                "Generated DGIBI still contains active native STL statements: "
                + ", ".join(active)
            )
    return program


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
            _patch_mesh_program,
            hole_mesh_directory=workdir,
        )
        if hole_meshes is None or not generated_program_uses_python_holes(program):
            raise RuntimeError("The conformal Python-hole DGIBI was not generated correctly.")
        mode_suffix = (
            "_chambers_python_holes"
            if setup.chambers.enabled
            else "_python_holes"
        )
    else:
        program = _patch_mesh_program(template, setup.params)
        mode_suffix = "_chambers" if setup.chambers.enabled else "_reference"

    p = setup.params
    dgibi = workdir / (
        f"{setup.mesh_template.stem}{mode_suffix}_ti{p.re_ti}_crpa{p.re_crpa}_"
        f"smfa{p.re_smfa_int}_numsp{p.re_numspa}_opmin{p.re_opmin_int}.dgibi"
    )
    dgibi.write_text(program, encoding="utf-8")
    return_code, elapsed = _run_castem(executable, dgibi, workdir, workdir / "castem-console.log")
    missing = missing_mesh_outputs(workdir, p) if return_code == 0 else ()

    final_bdf: Path | None = None
    stl_exports = ()
    if return_code == 0 and not missing:
        if p.opti_stl:
            stl_exports = export_boundary_bdfs_to_stl(
                workdir,
                hole_count=len(p.holes) if p.holes_enabled else 0,
                include_chambers=setup.chambers.enabled,
                log=lambda message: print(message, end=""),
            )
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

    if setup.open_gmsh and final_bdf is not None and final_bdf.is_file():
        gmsh = baseline.resolve_gmsh_exe()
        subprocess.Popen([str(gmsh), str(final_bdf)], cwd=str(workdir))

    return {
        "return_code": return_code,
        "elapsed_seconds": round(elapsed, 6),
        "mode": setup.mesh_mode,
        "chambers": setup.chambers.report(),
        "surface_mode": setup.surface_source.normalized_mode,
        "surface_grid_points": [surface_grid.shape[1], surface_grid.shape[0]],
        "generated_dgibi": dgibi.name,
        "hole_wall_edges_per_hole": list(hole_meshes.points_per_hole) if hole_meshes else [],
        "square_interface_edges_per_hole": list(hole_meshes.points_per_hole) if hole_meshes else [],
        "interface_counts_match": True if hole_meshes is not None else None,
        "missing_outputs": list(missing),
        "final_bdf": final_bdf.name if final_bdf else None,
        "stl_export": export_report(stl_exports) if p.opti_stl else None,
        "native_cast3m_stl_export": "commented_out" if p.opti_stl else "not_requested",
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
        "--surface-mode",
        choices=(
            "csv",
            "deap",
            "fit",
            "deap_fit",
            "python_fit",
            "fractal",
            "constant",
        ),
        help="override [surface] mode for this run; use deap/fit for Python fitting or csv to bypass fitting",
    )
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
        setup = load_setup(args.config, surface_mode_override=args.surface_mode)
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
            "chambers": setup.chambers.report(),
            "characterization_enabled": setup.characterization_enabled,
            "characterization_output": str(setup.characterization_output),
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
        summary["dataset_naming"] = {
            "source": {
                "csv": "csv_filenames",
                "deap": "deap_inputs",
                "fractal": "generated_surface_defaults",
                "constant": "generated_surface_defaults",
            }[source.normalized_mode],
            "ti": setup.params.re_ti,
            "crpa": setup.params.re_crpa,
            "smfa": setup.params.re_smfa,
            "numspa": setup.params.re_numspa,
            "opmin": setup.params.re_opmin,
        }
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
        elif source.normalized_mode == "deap":
            summary["surface_fit"] = surface_grid.metadata
            summary["surface_files"] = [
                setup.csv_x.name,
                setup.csv_y.name,
                setup.csv_zmin.name,
                setup.csv_zmax.name,
            ]
        else:
            summary["surface_files"] = [
                setup.csv_x.name,
                setup.csv_y.name,
                setup.csv_zmin.name,
                setup.csv_zmax.name,
            ]
        if args.validate_only:
            summary["characterization_configuration"] = {
                "aperture_method": setup.characterization.aperture_method,
                "flow_direction": setup.characterization.flow_direction,
                "length_unit": setup.characterization.length_unit,
                "synthetic_generation": setup.synthetic is not None,
            }
            summary["valid"] = True
            print(json.dumps(summary, indent=2))
            return 0

        if setup.characterization_enabled:
            characterization = characterize_surface(
                surface_grid,
                setup.characterization,
                output_directory=setup.characterization_output,
                synthetic_config=setup.synthetic,
                progress=lambda fraction, message: print(
                    f"[characterization {fraction:5.1%}] {message}"
                ),
            )
            aperture_summary = characterization.summary["aperture"]["statistics"]
            hydraulic_summary = characterization.summary["hydraulic"]
            summary["characterization"] = {
                "success": True,
                "output_directory": str(setup.characterization_output),
                "arithmetic_mean_aperture": aperture_summary["arithmetic_mean"],
                "cubic_mean_aperture": aperture_summary["global_cubic_mean"],
                "equivalent_hydraulic_aperture": hydraulic_summary[
                    "global_equivalent_hydraulic_aperture"
                ],
                "warnings": characterization.warnings,
                "exported_files": {
                    key: str(path)
                    for key, path in characterization.exported_files.items()
                },
            }

        executable = None
        if _operation_uses_mesh(setup.operation) or _operation_uses_fiss(
            setup.operation
        ):
            executable = baseline.resolve_castem_exe(setup.castem_version)
        if _operation_uses_mesh(setup.operation):
            assert executable is not None
            summary["mesh"] = run_mesh(setup, executable, surface_grid)
        if _operation_uses_fiss(setup.operation):
            assert executable is not None
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
            if key in {"characterization", "mesh", "fiss"}
        )
        return 0 if success else 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
