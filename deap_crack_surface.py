"""Standalone DEAP crack-to-smoothed-surface reconstruction.

This module ports the surface-producing path of
``original_input/source/DEAP_crack_CFD_coupling.m`` to Python.  It reads the
DEAP HDF5 files directly, extracts connected crack components, and evaluates
a two-dimensional quadratic LOESS fit compatible with MATLAB's ``loess``
surface model.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import h5py
import numpy as np
from numpy.typing import NDArray
from scipy.spatial import ConvexHull

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


@dataclass(frozen=True)
class SurfaceConfig:
    case_dir: Path
    time_step: int
    component: int = 1
    span: float = 0.05
    grid_resolution: int = 50
    opening_threshold: float = 1.0e-8
    orientation: str = "ZX"
    magnification: float = 1.0
    bounding_box: tuple[float, float, float, float, float, float] | None = None

    def validate(self) -> None:
        if isinstance(self.time_step, bool) or self.time_step < 0:
            raise ValueError("time_step must be non-negative")
        if isinstance(self.component, bool) or self.component < 1:
            raise ValueError("component uses MATLAB-style numbering and must be >= 1")
        if not math.isfinite(self.span) or not 0.0 < self.span <= 1.0:
            raise ValueError("span must be in (0, 1]")
        if isinstance(self.grid_resolution, bool) or self.grid_resolution <= 0:
            raise ValueError("grid_resolution must be positive")
        if not math.isfinite(self.opening_threshold) or self.opening_threshold < 0.0:
            raise ValueError("opening_threshold must be non-negative")
        if self.orientation not in {"XY", "YZ", "ZX"}:
            raise ValueError("orientation must be one of XY, YZ, or ZX")
        if not math.isfinite(self.magnification):
            raise ValueError("magnification must be finite")
        if self.bounding_box is not None:
            if len(self.bounding_box) != 6:
                raise ValueError("bounding_box must contain Xmin Xmax Ymin Ymax Zmin Zmax")
            if not all(math.isfinite(value) for value in self.bounding_box):
                raise ValueError("bounding_box values must be finite")
            if any(
                self.bounding_box[index] >= self.bounding_box[index + 1]
                for index in (0, 2, 4)
            ):
                raise ValueError("bounding_box minima must be smaller than maxima")


@dataclass(frozen=True)
class CrackComponent:
    node_ids: IntArray
    xyz_min: FloatArray
    xyz_max: FloatArray

    @property
    def opening(self) -> FloatArray:
        return self.xyz_max[:, 2] - self.xyz_min[:, 2]


@dataclass(frozen=True)
class SurfaceResult:
    x: FloatArray
    y: FloatArray
    z_min: FloatArray
    z_max: FloatArray
    component: CrackComponent
    fit_x: FloatArray
    fit_y: FloatArray
    fit_z_min: FloatArray
    fit_z_max: FloatArray
    fit_weights: FloatArray
    metadata: dict[str, object]


def _oriented_columns(orientation: str) -> tuple[int, int, int]:
    return {"XY": (0, 1, 2), "YZ": (1, 2, 0), "ZX": (2, 0, 1)}[orientation]


def _read_limits(config: SurfaceConfig) -> tuple[float, float, float, float, float, float]:
    boundary = config.case_dir / "input.boundary"
    if boundary.is_file():
        limits = np.loadtxt(boundary, dtype=np.float64)
        if limits.shape != (2, 3):
            raise ValueError(f"{boundary} must contain two rows and three columns")
        global_limits = (
            float(limits[0, 0]),
            float(limits[1, 0]),
            float(limits[0, 1]),
            float(limits[1, 1]),
            float(limits[0, 2]),
            float(limits[1, 2]),
        )
    elif config.bounding_box is not None:
        global_limits = config.bounding_box
    else:
        raise FileNotFoundError(
            f"{boundary} does not exist; provide a six-value bounding_box"
        )

    pairs = (
        (global_limits[0], global_limits[1]),
        (global_limits[2], global_limits[3]),
        (global_limits[4], global_limits[5]),
    )
    a, b, c = _oriented_columns(config.orientation)
    return (*pairs[a], *pairs[b], *pairs[c])


def _group_displacements(
    inverse: IntArray, displacements: FloatArray, group_count: int
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Match the per-unique-vertex mean/min/max operations in MATLAB."""
    order = np.argsort(inverse, kind="stable")
    sorted_groups = inverse[order]
    boundaries = np.r_[0, np.flatnonzero(np.diff(sorted_groups)) + 1, order.size]
    mean_disp = np.empty((group_count, 3), dtype=np.float64)
    min_disp = np.empty((group_count, 3), dtype=np.float64)
    max_disp = np.empty((group_count, 3), dtype=np.float64)

    for group in range(group_count):
        members = order[boundaries[group] : boundaries[group + 1]]
        values = displacements[members]
        average = np.mean(values, axis=0)
        mean_disp[group] = average
        min_disp[group] = average
        max_disp[group] = average
        min_disp[group, 2] = np.min(values[:, 2])
        max_disp[group, 2] = np.max(values[:, 2])
    return mean_disp, min_disp, max_disp


def _parse_open_edges(
    crack_connectivity: IntArray,
    inverse: IntArray,
    openings: FloatArray,
    crack_count: int,
    threshold: float,
) -> list[tuple[int, int]]:
    edges: list[tuple[int, int]] = []
    read_count = 0
    for crack_index in range(crack_count):
        count_index = 2 * crack_index + 1 + read_count
        if count_index >= crack_connectivity.size:
            raise ValueError("vs_broken_connect ends before all crack faces are parsed")
        vertex_count = int(crack_connectivity[count_index])
        start = count_index + 1
        stop = start + vertex_count
        if stop > crack_connectivity.size:
            raise ValueError("invalid vertex count in vs_broken_connect")
        if openings[crack_index] >= threshold:
            original_nodes = crack_connectivity[start:stop]
            nodes = inverse[original_nodes]
            for node_a, node_b in zip(nodes, np.roll(nodes, -1), strict=True):
                a, b = int(node_a), int(node_b)
                if a != b:
                    edges.append((min(a, b), max(a, b)))
        read_count += vertex_count
    return list(dict.fromkeys(edges))


def _connected_components(edges: Iterable[tuple[int, int]]) -> list[IntArray]:
    adjacency: dict[int, set[int]] = {}
    for a, b in edges:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)

    components: list[IntArray] = []
    unseen = set(adjacency)
    while unseen:
        seed = min(unseen)
        stack = [seed]
        unseen.remove(seed)
        found: list[int] = []
        while stack:
            node = stack.pop()
            found.append(node)
            for neighbor in sorted(adjacency[node], reverse=True):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
        if len(found) > 10:
            components.append(np.asarray(sorted(found), dtype=np.int64))
    components.sort(key=lambda values: (-values.size, int(values[0])))
    return components


def extract_components(config: SurfaceConfig) -> list[CrackComponent]:
    """Extract open connected macro-cracks in descending node-count order."""
    config.validate()
    post_path = config.case_dir / "deap_post.h5"
    output_path = config.case_dir / "deap_output.h5"
    if not post_path.is_file() or not output_path.is_file():
        raise FileNotFoundError("case directory must contain deap_post.h5 and deap_output.h5")

    with h5py.File(output_path, "r") as output_h5:
        available_steps = sum(name.startswith("disp_trans_") for name in output_h5)
    time_step = min(config.time_step, available_steps)

    with h5py.File(post_path, "r") as post_h5:
        coordinates = np.asarray(post_h5["v_elem_coord"], dtype=np.float64)
        displacements = np.asarray(post_h5[f"disp_{time_step:04d}"], dtype=np.float64)
        openings = np.asarray(post_h5[f"crack_open_{time_step:04d}"], dtype=np.float64)
        crack_count = int(post_h5["nSurfaces_per_time_step"][time_step])
        connectivity = np.asarray(post_h5["vs_broken_connect"], dtype=np.int64)

    if np.all(openings <= config.opening_threshold):
        raise ValueError(
            f"no crack openings exceed {config.opening_threshold:g} at time step {time_step}"
        )

    columns = _oriented_columns(config.orientation)
    coordinates = coordinates[:, columns]
    displacements = displacements[:, columns]
    unique_coordinates, _, inverse_raw = np.unique(
        coordinates, axis=0, return_index=True, return_inverse=True
    )
    inverse = np.asarray(inverse_raw, dtype=np.int64)
    _, disp_min, disp_max = _group_displacements(
        inverse, displacements, unique_coordinates.shape[0]
    )
    xyz_min = unique_coordinates + config.magnification * disp_min
    xyz_max = unique_coordinates + config.magnification * disp_max

    edges = _parse_open_edges(
        connectivity, inverse, openings, crack_count, config.opening_threshold
    )
    node_groups = _connected_components(edges)
    return [
        CrackComponent(nodes, xyz_min[nodes], xyz_max[nodes]) for nodes in node_groups
    ]


def _quadratic_terms(dx: FloatArray, dy: FloatArray) -> FloatArray:
    return np.column_stack(
        (np.ones_like(dx), dx, dy, dx * dx, dy * dy, dx * dy)
    )


def quadratic_loess_surface(
    x: FloatArray,
    y: FloatArray,
    z: FloatArray,
    query_x: FloatArray,
    query_y: FloatArray,
    *,
    span: float,
    user_weights: FloatArray | None = None,
) -> FloatArray:
    """Evaluate normalized 2-D quadratic LOESS at arbitrary query points.

    Neighborhoods use Euclidean distance after MATLAB-style centering and
    sample-standard-deviation scaling.  Each local regression combines the
    tricube distance weights with the supplied fit weights.
    """
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    y = np.asarray(y, dtype=np.float64).reshape(-1)
    z = np.asarray(z, dtype=np.float64).reshape(-1)
    qx = np.asarray(query_x, dtype=np.float64)
    qy = np.asarray(query_y, dtype=np.float64)
    if x.shape != y.shape or x.shape != z.shape:
        raise ValueError("x, y, and z must have equal lengths")
    if qx.shape != qy.shape:
        raise ValueError("query_x and query_y must have equal shapes")
    if x.size < 6:
        raise ValueError("quadratic surface LOESS requires at least six points")

    weights = (
        np.ones_like(z)
        if user_weights is None
        else np.asarray(user_weights, dtype=np.float64).reshape(-1)
    )
    if weights.shape != z.shape or np.any(weights < 0.0):
        raise ValueError("user_weights must be non-negative and match z")

    x_mean, y_mean = float(np.mean(x)), float(np.mean(y))
    x_scale, y_scale = float(np.std(x, ddof=1)), float(np.std(y, ddof=1))
    if x_scale == 0.0 or y_scale == 0.0:
        raise ValueError("both predictors must have non-zero variance")
    xn = (x - x_mean) / x_scale
    yn = (y - y_mean) / y_scale
    qxn = (qx.reshape(-1) - x_mean) / x_scale
    qyn = (qy.reshape(-1) - y_mean) / y_scale

    point_count = x.size
    neighbor_count = min(point_count, max(6, int(math.ceil(span * point_count))))
    positive = weights > 0.0
    xn_positive = xn[positive]
    yn_positive = yn[positive]
    z_positive = z[positive]
    weights_positive = weights[positive]
    if xn_positive.size < neighbor_count:
        raise ValueError("too few positive-weight points for the requested LOESS span")

    fitted = np.empty(qxn.size, dtype=np.float64)
    for row in range(qxn.size):
        all_distances = np.sqrt(
            (xn_positive - qxn[row]) ** 2 + (yn_positive - qyn[row]) ** 2
        )
        # MATLAB's sort is stable for equal distances.  A stable full sort also
        # avoids implementation-dependent k-d-tree tie selection.
        local_indices = np.argsort(all_distances, kind="stable")[:neighbor_count]
        local_distances = all_distances[local_indices]
        bandwidth = float(local_distances[-1])
        if bandwidth == 0.0:
            fitted[row] = float(
                np.average(z_positive[local_indices], weights=weights_positive[local_indices])
            )
            continue
        distance_weights = np.clip(1.0 - (local_distances / bandwidth) ** 3, 0.0, None) ** 3
        combined = distance_weights * weights_positive[local_indices]
        keep = combined > 0.0
        local_indices = local_indices[keep]
        combined = combined[keep]
        # MATLAB's curvefit.LowessFit uses the globally referenced normalized
        # predictors divided by the local bandwidth (rather than centering the
        # polynomial at the query point).  The distinction matters numerically
        # for ill-conditioned neighborhoods near a surface boundary.
        design = _quadratic_terms(
            xn_positive[local_indices] / bandwidth,
            yn_positive[local_indices] / bandwidth,
        )
        root_weight = np.sqrt(combined)
        coefficients, _, _, _ = np.linalg.lstsq(
            design * root_weight[:, None],
            z_positive[local_indices] * root_weight,
            rcond=None,
        )
        query_terms = _quadratic_terms(
            np.asarray([qxn[row] / bandwidth]),
            np.asarray([qyn[row] / bandwidth]),
        )
        fitted[row] = (query_terms @ coefficients).item()
    return fitted.reshape(qx.shape)


def _closed_hull_indices(x: FloatArray, y: FloatArray) -> IntArray:
    vertices = ConvexHull(np.column_stack((x, y))).vertices.astype(np.int64)
    # MATLAB's convhull starts its closed cycle at the smallest original point
    # index.  Qhull returns the same cycle through SciPy but with an arbitrary
    # rotation; the start matters here because the closed vertex is duplicated
    # once more and therefore receives extra fit weight.
    start = int(np.argmin(vertices))
    vertices = np.roll(vertices, -start)
    return np.r_[vertices, vertices[0]]


def reconstruct_surface(config: SurfaceConfig) -> SurfaceResult:
    config.validate()
    components = extract_components(config)
    if config.component > len(components):
        raise ValueError(
            f"component {config.component} requested, but only {len(components)} eligible components exist"
        )
    component = components[config.component - 1]
    if component.node_ids.size <= 8:
        raise ValueError("selected component has too few points for surface fitting")

    x_min, y_min, z_min = component.xyz_min.T
    x_max, y_max, z_max = component.xyz_max.T
    opening = component.opening.copy()
    opening[opening == 0.0] = np.finfo(np.float64).eps
    opening /= np.max(opening)

    hull_min = _closed_hull_indices(x_min, y_min)
    hull_max = _closed_hull_indices(x_max, y_max)
    fit_x_min = np.r_[x_min, x_min[hull_min]]
    fit_y_min = np.r_[y_min, y_min[hull_min]]
    fit_z_min = np.r_[z_min, z_min[hull_min]]
    weights_min = np.r_[opening, opening[hull_min]]
    fit_x_max = np.r_[x_max, x_max[hull_max]]
    fit_y_max = np.r_[y_max, y_max[hull_max]]
    fit_z_max = np.r_[z_max, z_max[hull_max]]
    weights_max = np.r_[opening, opening[hull_max]]

    xmin, xmax, ymin, ymax, _, _ = _read_limits(config)
    element_size = min(
        (xmax - xmin) / config.grid_resolution,
        (ymax - ymin) / config.grid_resolution,
    )
    grid_span_x = max(10, int(math.ceil((xmax - xmin) / element_size)))
    grid_span_y = max(10, int(math.ceil((ymax - ymin) / element_size)))
    grid_x, grid_y = np.meshgrid(
        np.linspace(xmin, xmax, grid_span_x),
        np.linspace(ymin, ymax, grid_span_y),
    )

    fitted_min = quadratic_loess_surface(
        fit_x_min,
        fit_y_min,
        fit_z_min,
        grid_x,
        grid_y,
        span=config.span,
        user_weights=weights_min,
    )
    raw_fitted_max = quadratic_loess_surface(
        fit_x_max,
        fit_y_max,
        fit_z_max,
        grid_x,
        grid_y,
        span=config.span,
        user_weights=weights_max,
    )

    data_xmin = min(float(np.min(fit_x_min)), float(np.min(fit_x_max)))
    data_xmax = max(float(np.max(fit_x_min)), float(np.max(fit_x_max)))
    data_ymin = min(float(np.min(fit_y_min)), float(np.min(fit_y_max)))
    data_ymax = max(float(np.max(fit_y_min)), float(np.max(fit_y_max)))
    valid_x = np.flatnonzero((grid_x[0] >= data_xmin) & (grid_x[0] <= data_xmax))
    valid_y = np.flatnonzero((grid_y[:, 0] >= data_ymin) & (grid_y[:, 0] <= data_ymax))
    if valid_x.size == 0 or valid_y.size == 0:
        raise ValueError("selected component does not overlap the output grid")
    ix_min, ix_max = int(valid_x[0]), int(valid_x[-1])
    iy_min, iy_max = int(valid_y[0]), int(valid_y[-1])
    inside = (
        (grid_x >= data_xmin)
        & (grid_x <= data_xmax)
        & (grid_y >= data_ymin)
        & (grid_y <= data_ymax)
    )
    opening_fit = raw_fitted_max - fitted_min
    opening_fit[~inside] = 0.0

    if ix_min > 0:
        fitted_min[:, :ix_min] = fitted_min[:, [ix_min]]
    if ix_max + 1 < fitted_min.shape[1]:
        fitted_min[:, ix_max + 1 :] = fitted_min[:, [ix_max]]
    if iy_min > 0:
        fitted_min[:iy_min, :] = fitted_min[[iy_min], :]
    if iy_max + 1 < fitted_min.shape[0]:
        fitted_min[iy_max + 1 :, :] = fitted_min[[iy_max], :]
    opening_fit[opening_fit < 0.0] = 0.0
    fitted_max = fitted_min + opening_fit

    metadata: dict[str, object] = {
        "algorithm": "normalized 2D quadratic LOESS compatible with MATLAB fittype('loess')",
        "results_directory": config.case_dir.name,
        "input_files": {
            "deap_post.h5": (config.case_dir / "deap_post.h5").stat().st_size,
            "deap_output.h5": (config.case_dir / "deap_output.h5").stat().st_size,
        },
        "time_step": min(config.time_step, _count_output_steps(config.case_dir)),
        "component": config.component,
        "component_nodes": int(component.node_ids.size),
        "span": config.span,
        "grid_resolution": config.grid_resolution,
        "grid_shape": list(grid_x.shape),
        "opening_threshold": config.opening_threshold,
        "orientation": config.orientation,
        "magnification": config.magnification,
        "fit_points_min": int(fit_x_min.size),
        "fit_points_max": int(fit_x_max.size),
        "eligible_components": len(components),
    }
    return SurfaceResult(
        grid_x,
        grid_y,
        fitted_min,
        fitted_max,
        component,
        fit_x_min,
        fit_y_min,
        fit_z_min,
        fit_z_max,
        weights_min,
        metadata,
    )


def _count_output_steps(case_dir: Path) -> int:
    with h5py.File(case_dir / "deap_output.h5", "r") as output_h5:
        return sum(name.startswith("disp_trans_") for name in output_h5)


def matlab_tag(config: SurfaceConfig) -> str:
    def matlab_round_nonnegative(value: float) -> int:
        return int(math.floor(value + 0.5))

    return (
        f"_ti{min(config.time_step, _count_output_steps(config.case_dir))}"
        f"_crpa{config.component}_smfa{matlab_round_nonnegative(config.span * 100)}"
        f"_numsp{config.grid_resolution}"
        f"_opmin{matlab_round_nonnegative(config.opening_threshold * 1.0e9)}"
    )


def write_surface_csvs(
    result: SurfaceResult, config: SurfaceConfig, output_dir: Path
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tag = matlab_tag(config)
    arrays = {
        "zfit_zmin": result.z_min,
        "zfit_zmax": result.z_max,
        "yrange": result.y,
        "xrange": result.x,
    }
    written: list[Path] = []
    for stem, values in arrays.items():
        path = output_dir / f"{stem}{tag}.csv"
        np.savetxt(path, values, delimiter=",", fmt="%.17g")
        written.append(path)
    report_path = output_dir / f"surface_report{tag}.json"
    report_path.write_text(json.dumps(result.metadata, indent=2) + "\n", encoding="utf-8")
    written.append(report_path)
    return written


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--time-step", type=int, required=True)
    parser.add_argument("--component", type=int, default=1)
    parser.add_argument("--span", type=float, required=True)
    parser.add_argument("--grid-resolution", type=int, required=True)
    parser.add_argument("--opening-threshold", type=float, required=True)
    parser.add_argument("--orientation", choices=("XY", "YZ", "ZX"), required=True)
    parser.add_argument("--magnification", type=float, default=1.0)
    parser.add_argument("--bounding-box", type=float, nargs=6)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = SurfaceConfig(
        case_dir=args.case_dir,
        time_step=args.time_step,
        component=args.component,
        span=args.span,
        grid_resolution=args.grid_resolution,
        opening_threshold=args.opening_threshold,
        orientation=args.orientation,
        magnification=args.magnification,
        bounding_box=None if args.bounding_box is None else tuple(args.bounding_box),
    )
    result = reconstruct_surface(config)
    paths = write_surface_csvs(result, config, args.output_dir)
    print(json.dumps({"metadata": result.metadata, "written": [str(path) for path in paths]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
