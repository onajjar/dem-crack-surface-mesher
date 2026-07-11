"""Compatibility backend for the scientific Cast3M workbench.

The published ``castem_pipeline_gui_t13.py`` baseline remains untouched. New
users should launch ``castem_pipeline_gui_scientific.py``; executing this file
delegates to that same interface for backwards compatibility.
"""

from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
import subprocess

import castem_pipeline_gui_t13 as baseline
from python_hole_interpolation import build_python_holes_dgibi


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
    return tuple(names)


def missing_mesh_outputs(workdir: Path, params: baseline.CastemMainParams) -> tuple[str, ...]:
    return tuple(
        name for name in expected_mesh_output_names(params) if not (workdir / name).is_file()
    )


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
        # Preserve the exact baseline implementation for no-hole runs.
        try:
            preview = self._read_params()
            self._validate_params(preview)
        except Exception as exc:
            baseline.messagebox.showerror("Error", str(exc))
            return
        if not preview.holes_enabled or not preview.holes:
            super()._run()
            return

        try:
            dgibi = Path(self.dgibi_var.get().strip())
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
            patched, hole_meshes = build_python_holes_dgibi(
                template_text,
                params,
                csv_x,
                csv_y,
                csv_zmin,
                csv_zmax,
                baseline.patch_dgibi_main_program,
                hole_mesh_directory=workdir,
            )
            if hole_meshes is None:
                raise RuntimeError("Python hole interpolation requires at least one hole.")
        except Exception as exc:
            baseline.messagebox.showerror("Error", str(exc))
            return

        self._log("\n===== PYTHON-HOLE RUN START =====\n")
        self._log(f"Workdir: {workdir}\n")
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

        names = self._expected_csv_names(params)
        baseline.safe_copy(csv_x, workdir / names["xrange"])
        baseline.safe_copy(csv_y, workdir / names["yrange"])
        baseline.safe_copy(csv_zmax, workdir / names["zfit_zmax"])
        baseline.safe_copy(csv_zmin, workdir / names["zfit_zmin"])

        out_dgibi = workdir / (
            f"{dgibi.stem}_python_holes_ti{params.re_ti}_crpa{params.re_crpa}_"
            f"smfa{params.re_smfa_int}_numsp{params.re_numspa}_opmin{params.re_opmin_int}.dgibi"
        )
        out_dgibi.write_text(patched, encoding="utf-8")
        self._log(f"Generated optimized DGIBI: {out_dgibi.name}\n")

        cmd = ["cmd.exe", "/c", str(castem_exe), str(out_dgibi)]

        def after_castem(return_code: int) -> None:
            if return_code != 0:
                baseline.messagebox.showerror("CASTEM error", f"CASTEM failed, return code {return_code}")
                self._log("===== PYTHON-HOLE RUN END (FAILED) =====\n")
                return

            missing = missing_mesh_outputs(workdir, params)
            if missing:
                message = "Cast3M returned 0 but did not create fresh expected outputs: " + ", ".join(missing)
                baseline.messagebox.showerror("Incomplete Cast3M output", message)
                self._log(message + "\n===== PYTHON-HOLE RUN END (FAILED) =====\n")
                return

            final_bdf = None
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
                    final_bdf = named
                    self._log(f"Final combined: {named.name}\n")
            else:
                volume = workdir / "castem_mesh_v.bdf"
                if volume.exists():
                    final_bdf = volume

            if params.opti_visu == 1 and final_bdf and final_bdf.exists():
                try:
                    gmsh_exe = baseline.resolve_gmsh_exe()
                    self._log(f"Opening in Gmsh: {final_bdf.name}\n")
                    subprocess.Popen([str(gmsh_exe), str(final_bdf)], cwd=str(workdir))
                except Exception as exc:
                    baseline.messagebox.showwarning("Gmsh", str(exc))
            self._log("===== PYTHON-HOLE RUN END =====\n")

        self._log("Running CASTEM without INT_COMP/DISPLACE...\n")
        return self._stream_process_to_log(cmd, workdir, on_done=after_castem)


def main() -> None:
    from castem_pipeline_gui_scientific import main as scientific_main

    scientific_main()


if __name__ == "__main__":
    main()
