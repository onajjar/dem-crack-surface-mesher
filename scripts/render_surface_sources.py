"""Render the documented generated surfaces from their real configurations."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from castem_pipeline_headless import load_setup  # noqa: E402
from surface_generation import build_surface_grid  # noqa: E402

OUTPUT = ROOT / "docs" / "assets" / "synthetic-surface-comparison.png"


def main() -> int:
    cases = (
        (
            "Legacy isotropic fractal",
            ROOT / "examples" / "surfaces" / "fractal-hurst.ini",
            "H = 0.8, D = 2.2, RMS = 50 µm, seed = 20260721",
        ),
        (
            "Advanced opposing walls",
            ROOT / "examples" / "surfaces" / "fractal-advanced.ini",
            "Hx = 0.85, Hy = 0.55, lognormal, wall correlation = 0",
        ),
        (
            "Constant-Z walls",
            ROOT / "examples" / "surfaces" / "constant-planes.ini",
            "zmin = 0 µm, zmax = 200 µm",
        ),
    )
    figure = plt.figure(figsize=(18, 6.8), dpi=150, facecolor="#f4f7fb")
    for index, (title, config, subtitle) in enumerate(cases, start=1):
        setup = load_setup(config)
        grid = build_surface_grid(setup.surface_source)
        axes = figure.add_subplot(1, len(cases), index, projection="3d")
        axes.plot_surface(
            grid.x,
            grid.y,
            grid.zmin * 1.0e6,
            cmap="Blues",
            linewidth=0,
            antialiased=True,
            alpha=0.88,
        )
        axes.plot_surface(
            grid.x,
            grid.y,
            grid.zmax * 1.0e6,
            cmap="Oranges",
            linewidth=0,
            antialiased=True,
            alpha=0.65,
        )
        axes.set_title(f"{title}\n{subtitle}", color="#10233f", pad=8, weight="bold")
        axes.set_xlabel("X")
        axes.set_ylabel("Y")
        axes.set_zlabel("Z (µm)")
        axes.view_init(elev=28, azim=-56)
        axes.grid(True, alpha=0.22)
        axes.set_box_aspect((1.2, 0.9, 0.42))
    figure.suptitle(
        "Generated crack-wall sources used by the documented examples",
        fontsize=18,
        color="#0f2742",
        weight="bold",
        y=0.98,
    )
    figure.text(
        0.5,
        0.02,
        "Blue: lower wall   •   Orange: upper wall   •   Advanced case: directional roll-off and variable aperture",
        ha="center",
        color="#5d6d82",
        fontsize=11,
    )
    figure.subplots_adjust(left=0.01, right=0.99, top=0.78, bottom=0.09, wspace=0.01)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(OUTPUT, bbox_inches="tight", facecolor=figure.get_facecolor())
    plt.close(figure)
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
