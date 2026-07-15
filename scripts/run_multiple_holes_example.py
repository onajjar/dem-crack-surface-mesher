"""Run the immutable GUI baseline with the documented two-hole parameters.

The application is configured through its Tk variables and executed through
``App._run``.  Every runtime artifact is confined to
``_runtime/multiple-holes-output``; the tracked baseline sources are hashed
before and after the run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "_runtime" / "multiple-holes-output"
MPLCONFIG = OUTPUT / ".mplconfig"
DRIVER_REPORT = OUTPUT / "driver-report.json"
GUI_LOG = OUTPUT / "castem-gui.log"

# Do not create import or plotting caches beside immutable project files.
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["MPLCONFIGDIR"] = str(MPLCONFIG)

sys.path.insert(0, str(ROOT))

import castem_pipeline_gui_t13 as baseline  # noqa: E402

IMMUTABLE_PATHS = [
    ROOT / "bpm_cfx.ico",
    ROOT / "castem_pipeline_gui_t13.py",
    *sorted((ROOT / "source_codes").glob("*")),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def immutable_hashes() -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): sha256(path)
        for path in IMMUTABLE_PATHS
        if path.is_file()
    }


def expected_hashes() -> dict[str, str]:
    manifest = ROOT / "BASELINE_SHA256SUMS"
    parsed: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line.strip())
        if match and (
            match.group(2) in {"bpm_cfx.ico", "castem_pipeline_gui_t13.py"}
            or match.group(2).startswith("source_codes/")
        ):
            parsed[match.group(2)] = match.group(1)
    return parsed


def relative_inventory() -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(OUTPUT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(OUTPUT.rglob("*"))
        if path.is_file() and path not in {DRIVER_REPORT, GUI_LOG}
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute the immutable two-hole example with baseline inputs."
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help=(
            "Delete and recreate the runtime output directory before execution. "
            "Useful for rerunning after a previous generated run."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    existing_run_entries = [
        path for path in OUTPUT.iterdir()
        if path.name != ".mplconfig"
    ] if OUTPUT.exists() else []
    if args.clean and OUTPUT.exists():
        if existing_run_entries:
            shutil.rmtree(OUTPUT)
            existing_run_entries = []
        else:
            OUTPUT.mkdir(parents=True, exist_ok=True)
    if existing_run_entries:
        raise RuntimeError(
            "Refusing to reuse the non-empty isolated runtime directory: "
            "_runtime/multiple-holes-output. Use --clean to remove existing files and rerun."
        )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    MPLCONFIG.mkdir(parents=True, exist_ok=True)

    before = immutable_hashes()
    expected = expected_hashes()
    if before != expected:
        raise RuntimeError("Immutable source hashes do not match BASELINE_SHA256SUMS.")

    required = {
        "dgibi": ROOT / "source_codes" / "castem_tool.dgibi",
        "xrange": ROOT / "examples" / "input" / "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        "yrange": ROOT / "examples" / "input" / "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        "zfit_zmax": ROOT / "examples" / "input" / "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        "zfit_zmin": ROOT / "examples" / "input" / "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing inputs: " + ", ".join(missing))

    state: dict[str, Any] = {
        "command": None,
        "process": None,
        "return_code": None,
        "started": None,
        "finished": None,
        "dialogs": [],
        "failure": None,
    }

    os.chdir(ROOT)
    app = baseline.App()
    app.withdraw()

    original_stream = app._stream_process_to_log

    def stream_wrapper(cmd: list[str], cwd: Path, on_done=None):
        state["command"] = [str(part) for part in cmd]
        process = original_stream(cmd, cwd, on_done=on_done)
        state["process"] = process
        return process

    app._stream_process_to_log = stream_wrapper  # type: ignore[method-assign]

    def record_dialog(kind: str, title: str, message: str) -> None:
        state["dialogs"].append({"kind": kind, "title": title, "message": message})

    # Avoid unattended modal dialogs while retaining their exact content.
    baseline.messagebox.showerror = lambda title, message: record_dialog("error", title, message)
    baseline.messagebox.showwarning = lambda title, message: record_dialog("warning", title, message)
    baseline.messagebox.showinfo = lambda title, message: record_dialog("info", title, message)

    app.dgibi_var.set("source_codes/castem_tool.dgibi")
    app.workdir_var.set("_runtime/multiple-holes-output")
    app.castem_version_var.set("25")
    app.csv_x_var.set("examples/input/xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv")
    app.csv_y_var.set("examples/input/yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv")
    app.csv_zmax_var.set("examples/input/zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv")
    app.csv_zmin_var.set("examples/input/zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv")

    app.re_ti_var.set("60")
    app.re_crpa_var.set("1")
    app.re_smfa_var.set("0.05")
    app.re_numspa_var.set("50")
    app.re_opmin_var.set("1e-6")
    app.nelem_x_var.set("1")
    app.nelem_y_var.set("1")
    app.nelem_z_var.set("1")
    app.num_el_fill_var.set("5")
    app.re_fact_hole_var.set("5.0")
    app.holes_enabled_var.set(True)
    app.opti_med_var.set(False)
    app.opti_stl_var.set(False)
    app.opti_visu_var.set(False)
    app.do_merge_var.set(True)

    app._add_hole_row()
    app._add_hole_row()
    for row, values in zip(
        app.hole_rows,
        (("-0.20", "0.20", "0.07"), ("0.20", "-0.20", "0.07")),
        strict=True,
    ):
        for variable, value in zip(row, values, strict=True):
            variable.set(value)
    app._toggle_holes()

    def start() -> None:
        state["started"] = time.perf_counter()
        try:
            app._run()
        except Exception:
            state["failure"] = traceback.format_exc()
            finish()
            return
        if state.get("process") is None:
            state["failure"] = "GUI validation or launch failed before process creation."
            finish()
            return
        app.after(250, poll)

    def poll() -> None:
        elapsed = time.perf_counter() - float(state["started"] or time.perf_counter())
        process = state.get("process")
        log_text = app.log.get("1.0", "end-1c")
        if process is not None and process.poll() is not None:
            state["return_code"] = process.returncode
            if "===== RUN END" in log_text:
                state["finished"] = time.perf_counter()
                app.after(250, finish)
                return
        if elapsed > 900:
            state["failure"] = "Timed out after 900 seconds."
            if process is not None and process.poll() is None:
                process.terminate()
            finish()
            return
        app.after(250, poll)

    def finish() -> None:
        if state.get("finished") is None:
            state["finished"] = time.perf_counter()
        log_text = app.log.get("1.0", "end-1c")
        GUI_LOG.write_text(log_text, encoding="utf-8")
        after = immutable_hashes()
        elapsed = float(state["finished"]) - float(state["started"] or state["finished"])
        command = state.get("command") or []
        report = {
            "entrypoint": "castem_pipeline_gui_t13.App._run",
            "parameters": {
                "re_ti": 60,
                "re_crpa": 1,
                "re_smfa": 0.05,
                "re_numspa": 50,
                "re_opmin": 1e-6,
                "nelem_x": 1,
                "nelem_y": 1,
                "nelem_z": 1,
                "num_el_fill": 5,
                "re_fact_hole": 5.0,
                "holes_enabled": True,
                "holes": [
                    {"cx": -0.20, "cy": 0.20, "r": 0.07},
                    {"cx": 0.20, "cy": -0.20, "r": 0.07},
                ],
                "opti_med": 0,
                "opti_stl": 0,
                "opti_visu": 0,
                "merge_bdfs": True,
            },
            "execution": {
                "command_form": "cmd.exe /c <resolved-castem-launcher> castem_tool_ti60_crpa1_smfa5_numsp50_opmin1.dgibi"
                if command
                else None,
                "return_code": state.get("return_code"),
                "elapsed_seconds": round(elapsed, 3),
                "dialogs": state["dialogs"],
                "failure": state.get("failure"),
            },
            "immutable_hashes_before": before,
            "immutable_hashes_after": after,
            "immutable_hashes_match": before == after == expected,
            "outputs": relative_inventory(),
        }
        DRIVER_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        app.after(100, app.destroy)

    app.after(100, start)
    app.mainloop()

    report = json.loads(DRIVER_REPORT.read_text(encoding="utf-8"))
    print(json.dumps(report, indent=2))
    execution = report["execution"]
    succeeded = (
        execution["return_code"] == 0
        and execution["failure"] is None
        and report["immutable_hashes_match"]
        and (OUTPUT / "castem_mesh_v.bdf").is_file()
        and (OUTPUT / "combined_ti60_crpa1_smfa5_numsp50_opmin1.bdf").is_file()
    )
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
