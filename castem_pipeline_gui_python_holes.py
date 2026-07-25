"""Compatibility backend for the scientific Cast3M workbench.

The published ``castem_pipeline_gui_t13.py`` baseline remains untouched. New
users should launch ``castem_pipeline_gui_scientific.py``; executing this file
delegates to that same interface for backwards compatibility.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import castem_pipeline_gui_t13 as baseline
from chamber_geometry import (
    CHAMBER_OUTPUT_NAMES,
    chambers_from_params,
    mesh_template_for_params,
    patch_chamber_program,
)
from python_hole_interpolation import build_python_holes_dgibi
from stl_export import (
    active_native_stl_sort_lines,
    comment_native_stl_export,
    export_boundary_bdfs_to_stl,
)

MESH_OUTPUT_PATTERNS = (
    "castem_mesh_*.bdf",
    "castem_mesh_*.med",
    "castem_mesh_*.stl",
    "combined*.bdf",
    "python_hole_fill_*.bdf",
)


def existing_mesh_outputs(workdir: Path) -> tuple[Path, ...]:
    """Return fixed-name mesh artifacts that could contaminate a later run."""

    found: dict[Path, None] = {}
    for pattern in MESH_OUTPUT_PATTERNS:
        for path in workdir.glob(pattern):
            if path.is_file():
                found[path] = None
    return tuple(sorted(found, key=lambda item: item.name.lower()))


def archive_existing_mesh_outputs(workdir: Path, log) -> Path | None:
    """Move prior mesh artifacts aside so a new run cannot merge stale files."""

    artifacts = existing_mesh_outputs(workdir)
    if not artifacts:
        return None
    archive_root = workdir / "_previous_mesh_runs"
    archive_name = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = archive_root / archive_name
    suffix = 1
    while archive.exists():
        archive = archive_root / f"{archive_name}-{suffix}"
        suffix += 1
    archive.mkdir(parents=True)
    for path in artifacts:
        path.replace(archive / path.name)
    log(
        f"Archived {len(artifacts)} previous mesh artifact(s) in "
        f"{archive.relative_to(workdir)}\n"
    )
    return archive


def expected_mesh_output_names(params: baseline.CastemMainParams) -> tuple[str, ...]:
    """List Cast3M BDF outputs required before merge or success reporting."""

    names = [
        "castem_mesh_v.bdf",
        "castem_mesh_surf_min.bdf",
        "castem_mesh_surf_max.bdf",
        "castem_mesh_surf_mean.bdf",
        "castem_mesh_surf_xmin.bdf",
        "castem_mesh_surf_xmax.bdf",
        "castem_mesh_surf_ymin.bdf",
        "castem_mesh_surf_ymax.bdf",
    ]
    if params.holes_enabled:
        names.extend(
            f"castem_mesh_surf_trou_{index}.bdf"
            for index in range(1, len(params.holes) + 1)
        )
    if chambers_from_params(params).enabled:
        names.extend(CHAMBER_OUTPUT_NAMES)
    return tuple(names)


def missing_mesh_outputs(workdir: Path, params: baseline.CastemMainParams) -> tuple[str, ...]:
    return tuple(
        name for name in expected_mesh_output_names(params) if not (workdir / name).is_file()
    )


def patch_mesh_program(template: str, params: baseline.CastemMainParams) -> str:
    """Patch a mesh program and disable Cast3M's fragile native STL writer."""

    program = baseline.patch_dgibi_main_program(template, params)
    program = patch_chamber_program(program, chambers_from_params(params))
    if params.opti_stl:
        program = comment_native_stl_export(program)
        active = active_native_stl_sort_lines(program)
        if active:
            raise RuntimeError(
                "Generated DGIBI still contains active native STL statements: "
                + ", ".join(active)
            )
    return program


class PythonHoleInterpolationApp(baseline.App):
    """The baseline UI with an optimized, hole-only main run implementation."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Cast3M Crack Pipeline — Python Hole Interpolation")

    def _validate_params(self, params: baseline.CastemMainParams) -> None:
        super()._validate_params(params)
        mode = getattr(self, "solver_mode_var", None)
        uses_bulk_holes = params.holes_enabled and (
            mode is None or mode.get() == "python"
        )
        if uses_bulk_holes:
            if params.num_el_fill < 1:
                raise ValueError("num_el_fill must be >= 1")
            if not math.isfinite(params.re_fact_hole) or params.re_fact_hole <= 0.0:
                raise ValueError("re_fact_hole must be a finite value > 0")

    def _run(self) -> None:
        try:
            preview = self._read_params()
            self._validate_params(preview)
            configured_template = Path(self.dgibi_var.get().strip())
            dgibi = mesh_template_for_params(preview, configured_template)
            if not dgibi.exists():
                raise FileNotFoundError("DGIBI template not found.")

            workdir = baseline.ensure_dir(self.workdir_var.get().strip())
            castem_exe = baseline.resolve_castem_exe(self.castem_version_var.get())
            csv_x = Path(self.csv_x_var.get().strip())
            csv_y = Path(self.csv_y_var.get().strip())
            csv_zmax = Path(self.csv_zmax_var.get().strip())
            csv_zmin = Path(self.csv_zmin_var.get().strip())
            for source in (csv_x, csv_y, csv_zmax, csv_zmin):
                if not source.exists():
                    raise FileNotFoundError(f"CSV not found:\n{source}")

            params = preview
            archive_existing_mesh_outputs(workdir, self._log)
            template_text = dgibi.read_text(encoding="utf-8", errors="ignore")
            mode = getattr(self, "solver_mode_var", None)
            uses_python_holes = bool(
                params.holes_enabled
                and params.holes
                and (mode is None or mode.get() == "python")
            )
            if uses_python_holes:
                patched, hole_meshes = build_python_holes_dgibi(
                    template_text,
                    params,
                    csv_x,
                    csv_y,
                    csv_zmin,
                    csv_zmax,
                    patch_mesh_program,
                    hole_mesh_directory=workdir,
                )
                if hole_meshes is None:
                    raise RuntimeError("Python hole interpolation requires at least one hole.")
                mode_suffix = (
                    "_chambers_python_holes"
                    if chambers_from_params(params).enabled
                    else "_python_holes"
                )
            else:
                patched = patch_mesh_program(template_text, params)
                hole_meshes = None
                mode_suffix = (
                    "_chambers"
                    if chambers_from_params(params).enabled
                    else "_reference"
                )
        except Exception as exc:
            baseline.messagebox.showerror("Error", str(exc))
            return

        self._log("\n===== MESH RUN START =====\n")
        self._log(f"Workdir: {workdir}\n")
        if hole_meshes is not None:
            self._log(
                "Python hole boundary points per hole: "
                + ", ".join(str(count) for count in hole_meshes.points_per_hole)
                + "\n"
            )
            self._log(
                f"Bulk hole-fill files: {hole_meshes.min_path.name}, "
                f"{hole_meshes.max_path.name}, {hole_meshes.mean_path.name}\n"
            )
            self._log(
                "Radial layer fractions (outer to hole): "
                + ", ".join(f"{value:.5f}" for value in hole_meshes.radial_fractions)
                + "\n"
            )
        if params.opti_stl:
            self._log(
                "Native Cast3M STL block is commented out; boundary BDF files "
                "will be converted to high-precision ASCII STL by Python.\n"
            )

        names = self._expected_csv_names(params)
        baseline.safe_copy(csv_x, workdir / names["xrange"])
        baseline.safe_copy(csv_y, workdir / names["yrange"])
        baseline.safe_copy(csv_zmax, workdir / names["zfit_zmax"])
        baseline.safe_copy(csv_zmin, workdir / names["zfit_zmin"])

        out_dgibi = workdir / (
            f"{dgibi.stem}{mode_suffix}_ti{params.re_ti}_crpa{params.re_crpa}_"
            f"smfa{params.re_smfa_int}_numsp{params.re_numspa}_opmin{params.re_opmin_int}.dgibi"
        )
        out_dgibi.write_text(patched, encoding="utf-8")
        self._log(f"Generated DGIBI: {out_dgibi.name}\n")

        cmd = ["cmd.exe", "/c", str(castem_exe), str(out_dgibi)]

        def after_castem(return_code: int) -> None:
            if return_code != 0:
                baseline.messagebox.showerror("CASTEM error", f"CASTEM failed, return code {return_code}")
                self._log("===== MESH RUN END (FAILED) =====\n")
                return

            missing = missing_mesh_outputs(workdir, params)
            if missing:
                message = "Cast3M returned 0 but did not create fresh expected outputs: " + ", ".join(missing)
                baseline.messagebox.showerror("Incomplete Cast3M output", message)
                self._log(message + "\n===== MESH RUN END (FAILED) =====\n")
                return

            if params.opti_stl:
                export_boundary_bdfs_to_stl(
                    workdir,
                    hole_count=len(params.holes) if params.holes_enabled else 0,
                    include_chambers=chambers_from_params(params).enabled,
                    log=self._log,
                )

            if self.do_merge_var.get():
                combined = baseline.merge_bdfs(workdir, self._log)
                if combined is not None:
                    named = workdir / (
                        f"combined_ti{params.re_ti}_crpa{params.re_crpa}_smfa{params.re_smfa_int}_"
                        f"numsp{params.re_numspa}_opmin{params.re_opmin_int}.bdf"
                    )
                    if named.exists():
                        named.unlink()
                    combined.replace(named)
                    self._log(f"Final combined: {named.name}\n")

            self._log("===== MESH RUN END =====\n")

        if hole_meshes is not None:
            self._log("Running CASTEM without INT_COMP/DISPLACE...\n")
        else:
            self._log("Running reference Cast3M mesh path...\n")
        return self._stream_process_to_log(cmd, workdir, on_done=after_castem)


def main() -> None:
    from castem_pipeline_gui_scientific import main as scientific_main

    scientific_main()


if __name__ == "__main__":
    main()
