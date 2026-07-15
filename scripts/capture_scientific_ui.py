"""Capture real, relative-path-only stills and a GIF of the scientific workbench."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESH_ASSET = ROOT / "docs" / "assets" / "scientific-workbench.png"
RUN_ASSET = ROOT / "docs" / "assets" / "scientific-workbench-run-results.png"
DEMO_ASSET = ROOT / "docs" / "assets" / "demo.gif"

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.path.insert(0, str(ROOT))


def main() -> int:
    from PIL import Image, ImageDraw, ImageFont, ImageGrab

    from castem_pipeline_gui_scientific import ScientificApp

    app = ScientificApp()
    # Keep the capture clear of unrelated desktop notifications while retaining
    # a representative, comfortably sized application viewport.
    app.geometry("1400x860+20+30")
    app._load_shape_gallery()
    # Published captures must not expose machine-specific absolute paths.
    app.dgibi_var.set("source_codes/castem_tool.dgibi")
    app.fiss_dgibi_var.set("source_codes/fuite_fissure.dgibi")
    app.workdir_var.set("_runtime/shape-gallery-run")
    app.csv_x_var.set("examples/input/xrange_ti60_crpa1_smfa5_numsp50_opmin1.csv")
    app.csv_y_var.set("examples/input/yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv")
    app.csv_zmax_var.set("examples/input/zfit_zmax_ti60_crpa1_smfa5_numsp50_opmin1.csv")
    app.csv_zmin_var.set("examples/input/zfit_zmin_ti60_crpa1_smfa5_numsp50_opmin1.csv")
    app._validate_inputs(operation="mesh")
    app.notebook.select(app.input_tab)
    app.update_idletasks()
    app.deiconify()
    app.attributes("-topmost", True)
    app.lift()
    app.focus_force()

    def capture() -> None:
        # Process a full paint cycle before desktop capture; update_idletasks
        # alone can capture an incompletely composited Tk window on Windows.
        app.update()
        app.update_idletasks()
        def grab_current_tab() -> Image.Image:
            app.update()
            app.update_idletasks()
            x, y = app.winfo_rootx(), app.winfo_rooty()
            return ImageGrab.grab(
                bbox=(x, y, x + app.winfo_width(), y + app.winfo_height()),
                all_screens=True,
            ).convert("RGB")

        def save_image(image: Image.Image, target: Path) -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, optimize=True)
            print(f"Wrote {target} ({image.width}x{image.height})")

        def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
            for name in ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"):
                if Path(name).is_file():
                    return ImageFont.truetype(name, size=size)
            return ImageFont.load_default()

        def badge(image: Image.Image, label: str, color: str) -> Image.Image:
            result = image.copy()
            draw = ImageDraw.Draw(result)
            label_font = font(22)
            box = draw.textbbox((0, 0), label, font=label_font)
            width = box[2] - box[0] + 34
            height = box[3] - box[1] + 22
            x = result.width - width - 20
            y = 18
            draw.rounded_rectangle(
                (x, y, x + width, y + height),
                radius=12,
                fill=color,
                outline="white",
                width=2,
            )
            draw.text((x + 17, y + 8), label, font=label_font, fill="white")
            return result

        frames: list[Image.Image] = []
        stages = (
            (app.input_tab, "1  GEOMETRY & INPUTS", "#1668a8"),
            (app.mesh_tab, "2  MESH & HOLES", "#0f766e"),
            (app.run_tab, "3  RUN & RESULTS", "#b45309"),
            (app.fiss_tab, "4  FISS FLOW", "#6d4c9a"),
        )
        clean_images: dict[object, Image.Image] = {}
        for tab, label, color in stages:
            app.notebook.select(tab)
            image = grab_current_tab()
            clean_images[tab] = image
            frames.append(badge(image, label, color))

        save_image(clean_images[app.mesh_tab], MESH_ASSET)
        save_image(clean_images[app.run_tab], RUN_ASSET)

        target_width = 1040
        resized = [
            frame.resize(
                (target_width, round(frame.height * target_width / frame.width)),
                Image.Resampling.LANCZOS,
            ).convert("RGB")
            for frame in frames
        ]
        encoded = [
            frame.quantize(
                colors=192,
                method=Image.Quantize.MEDIANCUT,
                dither=Image.Dither.FLOYDSTEINBERG,
            )
            for frame in resized
        ]
        encoded[0].save(
            DEMO_ASSET,
            save_all=True,
            append_images=encoded[1:],
            duration=[1800, 2200, 1900, 1800],
            loop=0,
            optimize=False,
            disposal=2,
        )
        print(
            f"Wrote {DEMO_ASSET} ({encoded[0].width}x{encoded[0].height}, "
            f"{len(encoded)} frames)"
        )
        app.after(100, app.destroy)

    # Allow Windows/Tk enough time to composite every themed widget and the
    # live Canvas schematic before the desktop pixels are sampled.
    app.after(3000, capture)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
