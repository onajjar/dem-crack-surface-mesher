"""Capture the embedded advanced-characterization tab for documentation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_AUTOMATIC = (
    ROOT / "docs" / "assets" / "advanced-crack-characterization.png"
)
OUTPUT_SYNTHETIC = (
    ROOT / "docs" / "assets" / "advanced-crack-characterization-synthetic.png"
)
OUTPUT_RESULTS = (
    ROOT / "docs" / "assets" / "advanced-crack-characterization-results.png"
)
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.path.insert(0, str(ROOT))


def main() -> int:
    from PIL import ImageGrab

    from castem_pipeline_gui_scientific import ScientificApp

    app = ScientificApp()
    app.geometry("1440x1000+10+10")
    app._load_documented_example(validate=False)
    app.solver_mode_var.set("python_only")
    app._update_method_summary()
    app._validate_inputs(operation="mesh")
    assert app._show_characterization_tab()
    app.deiconify()
    app.update()
    app.attributes("-topmost", True)
    app.lift()
    app.focus_force()

    def grab(path: Path) -> None:
        app.update()
        app.update_idletasks()
        if app.winfo_width() < 1100 or app.winfo_height() < 700:
            raise RuntimeError(
                f"Workbench was not fully mapped: "
                f"{app.winfo_width()}x{app.winfo_height()}"
            )
        x, y = app.winfo_rootx(), app.winfo_rooty()
        image = ImageGrab.grab(
            bbox=(x, y, x + app.winfo_width(), y + app.winfo_height()),
            all_screens=True,
        ).convert("RGB")
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, optimize=True)
        print(f"Wrote {path} ({image.width}x{image.height})")

    def capture() -> None:
        grab(OUTPUT_AUTOMATIC)
        app.characterization_panel.notebook.select(1)
        app.characterization_panel._apply_synthetic_preset("rough")
        app.update()
        grab(OUTPUT_SYNTHETIC)
        app.characterization_panel.notebook.select(2)
        app.update()
        grab(OUTPUT_RESULTS)
        app.destroy()

    app.after(2200, capture)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
