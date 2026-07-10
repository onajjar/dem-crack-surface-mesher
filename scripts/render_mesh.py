"""Render a real Cast3M BDF from an isolated baseline run with PyVista."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BDF = ROOT / "_runtime" / "demo-output" / "castem_mesh_v.bdf"
DEFAULT_OUTPUT = ROOT / "docs" / "assets" / "mesh-preview.png"
ALLOWED_RUNTIMES = (
    ROOT / "_runtime" / "demo-output",
    ROOT / "_runtime" / "multiple-holes-output",
)

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "_runtime" / "mplconfig"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bdf", type=Path, default=DEFAULT_BDF)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--title", default="Real Cast3M volume mesh")
    parser.add_argument("--view", choices=("isometric", "top"), default="isometric")
    args = parser.parse_args()

    bdf = args.bdf.resolve()
    output = args.output.resolve()
    runtimes = tuple(path.resolve() for path in ALLOWED_RUNTIMES)
    if not any(runtime in bdf.parents for runtime in runtimes):
        allowed = ", ".join(path.relative_to(ROOT).as_posix() for path in runtimes)
        raise ValueError(f"Mesh preview input must come from an isolated run: {allowed}")
    if not bdf.is_file():
        raise FileNotFoundError(f"Demo BDF does not exist: {bdf}")

    import meshio
    import pyvista as pv

    mesh = meshio.read(bdf)
    grid = pv.from_meshio(mesh)
    if grid.n_points == 0 or grid.n_cells == 0:
        raise RuntimeError("The generated BDF did not contain renderable mesh cells.")

    surface = grid.extract_surface()
    output.parent.mkdir(parents=True, exist_ok=True)
    plotter = pv.Plotter(off_screen=True, window_size=(1600, 1000))
    plotter.set_background("#f4f7fb")
    plotter.add_mesh(
        surface,
        color="#72a9cf",
        show_edges=True,
        edge_color="#264766",
        line_width=0.35,
        smooth_shading=False,
        ambient=0.35,
        diffuse=0.75,
        specular=0.08,
    )
    plotter.add_text(
        f"{args.title}\n{grid.n_points:,} points · {grid.n_cells:,} cells",
        position="upper_left",
        font_size=17,
        color="#10233f",
    )
    if args.view == "top":
        plotter.view_xy()
        plotter.camera.zoom(1.12)
    else:
        plotter.view_isometric()
        plotter.camera.zoom(1.2)
    plotter.show(screenshot=str(output), auto_close=True)

    from PIL import Image

    dimensions = Image.open(output).size
    print(
        f"Wrote {output} ({dimensions[0]}x{dimensions[1]}, {output.stat().st_size} bytes) "
        f"from {bdf.name}; points={grid.n_points}, cells={grid.n_cells}, surface_cells={surface.n_cells}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
