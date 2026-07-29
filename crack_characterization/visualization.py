"""Publication-quality characterization figures without geometry distortion."""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
from matplotlib import pyplot as plt

from .geometry import surface_gradients
from .model import AnalysisResult, CharacterizationConfig, PreparedSurface


def _bounded_histogram_bins(values: np.ndarray) -> int:
    """Avoid pathological automatic bin counts for nearly discrete fields."""

    finite_count = int(np.count_nonzero(np.isfinite(values)))
    return int(np.clip(np.sqrt(max(finite_count, 1)), 12, 80))


def _plot_probability_density(
    axis: plt.Axes,
    values: np.ndarray,
    *,
    label: str,
    alpha: float,
) -> None:
    """Plot a finite density without dividing by zero-width histogram bins."""

    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return
    lower = float(np.min(finite))
    upper = float(np.max(finite))
    scale = max(abs(lower), abs(upper), np.finfo(float).tiny)
    constant_tolerance = 32.0 * np.finfo(float).eps * scale
    if upper - lower <= constant_tolerance:
        axis.axvline(
            float(np.mean(finite)),
            linewidth=2.0,
            alpha=max(alpha, 0.75),
            label=f"{label} (single value)",
        )
        return
    counts, edges = np.histogram(
        finite,
        bins=_bounded_histogram_bins(finite),
        density=False,
    )
    widths = np.diff(edges)
    total = int(np.sum(counts))
    if total == 0 or np.any(widths <= 0) or not np.all(np.isfinite(widths)):
        axis.axvline(
            float(np.mean(finite)),
            linewidth=2.0,
            alpha=max(alpha, 0.75),
            label=f"{label} (numerically degenerate)",
        )
        return
    density = counts / (total * widths)
    axis.stairs(
        density,
        edges,
        fill=True,
        alpha=alpha,
        label=label,
    )


def _save(
    figure: plt.Figure,
    stem: str,
    output_directory: Path,
    config: CharacterizationConfig,
    exported: dict[str, Path],
) -> None:
    for extension in config.publication_formats:
        path = output_directory / f"{stem}.{extension}"
        figure.savefig(path, dpi=config.figure_dpi, bbox_inches="tight")
        exported[f"{stem}_{extension}"] = path
    plt.close(figure)


def _physical_box_aspect(surface: PreparedSurface) -> tuple[float, float, float]:
    x = float(np.ptp(surface.x_axis))
    y = float(np.ptp(surface.y_axis))
    z = float(np.nanmax(surface.upper) - np.nanmin(surface.lower))
    largest = max(x, y, z, np.finfo(float).tiny)
    return x / largest, y / largest, max(z / largest, 0.03)


def _surface_figure(
    surface: PreparedSurface,
    aperture: np.ndarray,
    config: CharacterizationConfig,
) -> plt.Figure:
    figure = plt.figure(figsize=(13.0, 5.2), constrained_layout=True)
    upper_axes = figure.add_subplot(121, projection="3d")
    mid_axes = figure.add_subplot(122, projection="3d")
    step = max(1, max(surface.shape) // 100)
    upper_axes.plot_surface(
        surface.x[::step, ::step],
        surface.y[::step, ::step],
        surface.lower[::step, ::step],
        cmap="Blues",
        alpha=0.72,
        linewidth=0,
    )
    upper_axes.plot_surface(
        surface.x[::step, ::step],
        surface.y[::step, ::step],
        surface.upper[::step, ::step],
        cmap="Oranges",
        alpha=0.64,
        linewidth=0,
    )
    upper_axes.set_title("Lower and upper crack walls")
    colored = mid_axes.plot_surface(
        surface.x[::step, ::step],
        surface.y[::step, ::step],
        surface.mid[::step, ::step],
        facecolors=plt.cm.viridis(
            plt.Normalize(np.nanmin(aperture), np.nanmax(aperture))(
                aperture[::step, ::step]
            )
        ),
        linewidth=0,
    )
    colored.set_array(aperture[np.isfinite(aperture)])
    figure.colorbar(
        colored,
        ax=mid_axes,
        shrink=0.64,
        pad=0.08,
        label=f"Aperture [{config.length_unit}]",
    )
    mid_axes.set_title("Mid-surface colored by aperture")
    for axes in (upper_axes, mid_axes):
        axes.set_xlabel(f"X [{config.length_unit}]")
        axes.set_ylabel(f"Y [{config.length_unit}]")
        axes.set_zlabel(f"Z [{config.length_unit}]")
        axes.set_box_aspect(_physical_box_aspect(surface))
        axes.view_init(elev=27, azim=-55)
    figure.suptitle("Reconstructed crack geometry (no vertical exaggeration)")
    return figure


def _aperture_figure(
    surface: PreparedSurface,
    aperture: np.ndarray,
    result: AnalysisResult,
    config: CharacterizationConfig,
) -> plt.Figure:
    figure, axes = plt.subplots(2, 2, figsize=(12.5, 9.0), constrained_layout=True)
    contour = axes[0, 0].pcolormesh(
        surface.x,
        surface.y,
        aperture,
        shading="auto",
        cmap="viridis",
    )
    figure.colorbar(
        contour,
        ax=axes[0, 0],
        label=f"Aperture [{config.length_unit}]",
    )
    axes[0, 0].set_title("Local aperture")
    aperture_fields = {
        "Global Z": result.arrays["aperture_global_z"],
        "Local normal": result.arrays["aperture_local_normal"],
    }
    for label, field in aperture_fields.items():
        _plot_probability_density(
            axes[0, 1],
            field,
            label=label,
            alpha=0.48,
        )
    axes[0, 1].set_xlabel(f"Aperture [{config.length_unit}]")
    axes[0, 1].set_ylabel("Probability density")
    axes[0, 1].set_title("Both aperture definitions")
    axes[0, 1].legend()
    for label, field in aperture_fields.items():
        sorted_values = np.sort(field[np.isfinite(field)])
        axes[1, 0].plot(
            sorted_values,
            np.linspace(0, 1, sorted_values.size),
            label=label,
        )
    axes[1, 0].set_xlabel(f"Aperture [{config.length_unit}]")
    axes[1, 0].set_ylabel("Cumulative probability")
    axes[1, 0].set_title("Cumulative aperture distribution")
    axes[1, 0].legend()
    resistance = np.full_like(aperture, np.nan)
    open_mask = np.isfinite(aperture) & (aperture > config.aperture_cutoff)
    resistance[open_mask] = aperture[open_mask] ** -3
    resistance_plot = np.log10(resistance)
    image = axes[1, 1].pcolormesh(
        surface.x,
        surface.y,
        resistance_plot,
        shading="auto",
        cmap="magma",
    )
    figure.colorbar(
        image,
        ax=axes[1, 1],
        label=f"log10(1/b³) [{config.length_unit}⁻³]",
    )
    axes[1, 1].set_title("Cubic-law resistance proxy and bottlenecks")
    for axis in axes.ravel():
        if axis in (axes[0, 0], axes[1, 1]):
            axis.set_aspect("equal", adjustable="box")
        axis.grid(False)
    mean = result.summary["aperture"]["statistics"]["arithmetic_mean"]
    cubic = result.summary["aperture"]["statistics"]["global_cubic_mean"]
    hydraulic = result.summary["hydraulic_by_aperture_and_direction"][
        "local_normal"
    ]
    equivalent_x = hydraulic["X"]["global_equivalent_hydraulic_aperture"]
    equivalent_y = hydraulic["Y"]["global_equivalent_hydraulic_aperture"]
    figure.suptitle(
        f"Aperture characterization — mean={mean:.4g}, cubic={cubic:.4g}, "
        f"equivalent X/Y={equivalent_x:.4g}/{equivalent_y:.4g} "
        f"{config.length_unit}"
    )
    return figure


def _directional_figure(
    result: AnalysisResult,
    config: CharacterizationConfig,
) -> plt.Figure:
    figure, axes = plt.subplots(1, 2, figsize=(12.0, 4.8), constrained_layout=True)
    paths = result.tables["flow_path_equivalent_aperture"]
    for direction, color in (("X", "#1668a8"), ("Y", "#b45309")):
        selected = [
            row
            for row in paths
            if row["aperture_definition"] == "local_normal"
            and row["direction"] == direction
        ]
        offsets = np.array(
            [row["transverse_offset"] for row in selected],
            dtype=float,
        )
        equivalent = np.array(
            [row["equivalent_aperture"] for row in selected],
            dtype=float,
        )
        axes[0].plot(
            offsets,
            equivalent,
            marker="o",
            markersize=3,
            color=color,
            label=direction,
        )
    axes[0].set_xlabel(f"Transverse path offset [{config.length_unit}]")
    axes[0].set_ylabel(f"Equivalent aperture [{config.length_unit}]")
    axes[0].set_title("Local-normal series resistance by path")
    axes[0].legend(title="Direction")
    for direction, color in (("X", "#1668a8"), ("Y", "#b45309")):
        tortuosity = [
            row
            for row in result.tables["directional_tortuosity"]
            if row["surface"] == "mid" and row["direction"] == direction
        ]
        values = np.array(
            [row["geometrical_tortuosity"] for row in tortuosity],
            dtype=float,
        )
        axes[1].hist(
            values[np.isfinite(values)],
            bins=_bounded_histogram_bins(values),
            color=color,
            alpha=0.48,
            label=direction,
        )
    axes[1].set_xlabel("Geometrical tortuosity [1]")
    axes[1].set_ylabel("Profile count")
    axes[1].set_title("Automatic mid-surface X/Y tortuosity")
    axes[1].legend(title="Direction")
    figure.suptitle("Automatic X/Y directional diagnostics")
    return figure


def _hurst_figure(
    result: AnalysisResult,
) -> plt.Figure:
    rows = [
        row
        for row in result.tables["hurst_analysis"]
        if row["surface"] == "mid"
    ]
    figure, axes = plt.subplots(2, 2, figsize=(11.0, 8.5), constrained_layout=True)
    for axis, row in zip(axes.ravel(), rows, strict=False):
        prefix = f"hurst_mid_{row['direction']}_{row['method']}"
        scale = result.arrays[f"{prefix}_scale"]
        response = result.arrays[f"{prefix}_response"]
        fitted = result.arrays[f"{prefix}_fit"]
        if scale.size:
            axis.loglog(scale, response, "o", markersize=3, label="data")
            if np.isfinite(fitted).any():
                axis.loglog(scale, fitted, "-", label="fit")
        exponent = row["hurst_exponent"]
        label = "not estimable" if exponent is None else f"H={exponent:.3f}"
        axis.set_title(f"{row['direction']} — {row['method'].replace('_', ' ')}\n{label}")
        axis.set_xlabel("Spatial scale")
        axis.set_ylabel("Increment RMS" if row["method"] == "structure_function" else "PSD")
        if axis.lines:
            axis.legend(loc="best")
        axis.grid(True, which="both", alpha=0.25)
    figure.suptitle("Mid-surface Hurst scaling diagnostics")
    return figure


def _orientation_figure(
    surface: PreparedSurface,
    result: AnalysisResult,
    config: CharacterizationConfig,
) -> plt.Figure:
    dz_dx, dz_dy = surface_gradients(surface.mid, surface)
    slope = np.hypot(dz_dx, dz_dy)
    correlation = result.arrays["mid_surface_autocorrelation"]
    figure, axes = plt.subplots(1, 2, figsize=(12.0, 4.8), constrained_layout=True)
    image = axes[0].pcolormesh(
        surface.x,
        surface.y,
        slope,
        shading="auto",
        cmap="cividis",
    )
    figure.colorbar(image, ax=axes[0], label="Local slope magnitude [1]")
    axes[0].set_title("Mid-surface local slope")
    extent = [
        -0.5 * np.ptp(surface.x_axis),
        0.5 * np.ptp(surface.x_axis),
        -0.5 * np.ptp(surface.y_axis),
        0.5 * np.ptp(surface.y_axis),
    ]
    auto = axes[1].imshow(
        correlation,
        origin="lower",
        extent=extent,
        cmap="coolwarm",
        vmin=-1,
        vmax=1,
        aspect="equal",
    )
    figure.colorbar(auto, ax=axes[1], label="Normalized autocorrelation [1]")
    axes[1].set_title("Mid-surface 2D autocorrelation")
    axes[1].set_xlabel(f"X lag [{config.length_unit}]")
    axes[1].set_ylabel(f"Y lag [{config.length_unit}]")
    axes[0].set_aspect("equal", adjustable="box")
    axes[0].set_xlabel(f"X [{config.length_unit}]")
    axes[0].set_ylabel(f"Y [{config.length_unit}]")
    return figure


def export_figures(
    surface: PreparedSurface,
    aperture: np.ndarray,
    result: AnalysisResult,
    config: CharacterizationConfig,
    output_directory: Path,
) -> dict[str, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    exported: dict[str, Path] = {}
    figures = {
        "crack_surfaces_3d": _surface_figure(surface, aperture, config),
        "aperture_characterization": _aperture_figure(
            surface, aperture, result, config
        ),
        "directional_flow_metrics": _directional_figure(result, config),
        "hurst_diagnostics": _hurst_figure(result),
        "orientation_autocorrelation": _orientation_figure(
            surface, result, config
        ),
    }
    for stem, figure in figures.items():
        _save(figure, stem, output_directory, config, exported)
    return exported
