"""Capture a real, relative-path-only screenshot of the scientific workbench."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "docs" / "assets" / "scientific-workbench.png"

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.path.insert(0, str(ROOT))


def main() -> int:
    from PIL import ImageGrab

    from castem_pipeline_gui_scientific import ScientificApp

    app = ScientificApp()
    # Keep the capture clear of unrelated desktop notifications while retaining
    # a representative, comfortably sized application viewport.
    app.geometry("1400x860+20+30")
    app._load_documented_example()
    app.notebook.select(app.mesh_tab)
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
        x, y = app.winfo_rootx(), app.winfo_rooty()
        image = ImageGrab.grab(
            bbox=(x, y, x + app.winfo_width(), y + app.winfo_height()),
            all_screens=True,
        ).convert("RGB")
        ASSET.parent.mkdir(parents=True, exist_ok=True)
        image.save(ASSET, optimize=True)
        print(f"Wrote {ASSET} ({image.width}x{image.height})")
        app.after(100, app.destroy)

    # Allow Windows/Tk enough time to composite every themed widget and the
    # live Canvas schematic before the desktop pixels are sampled.
    app.after(3000, capture)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
