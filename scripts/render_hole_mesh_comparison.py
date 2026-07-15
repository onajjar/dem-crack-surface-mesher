"""Render a real reference-versus-scientific Cast3M mesh comparison.

The default inputs are the ``r=1`` volume BDF files created by
``benchmark_hole_optimization.py``.  The image is intentionally generated
from those BDF files at render time: it is not a diagram or a synthetic mesh.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "_runtime" / "hole-optimization-benchmark"
DEFAULT_OUTPUT = ROOT / "docs" / "assets" / "mesh-comparison-baseline-vs-python-holes.png"
DEFAULT_BENCHMARK = RUNTIME / "benchmark.json"

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "_runtime" / "mplconfig"))


@dataclass(frozen=True)
class MeshSummary:
    """Quantities calculated directly from one volume BDF."""

    path: Path
    grid: Any
    surface: Any
    points: int
    hexahedra: int
    max_surface_quads: int


def _max_surface_quad_count(path: Path) -> int:
    """Read the real Cast3M maximum-surface export associated with a volume BDF."""

    import meshio

    surface_bdf = path.with_name("castem_mesh_surf_max.bdf")
    if not surface_bdf.is_file():
        raise FileNotFoundError(f"Associated maximum-surface BDF does not exist: {surface_bdf}")
    surface_mesh = meshio.read(surface_bdf)
    quads = surface_mesh.cells_dict.get("quad")
    if quads is None:
        raise ValueError(f"Expected CQUAD4 cells in maximum-surface BDF: {surface_bdf}")
    return int(len(quads))


def load_volume_mesh(path: Path) -> MeshSummary:
    """Load a BDF and extract the renderable volume boundary."""

    import meshio
    import pyvista as pv

    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Volume BDF does not exist: {path}")

    mesh = meshio.read(path)
    hexahedra = mesh.cells_dict.get("hexahedron")
    if hexahedra is None or len(hexahedra) == 0:
        raise ValueError(f"Expected HEXA8 cells in volume BDF: {path}")

    grid = pv.from_meshio(mesh)
    surface = grid.extract_surface(pass_pointid=False, pass_cellid=False)
    if grid.n_points == 0 or grid.n_cells == 0 or surface.n_cells == 0:
        raise RuntimeError(f"BDF contains no renderable volume mesh: {path}")

    return MeshSummary(
        path=path,
        grid=grid,
        surface=surface,
        points=int(grid.n_points),
        hexahedra=int(len(hexahedra)),
        max_surface_quads=_max_surface_quad_count(path),
    )


def _benchmark_case(data: dict[str, Any], mode: str, refinement: int) -> dict[str, Any] | None:
    for case in data.get("cases", []):
        if case.get("mode") == mode and case.get("refinement") == refinement:
            return case
    return None


def load_benchmark_metrics(path: Path, refinement: int) -> tuple[float | None, float | None, float | None]:
    """Return baseline time, Python time, and reported speed-up if available."""

    if not path.is_file():
        return None, None, None
    data = json.loads(path.read_text(encoding="utf-8"))
    baseline = _benchmark_case(data, "baseline", refinement)
    python = _benchmark_case(data, "python", refinement)
    baseline_seconds = baseline.get("castem_seconds") if baseline else None
    python_seconds = python.get("castem_seconds") if python else None
    speedup = python.get("speedup_vs_baseline") if python else None
    if speedup is None and baseline_seconds and python_seconds:
        speedup = baseline_seconds / python_seconds
    return baseline_seconds, python_seconds, speedup


def _add_panel(
    plotter: Any,
    summary: MeshSummary,
    *,
    row: int,
    column: int,
    view: str,
    color: str,
    label: str,
    timing: float | None,
    focus_xy: tuple[float, float] | None = None,
) -> None:
    """Add one consistently scaled mesh view to the composite plotter."""

    plotter.subplot(row, column)
    plotter.set_background("#f7f9fc")
    plotter.add_mesh(
        summary.surface,
        color=color,
        show_edges=True,
        edge_color="#1d3448",
        line_width=0.45,
        smooth_shading=False,
        ambient=0.42,
        diffuse=0.68,
        specular=0.05,
    )
    lines = [label]
    if view != "detail":
        lines.append(
            f"{summary.points:,} nodes | {summary.hexahedra:,} HEXA8 | "
            f"{summary.max_surface_quads:,} max-surface CQUAD4"
        )
    if timing is not None:
        lines.append(f"Cast3M meshing time: {timing:.3f} s")
    plotter.add_text(
        "\n".join(lines),
        position="upper_left",
        font_size=11,
        color="#ffffff" if view == "detail" else "#152b43",
        shadow=view == "detail",
    )

    if view in {"top", "detail"}:
        plotter.view_xy()
        if view == "detail":
            if focus_xy is None:
                raise ValueError("A detail panel requires focus_xy.")
            old_focus = plotter.camera.focal_point
            old_position = plotter.camera.position
            delta_x = focus_xy[0] - old_focus[0]
            delta_y = focus_xy[1] - old_focus[1]
            plotter.camera.focal_point = (
                old_focus[0] + delta_x,
                old_focus[1] + delta_y,
                old_focus[2],
            )
            plotter.camera.position = (
                old_position[0] + delta_x,
                old_position[1] + delta_y,
                old_position[2],
            )
            plotter.camera.zoom(4.7)
        else:
            plotter.camera.zoom(1.12)
    else:
        plotter.view_isometric()
        plotter.camera.zoom(1.12)
        plotter.add_axes(
            line_width=1.2,
            xlabel="X",
            ylabel="Y",
            zlabel="Z",
            x_color="#b64b3d",
            y_color="#3c985b",
            z_color="#356fae",
        )


def _font(size: int, *, bold: bool = False) -> Any:
    """Find a portable TrueType font through Matplotlib's installed font set."""

    from matplotlib import font_manager
    from PIL import ImageFont

    family = "DejaVu Sans"
    properties = font_manager.FontProperties(family=family, weight="bold" if bold else "normal")
    return ImageFont.truetype(font_manager.findfont(properties), size=size)


def _compose_final_image(
    raw_image: Path,
    output: Path,
    baseline: MeshSummary,
    python: MeshSummary,
    baseline_seconds: float | None,
    python_seconds: float | None,
    speedup: float | None,
    refinement: int,
) -> None:
    """Add a compact scientific header and provenance footer to the VTK image."""

    from PIL import Image, ImageDraw

    panels = Image.open(raw_image).convert("RGB")
    header_height, footer_height = 158, 96
    canvas = Image.new("RGB", (panels.width, panels.height + header_height + footer_height), "#ffffff")
    canvas.paste(panels, (0, header_height))
    draw = ImageDraw.Draw(canvas)

    draw.rectangle((0, 0, canvas.width, header_height), fill="#102b46")
    draw.text((44, 28), "Cast3M volume mesh comparison", font=_font(37, bold=True), fill="#ffffff")
    draw.text(
        (46, 83),
        f"Two-hole geometry | XY refinement r={refinement} | rendered directly from generated BDF volume meshes",
        font=_font(20),
        fill="#d7e6f2",
    )
    draw.rounded_rectangle((canvas.width - 640, 31, canvas.width - 42, 121), radius=14, fill="#173b5d")
    draw.text((canvas.width - 612, 48), "Baseline reference", font=_font(17, bold=True), fill="#f29b7f")
    draw.text((canvas.width - 402, 48), "Scientific bulk", font=_font(17, bold=True), fill="#66c8bf")
    draw.text(
        (canvas.width - 612, 78),
        f"{baseline.hexahedra:,} HEXA8",
        font=_font(18),
        fill="#ffffff",
    )
    draw.text(
        (canvas.width - 402, 78),
        f"{python.hexahedra:,} HEXA8",
        font=_font(18),
        fill="#ffffff",
    )

    footer_top = header_height + panels.height
    draw.rectangle((0, footer_top, canvas.width, canvas.height), fill="#eef3f8")
    same_export_counts = (
        baseline.hexahedra == python.hexahedra
        and baseline.max_surface_quads == python.max_surface_quads
    )
    if same_export_counts:
        equivalence = (
            "Exported cell counts: identical for this run "
            f"({baseline.hexahedra:,} HEXA8; {baseline.max_surface_quads:,} max-surface CQUAD4)."
        )
    else:
        equivalence = (
            "Exported cell counts: reference "
            f"{baseline.hexahedra:,} HEXA8 / {baseline.max_surface_quads:,} CQUAD4; conformal "
            f"{python.hexahedra:,} HEXA8 / {python.max_surface_quads:,} CQUAD4."
        )
    draw.text((44, footer_top + 20), equivalence, font=_font(18, bold=True), fill="#17314a")
    if baseline_seconds is not None and python_seconds is not None and speedup is not None:
        runtime = (
            f"Observed Cast3M time: {baseline_seconds:.3f} s -> {python_seconds:.3f} s "
            f"({speedup:.2f}x speed-up)."
        )
    else:
        runtime = "Timing unavailable: render generated BDF meshes only."
    draw.text((44, footer_top + 53), runtime, font=_font(18), fill="#314c64")
    draw.text(
        (canvas.width - 810, footer_top + 53),
        "Data source: benchmark BDF outputs (not synthetic geometry)",
        font=_font(15),
        fill="#526a7f",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refinement", type=int, default=1, help="Benchmark XY refinement used by the default inputs.")
    parser.add_argument("--baseline", type=Path, help="Baseline volume BDF (defaults to baseline-rN/castem_mesh_v.bdf).")
    parser.add_argument("--python", dest="python_bdf", type=Path, help="Scientific bulk-hole volume BDF (defaults to python-rN/castem_mesh_v.bdf).")
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK, help="Benchmark JSON used only for timing labels.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="PNG comparison output.")
    args = parser.parse_args()

    baseline_path = args.baseline or RUNTIME / f"baseline-r{args.refinement}" / "castem_mesh_v.bdf"
    python_path = args.python_bdf or RUNTIME / f"python-r{args.refinement}" / "castem_mesh_v.bdf"
    output = args.output.resolve()
    raw_output = output.with_name(f".{output.stem}-panels.png")

    baseline = load_volume_mesh(baseline_path)
    python = load_volume_mesh(python_path)
    baseline_seconds, python_seconds, speedup = load_benchmark_metrics(args.benchmark.resolve(), args.refinement)

    import pyvista as pv

    plotter = pv.Plotter(off_screen=True, shape=(3, 2), window_size=(2400, 1900), border=False)
    try:
        _add_panel(
            plotter,
            baseline,
            row=0,
            column=0,
            view="top",
            color="#e58a6d",
            label="A. Baseline reference | top view",
            timing=baseline_seconds,
        )
        _add_panel(
            plotter,
            python,
            row=0,
            column=1,
            view="top",
            color="#55b7ad",
            label="B. Scientific bulk | inflated holes | top view",
            timing=python_seconds,
        )
        _add_panel(
            plotter,
            baseline,
            row=1,
            column=0,
            view="detail",
            color="#e58a6d",
            label="C. Baseline reference | hole 1 detail",
            timing=None,
            focus_xy=(-0.20, 0.20),
        )
        _add_panel(
            plotter,
            python,
            row=1,
            column=1,
            view="detail",
            color="#55b7ad",
            label="D. Scientific bulk | five inflated layers | hole 1 detail",
            timing=None,
            focus_xy=(-0.20, 0.20),
        )
        _add_panel(
            plotter,
            baseline,
            row=2,
            column=0,
            view="isometric",
            color="#e58a6d",
            label="E. Baseline reference | isometric view",
            timing=baseline_seconds,
        )
        _add_panel(
            plotter,
            python,
            row=2,
            column=1,
            view="isometric",
            color="#55b7ad",
            label="F. Scientific bulk | inflated holes | isometric view",
            timing=python_seconds,
        )
        plotter.show(screenshot=str(raw_output), auto_close=False)
    finally:
        plotter.close()

    try:
        _compose_final_image(
            raw_output,
            output,
            baseline,
            python,
            baseline_seconds,
            python_seconds,
            speedup,
            args.refinement,
        )
    finally:
        raw_output.unlink(missing_ok=True)

    from PIL import Image

    dimensions = Image.open(output).size
    print(
        f"Wrote {output} ({dimensions[0]}x{dimensions[1]}, {output.stat().st_size} bytes)\n"
        f"Baseline: nodes={baseline.points}, HEXA8={baseline.hexahedra}, max_surface_quads={baseline.max_surface_quads}\n"
        f"Python:   nodes={python.points}, HEXA8={python.hexahedra}, max_surface_quads={python.max_surface_quads}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
