"""Capture an authentic GUI demo while running the staged Cast3M pipeline.

This helper imports the immutable baseline GUI and drives its existing ``_run``
method. Runtime files stay under ``_runtime/`` and published images contain
only relative paths; the live log region is visibly redacted because the GUI
prints resolved local paths there.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "_runtime"
OUTPUT = RUNTIME / "demo-output"
MPLCONFIG = RUNTIME / "mplconfig"
ASSETS = ROOT / "docs" / "assets"

# Keep interpreter and plotting caches away from the immutable baseline files.
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["MPLCONFIGDIR"] = str(MPLCONFIG)

RUNTIME.mkdir(parents=True, exist_ok=True)
MPLCONFIG.mkdir(parents=True, exist_ok=True)
ASSETS.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont, ImageGrab  # noqa: E402

import castem_pipeline_gui_t13 as baseline  # noqa: E402


GUI_SCREENSHOT = ASSETS / "gui-screenshot.png"
DEMO_GIF = ASSETS / "demo.gif"
RUN_LOG = RUNTIME / "castem-gui.log"
RUN_REPORT = RUNTIME / "run-report.json"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = (
        ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"]
        if bold
        else ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"]
    )
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size=size)
    return ImageFont.load_default()


def _grab_window(app: baseline.App) -> Image.Image:
    app.update_idletasks()
    x = app.winfo_rootx()
    y = app.winfo_rooty()
    width = app.winfo_width()
    height = app.winfo_height()
    return ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True).convert("RGB")


def _stage_badge(image: Image.Image, label: str, color: str) -> Image.Image:
    result = image.copy()
    draw = ImageDraw.Draw(result)
    font = _font(22, bold=True)
    bbox = draw.textbbox((0, 0), label, font=font)
    width = bbox[2] - bbox[0] + 34
    height = bbox[3] - bbox[1] + 22
    x = result.width - width - 18
    y = 18
    draw.rounded_rectangle((x, y, x + width, y + height), radius=12, fill=color, outline="white", width=2)
    draw.text((x + 17, y + 8), label, font=font, fill="white")
    return result


def _redact_log(
    image: Image.Image,
    app: baseline.App,
    status: str,
    detail: str,
    color: str,
) -> Image.Image:
    """Visibly replace the log widget because it contains absolute paths."""

    result = image.copy()
    draw = ImageDraw.Draw(result)

    win_x = app.winfo_rootx()
    win_y = app.winfo_rooty()
    ui_width = max(app.winfo_width(), 1)
    ui_height = max(app.winfo_height(), 1)
    scale_x = result.width / ui_width
    scale_y = result.height / ui_height

    left = int((app.log.winfo_rootx() - win_x) * scale_x)
    top = int((app.log.winfo_rooty() - win_y) * scale_y)
    right = int((app.log.winfo_rootx() - win_x + app.log.winfo_width()) * scale_x)
    bottom = int((app.log.winfo_rooty() - win_y + app.log.winfo_height()) * scale_y)

    left = max(8, left)
    top = max(8, top)
    right = min(result.width - 8, right)
    bottom = min(result.height - 8, bottom)

    if right > left and bottom > top:
        draw.rounded_rectangle(
            (left, top, right, bottom),
            radius=12,
            fill="#152238",
            outline="#6f86a5",
            width=2,
        )
        title_font = _font(27, bold=True)
        body_font = _font(19)
        draw.text((left + 24, top + 20), status, font=title_font, fill=color)
        draw.text((left + 24, top + 62), detail, font=body_font, fill="#f1f5fb")
        draw.text(
            (left + 24, bottom - 42),
            "Runtime log visibly redacted: it contains local absolute paths.",
            font=_font(16),
            fill="#aebdd2",
        )
    return result


def _write_gif(frames: list[Image.Image], durations: list[int]) -> None:
    target_width = 1040
    resized_rgb: list[Image.Image] = []
    for frame in frames:
        height = round(frame.height * target_width / frame.width)
        scaled = frame.resize((target_width, height), Image.Resampling.LANCZOS)
        resized_rgb.append(scaled.convert("RGB"))

    # All frames use one explicit opaque palette. This avoids partial-frame
    # transparency/disposal artifacts in GitHub and browser GIF decoders.
    palette = resized_rgb[0].quantize(colors=192, method=Image.Quantize.MEDIANCUT)
    encoded = [
        frame.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
        for frame in resized_rgb
    ]

    encoded[0].save(
        DEMO_GIF,
        save_all=True,
        append_images=encoded[1:],
        duration=durations,
        loop=0,
        optimize=False,
        disposal=1,
    )


def _relative_output_inventory() -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
        }
        for path in sorted(OUTPUT.rglob("*"))
        if path.is_file()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rerun-existing",
        action="store_true",
        help="Allow the baseline workflow to overwrite its own prior isolated demo outputs.",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    if OUTPUT.exists() and any(OUTPUT.iterdir()) and not args.rerun_existing:
        raise RuntimeError(
            f"Refusing to reuse non-empty runtime directory: {OUTPUT}. "
            "Remove it deliberately before rerunning this capture."
        )
    OUTPUT.mkdir(parents=True, exist_ok=True)

    required = [
        ROOT / "source_codes" / "castem_tool.dgibi",
        ROOT / "examples" / "input" / "xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        ROOT / "examples" / "input" / "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        ROOT / "examples" / "input" / "zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv",
        ROOT / "examples" / "input" / "zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing demo inputs: " + ", ".join(missing))

    state: dict[str, Any] = {
        "frames": [],
        "durations": [],
        "command": None,
        "cwd": None,
        "process": None,
        "started": None,
        "finished": None,
        "return_code": None,
        "dialogs": [],
        "running_captures": 0,
        "failure": None,
    }

    app = baseline.App()
    app.geometry("1300x650+40+40")
    app.lift()
    app.attributes("-topmost", True)
    app.focus_force()

    original_stream = app._stream_process_to_log

    def stream_wrapper(cmd: list[str], cwd: Path, on_done=None):
        state["command"] = [str(part) for part in cmd]
        state["cwd"] = str(cwd)
        process = original_stream(cmd, cwd, on_done=on_done)
        state["process"] = process
        return process

    app._stream_process_to_log = stream_wrapper  # type: ignore[method-assign]

    def record_dialog(kind: str, title: str, message: str) -> None:
        state["dialogs"].append({"kind": kind, "title": title, "message": message})

    # Modal dialogs would block unattended evidence capture. Their content is
    # retained in run-report.json instead.
    baseline.messagebox.showerror = lambda title, message: record_dialog("error", title, message)
    baseline.messagebox.showwarning = lambda title, message: record_dialog("warning", title, message)
    baseline.messagebox.showinfo = lambda title, message: record_dialog("info", title, message)

    def capture_blank() -> None:
        app.scroll.canvas.yview_moveto(0.0)
        app.update_idletasks()
        blank = _grab_window(app)
        blank.save(GUI_SCREENSHOT, optimize=True)
        state["frames"].append(_stage_badge(blank, "1  LAUNCH", "#315f9b"))
        state["durations"].append(1500)

        app.dgibi_var.set("source_codes/castem_tool.dgibi")
        app.workdir_var.set("_runtime/demo-output")
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
        app.holes_enabled_var.set(False)
        app.opti_med_var.set(False)
        app.opti_stl_var.set(False)
        app.opti_visu_var.set(False)
        app.do_merge_var.set(True)
        app._toggle_holes()

        app.update_idletasks()
        loaded = _grab_window(app)
        state["frames"].append(_stage_badge(loaded, "2  LOAD RELATIVE INPUTS", "#28796b"))
        state["durations"].append(1800)
        app.after(700, start_run)

    def start_run() -> None:
        app.scroll.canvas.yview_moveto(1.0)
        app.update_idletasks()
        ready = _grab_window(app)
        ready = _redact_log(
            ready,
            app,
            "READY",
            "Staged inputs and baseline parameters are set.",
            "#8bd3ff",
        )
        state["frames"].append(_stage_badge(ready, "3  RUN", "#9a6b19"))
        state["durations"].append(900)

        state["started"] = time.perf_counter()
        try:
            app._run()
        except Exception:
            state["failure"] = traceback.format_exc()
            finalize()
            return
        app.after(900, poll_run)

    def poll_run() -> None:
        process = state.get("process")
        elapsed = time.perf_counter() - float(state["started"] or time.perf_counter())

        if state["running_captures"] < 3:
            live = _grab_window(app)
            live = _redact_log(
                live,
                app,
                "CAST3M RUNNING",
                f"Real baseline execution in isolated runtime · elapsed {elapsed:.1f} s",
                "#ffd166",
            )
            state["frames"].append(_stage_badge(live, "3  RUNNING", "#9a6b19"))
            state["durations"].append(900)
            state["running_captures"] += 1

        log_text = app.log.get("1.0", "end-1c")
        if process is not None and process.poll() is not None:
            state["return_code"] = process.returncode
            if "===== RUN END" in log_text:
                state["finished"] = time.perf_counter()
                # Let Tk repaint after the synchronous BDF merge before the
                # final full-window frame is captured.
                app.after(600, finalize)
                return

        if elapsed > 900:
            state["failure"] = "Timed out after 900 seconds while waiting for the baseline run."
            if process is not None and process.poll() is None:
                process.terminate()
            finalize()
            return

        app.after(1600, poll_run)

    def finalize() -> None:
        if state.get("finished") is None:
            state["finished"] = time.perf_counter()
        elapsed = float(state["finished"]) - float(state["started"] or state["finished"])
        log_text = app.log.get("1.0", "end-1c")
        RUN_LOG.write_text(log_text, encoding="utf-8")

        rc = state.get("return_code")
        final_image = _grab_window(app)
        if rc == 0 and "===== RUN END =====" in log_text:
            final_image = _redact_log(
                final_image,
                app,
                "COMPLETED",
                f"Cast3M returned 0; BDF merge completed in {elapsed:.1f} s.",
                "#72d6a0",
            )
            badge = ("4  COMPLETE", "#28796b")
        else:
            final_image = _redact_log(
                final_image,
                app,
                "RUN STOPPED",
                f"Return code: {rc!r}. See the private runtime report.",
                "#ff8080",
            )
            badge = ("4  STOPPED", "#a63d40")
        state["frames"].append(_stage_badge(final_image, badge[0], badge[1]))
        state["durations"].append(2600)

        _write_gif(state["frames"], state["durations"])

        report = {
            "baseline_entrypoint": "castem_pipeline_gui_t13.App._run",
            "parameters": {
                "re_ti": 60,
                "re_crpa": 1,
                "re_smfa": 0.05,
                "re_numspa": 50,
                "re_opmin": 1e-6,
                "nelem_x": 1,
                "nelem_y": 1,
                "nelem_z": 1,
                "holes_enabled": False,
                "opti_med": 0,
                "opti_stl": 0,
                "opti_visu": 0,
                "merge_bdfs": True,
            },
            "command": state.get("command"),
            "working_directory": state.get("cwd"),
            "return_code": rc,
            "elapsed_seconds": round(elapsed, 3),
            "dialogs": state["dialogs"],
            "failure": state.get("failure"),
            "outputs": _relative_output_inventory(),
            "assets": [
                {
                    "path": GUI_SCREENSHOT.relative_to(ROOT).as_posix(),
                    "bytes": GUI_SCREENSHOT.stat().st_size,
                    "dimensions": list(Image.open(GUI_SCREENSHOT).size),
                },
                {
                    "path": DEMO_GIF.relative_to(ROOT).as_posix(),
                    "bytes": DEMO_GIF.stat().st_size,
                    "dimensions": list(Image.open(DEMO_GIF).size),
                },
            ],
        }
        RUN_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        app.after(300, app.destroy)

    app.after(900, capture_blank)
    app.mainloop()

    report = json.loads(RUN_REPORT.read_text(encoding="utf-8"))
    print(json.dumps(report, indent=2))
    return 0 if report["return_code"] == 0 and report["failure"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
