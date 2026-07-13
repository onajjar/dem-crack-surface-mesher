"""Vectorized Python generation of inflated Cast3M circular-hole fills.

The baseline Cast3M program creates hole fills at ``z = 0`` and then
interpolates/displaces every node in three full surface meshes.  For dense
meshes that pass dominates runtime.  This module mirrors the hole-boundary
detection, builds every radially inflated fill node and ``CQUAD4`` in NumPy,
writes three small NASTRAN BDF files, and patches a derived DGIBI so Cast3M
loads each complete mesh with ``LIRE 'NAS'``.

The immutable baseline files are intentionally not modified.  The optimized
path is opt-in and only applies when holes are enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np


MAIN_HOLE_BLOCK_START = "* Correct the z coordinates for the filling elements based on the original point clouds"
MAIN_HOLE_BLOCK_END = "* Remove duplicated nodes\nELIM surf_zmin re_tol ;"


@dataclass(frozen=True)
class CircleRing:
    """Counter-clockwise outer and projected inner boundaries for one hole."""

    hole_index: int
    outer_xy: np.ndarray
    xy: np.ndarray


@dataclass(frozen=True)
class SurfaceFillMesh:
    """One complete hole-fill surface ready for NASTRAN serialization."""

    points: np.ndarray
    quads: np.ndarray


@dataclass(frozen=True)
class HoleFillMeshSet:
    """Three generated surface meshes plus reproducibility metadata."""

    min_path: Path
    max_path: Path
    mean_path: Path
    min_mesh: SurfaceFillMesh
    max_mesh: SurfaceFillMesh
    mean_mesh: SurfaceFillMesh
    points_per_hole: tuple[int, ...]
    radial_fractions: np.ndarray


def _load_matrix(path: Path) -> np.ndarray:
    try:
        values = np.loadtxt(path, delimiter=",", dtype=float)
    except ValueError as exc:
        raise ValueError(f"Could not read numeric CSV data from {path}.") from exc
    values = np.atleast_2d(values)
    if values.ndim != 2 or min(values.shape) < 2:
        raise ValueError(f"{path} must contain a 2D grid with at least 2 rows and 2 columns.")
    if not np.isfinite(values).all():
        raise ValueError(f"{path} contains non-finite values.")
    return values


def load_surface_csvs(
    csv_x: Path, csv_y: Path, csv_zmin: Path, csv_zmax: Path
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Load and validate the four equally shaped structured-grid CSV files."""

    x = _load_matrix(csv_x)
    y = _load_matrix(csv_y)
    zmin = _load_matrix(csv_zmin)
    zmax = _load_matrix(csv_zmax)
    expected_shape = x.shape
    for label, values in (("y", y), ("zmin", zmin), ("zmax", zmax)):
        if values.shape != expected_shape:
            raise ValueError(
                f"CSV grids must have one shape; x is {expected_shape} but {label} is {values.shape}."
            )
    return x, y, zmin, zmax


def _quantized_xy(x: float, y: float, tolerance: float) -> tuple[int, int]:
    return (int(round(x / tolerance)), int(round(y / tolerance)))


def _edge_subdivision_count(
    start: np.ndarray,
    end: np.ndarray,
    grid_locations: dict[tuple[int, int], list[tuple[int, int]]],
    *,
    nelem_x: int,
    nelem_y: int,
    tolerance: float,
) -> int:
    """Match one ordered contour edge to its structured-grid subdivision."""

    start_locations = grid_locations.get(_quantized_xy(*start, tolerance), ())
    end_locations = grid_locations.get(_quantized_xy(*end, tolerance), ())
    same_row: list[int] = []
    same_column: list[int] = []
    for start_row, start_column in start_locations:
        for end_row, end_column in end_locations:
            if start_row == end_row and start_column != end_column:
                same_row.append(abs(end_column - start_column) * nelem_x)
            if start_column == end_column and start_row != end_row:
                same_column.append(abs(end_row - start_row) * nelem_y)
    if same_row or same_column:
        return min((*same_row, *same_column))

    # The angular ordering should normally connect source-grid neighbours. A
    # geometric fallback keeps mildly curvilinear/duplicated coordinate grids
    # usable while retaining the axis-specific Cast3M subdivision intent.
    delta = np.abs(end - start)
    return nelem_x if delta[0] >= delta[1] else nelem_y


def _subdivide_ordered_contour(
    points: np.ndarray,
    grid_locations: dict[tuple[int, int], list[tuple[int, int]]],
    *,
    nelem_x: int,
    nelem_y: int,
    tolerance: float,
) -> np.ndarray:
    """Insert the same edge nodes that Cast3M creates on the background grid."""

    blocks: list[np.ndarray] = []
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        count = _edge_subdivision_count(
            start,
            end,
            grid_locations,
            nelem_x=nelem_x,
            nelem_y=nelem_y,
            tolerance=tolerance,
        )
        fractions = np.arange(count, dtype=float)[:, np.newaxis] / count
        blocks.append((1.0 - fractions) * start + fractions * end)
    return np.vstack(blocks)


def detect_circle_rings(
    x: np.ndarray,
    y: np.ndarray,
    holes: Sequence[object],
    *,
    tolerance: float = 1.0e-10,
    margin: float = 1.05,
    nelem_x: int = 1,
    nelem_y: int = 1,
) -> tuple[CircleRing, ...]:
    """Replicate the baseline ``CR_SURF`` + ``CIRC_INT`` boundary selection.

    ``CR_SURF`` skips a source cell when a corner falls inside a hole's
    inflated bounding square.  Its outside corners then form the rectangle
    side of the fill region.  ``CIRC_INT`` de-duplicates those corners, orders
    them by angle, and radially projects them onto the circle.  Only the final
    projected XY coordinates are needed here; their Z coordinates are
    evaluated in Python. Each ordered outer edge is subdivided exactly as the
    corresponding Cast3M background-grid edge, preventing hanging nodes when
    ``nelem_x`` or ``nelem_y`` is greater than one.
    """

    if x.shape != y.shape:
        raise ValueError("x and y grids must have the same shape.")
    if tolerance <= 0.0:
        raise ValueError("tolerance must be positive.")
    if margin <= 0.0:
        raise ValueError("margin must be positive.")
    if nelem_x < 1 or nelem_y < 1:
        raise ValueError("nelem_x and nelem_y must be >= 1.")

    normalized_holes: list[tuple[float, float, float]] = []
    for index, hole in enumerate(holes, start=1):
        try:
            cx, cy, radius = float(hole.cx), float(hole.cy), float(hole.r)
        except AttributeError as exc:
            raise TypeError("Each hole must provide cx, cy, and r attributes.") from exc
        if not np.isfinite((cx, cy, radius)).all() or radius <= 0.0:
            raise ValueError(f"Hole {index} must have finite cx/cy and a positive radius.")
        normalized_holes.append((cx, cy, radius))

    if not normalized_holes:
        return ()

    rows, cols = x.shape
    grid_locations: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for row in range(rows):
        for col in range(cols):
            grid_locations.setdefault(
                _quantized_xy(float(x[row, col]), float(y[row, col]), tolerance),
                [],
            ).append((row, col))
    candidates: list[dict[tuple[int, int], tuple[float, float]]] = [
        {} for _ in normalized_holes
    ]

    for row in range(rows - 1):
        for col in range(cols - 1):
            corners = (
                (float(x[row, col]), float(y[row, col])),
                (float(x[row + 1, col]), float(y[row + 1, col])),
                (float(x[row + 1, col + 1]), float(y[row + 1, col + 1])),
                (float(x[row, col + 1]), float(y[row, col + 1])),
            )
            for hole_index, (cx, cy, radius) in enumerate(normalized_holes):
                inflated = margin * radius
                inside = tuple(
                    (cx - inflated < px < cx + inflated)
                    and (cy - inflated < py < cy + inflated)
                    for px, py in corners
                )
                if any(inside):
                    for is_inside, point in zip(inside, corners, strict=True):
                        if not is_inside:
                            candidates[hole_index].setdefault(
                                _quantized_xy(*point, tolerance), point
                            )

    rings: list[CircleRing] = []
    for hole_index, ((cx, cy, radius), per_hole_candidates) in enumerate(
        zip(normalized_holes, candidates, strict=True), start=1
    ):
        # ``ELIM (po_rec_hi ET SURF1)`` in the baseline merges coincident
        # Cast3M point objects.  It does not subtract the outer contour from
        # ``po_rec_hi``.  Retaining every unique candidate therefore mirrors
        # the following ``UNIQ po_rec_hi`` operation.
        boundary = list(per_hole_candidates.values())
        if len(boundary) < 3:
            raise ValueError(
                f"Hole {hole_index} produced only {len(boundary)} boundary points. "
                "Move the circle fully inside the input grid and away from other holes."
            )

        points = np.asarray(boundary, dtype=float)
        angles = np.arctan2(points[:, 1] - cy, points[:, 0] - cx)
        points = points[np.argsort(angles, kind="stable")]
        points = _subdivide_ordered_contour(
            points,
            grid_locations,
            nelem_x=nelem_x,
            nelem_y=nelem_y,
            tolerance=tolerance,
        )
        direction = points - np.array((cx, cy), dtype=float)
        distance = np.hypot(direction[:, 0], direction[:, 1])
        if np.any(distance <= tolerance):
            raise ValueError(
                f"Hole {hole_index} has a detected boundary point at its centre; "
                "the circle projection is undefined."
            )
        ring_xy = np.column_stack(
            (
                cx + radius * direction[:, 0] / distance,
                cy + radius * direction[:, 1] / distance,
            )
        )
        rings.append(CircleRing(hole_index=hole_index, outer_xy=points, xy=ring_xy))
    return tuple(rings)


def _axis_coordinates(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Return grid axes for the common rectilinear CSV layout, if applicable."""

    x_axis = x[0, :]
    y_axis = y[:, 0]
    if np.allclose(x, x_axis[np.newaxis, :], rtol=0.0, atol=1.0e-12) and np.allclose(
        y, y_axis[:, np.newaxis], rtol=0.0, atol=1.0e-12
    ):
        if (np.all(np.diff(x_axis) > 0.0) or np.all(np.diff(x_axis) < 0.0)) and (
            np.all(np.diff(y_axis) > 0.0) or np.all(np.diff(y_axis) < 0.0)
        ):
            return x_axis, y_axis
    return None


def _cell_indices(axis: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Locate many values on one monotonic axis without a Python point loop."""

    values = np.asarray(values, dtype=float)
    ascending = axis[-1] > axis[0]
    sorted_axis = axis if ascending else axis[::-1]
    if np.any(values < sorted_axis[0] - 1.0e-12) or np.any(
        values > sorted_axis[-1] + 1.0e-12
    ):
        raise ValueError("A circle point lies outside the source-grid extent.")
    position = np.searchsorted(sorted_axis, values, side="right") - 1
    position = np.clip(position, 0, len(sorted_axis) - 2).astype(int, copy=False)
    if not ascending:
        position = len(axis) - 2 - position
    denominator = axis[position + 1] - axis[position]
    return position, (values - axis[position]) / denominator


def _interpolate_rectilinear(
    x_axis: np.ndarray, y_axis: np.ndarray, z: np.ndarray, points: np.ndarray
) -> np.ndarray:
    cols, u = _cell_indices(x_axis, points[:, 0])
    rows, v = _cell_indices(y_axis, points[:, 1])
    z00 = z[rows, cols]
    z10 = z[rows, cols + 1]
    z11 = z[rows + 1, cols + 1]
    z01 = z[rows + 1, cols]
    return (
        (1.0 - u) * (1.0 - v) * z00
        + u * (1.0 - v) * z10
        + u * v * z11
        + (1.0 - u) * v * z01
    )


def _interpolate_curvilinear(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, points: np.ndarray
) -> np.ndarray:
    """Bilinear interpolation for a structured, non-rectilinear grid.

    This fallback locates a containing cell from its bounding box and solves
    the bilinear inverse with Newton iterations.  Circle rings contain a small
    number of points, so robustness is more useful than global pre-indexing.
    """

    values = np.empty(len(points), dtype=float)
    rows, cols = x.shape
    for point_index, (px, py) in enumerate(points):
        found = False
        for row in range(rows - 1):
            if found:
                break
            for col in range(cols - 1):
                corners_x = np.array((x[row, col], x[row, col + 1], x[row + 1, col + 1], x[row + 1, col]))
                corners_y = np.array((y[row, col], y[row, col + 1], y[row + 1, col + 1], y[row + 1, col]))
                if not (
                    corners_x.min() - 1.0e-12 <= px <= corners_x.max() + 1.0e-12
                    and corners_y.min() - 1.0e-12 <= py <= corners_y.max() + 1.0e-12
                ):
                    continue

                p00 = np.array((x[row, col], y[row, col]), dtype=float)
                p10 = np.array((x[row, col + 1], y[row, col + 1]), dtype=float)
                p11 = np.array((x[row + 1, col + 1], y[row + 1, col + 1]), dtype=float)
                p01 = np.array((x[row + 1, col], y[row + 1, col]), dtype=float)
                a = p10 - p00
                b = p01 - p00
                c = p00 - p10 - p01 + p11
                uv = np.array((0.5, 0.5), dtype=float)
                target = np.array((px, py), dtype=float)
                singular = False
                for _ in range(12):
                    u, v = uv
                    current = p00 + u * a + v * b + u * v * c
                    residual = current - target
                    jacobian = np.column_stack((a + v * c, b + u * c))
                    try:
                        update = np.linalg.solve(jacobian, residual)
                    except np.linalg.LinAlgError:
                        singular = True
                        break
                    uv -= update
                    if np.linalg.norm(update, ord=np.inf) <= 1.0e-11:
                        break
                if singular:
                    continue
                u, v = uv
                current = p00 + u * a + v * b + u * v * c
                residual = current - target
                jacobian = np.column_stack((a + v * c, b + u * c))
                cell_scale = max(float(np.ptp(corners_x)), float(np.ptp(corners_y)), 1.0)
                residual_tolerance = 1.0e-10 * cell_scale
                jacobian_tolerance = np.finfo(float).eps * cell_scale * cell_scale * 32.0
                inverse_is_valid = (
                    np.linalg.norm(residual, ord=np.inf) <= residual_tolerance
                    and abs(float(np.linalg.det(jacobian))) > jacobian_tolerance
                )
                if inverse_is_valid and -1.0e-8 <= u <= 1.0 + 1.0e-8 and -1.0e-8 <= v <= 1.0 + 1.0e-8:
                    z00 = z[row, col]
                    z10 = z[row, col + 1]
                    z11 = z[row + 1, col + 1]
                    z01 = z[row + 1, col]
                    values[point_index] = (
                        (1.0 - u) * (1.0 - v) * z00
                        + u * (1.0 - v) * z10
                        + u * v * z11
                        + (1.0 - u) * v * z01
                    )
                    found = True
                    break
        if not found:
            raise ValueError(
                f"Could not locate circle point ({px:.12g}, {py:.12g}) in the structured source grid."
            )
    return values


def interpolate_surface(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, points: np.ndarray
) -> np.ndarray:
    """Evaluate a structured-grid surface at XY points with bilinear interpolation."""

    if x.shape != y.shape or x.shape != z.shape:
        raise ValueError("x, y, and z must have identical shapes.")
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("points must be an N-by-2 array.")
    axes = _axis_coordinates(x, y)
    if axes is not None:
        return _interpolate_rectilinear(*axes, z, points)
    return _interpolate_curvilinear(x, y, z, points)


def radial_layer_fractions(num_layers: int, inflation_factor: float) -> np.ndarray:
    """Return outer-to-inner ring fractions with an exact edge-size ratio.

    The first interval touches the coarse outer contour and the last interval
    touches the hole.  Their ratio is ``inflation_factor``; intermediate widths
    follow a geometric progression, matching the intent of Cast3M's
    ``DINI=factor*density`` and ``DFIN=density`` controls.
    """

    if num_layers < 1:
        raise ValueError("num_el_fill must be >= 1.")
    if not np.isfinite(inflation_factor) or inflation_factor <= 0.0:
        raise ValueError("re_fact_hole must be a finite value > 0.")
    if num_layers == 1:
        return np.array((0.0, 1.0), dtype=float)
    ratio = inflation_factor ** (-1.0 / (num_layers - 1))
    widths = ratio ** np.arange(num_layers, dtype=float)
    fractions = np.concatenate((np.array((0.0,)), np.cumsum(widths)))
    fractions /= fractions[-1]
    return fractions


def _build_surface_fill_mesh(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    rings: Sequence[CircleRing],
    fractions: np.ndarray,
) -> SurfaceFillMesh:
    point_blocks: list[np.ndarray] = []
    quad_blocks: list[np.ndarray] = []
    point_offset = 0
    num_layers = len(fractions) - 1

    for ring in rings:
        outer = ring.outer_xy[np.newaxis, :, :]
        inner = ring.xy[np.newaxis, :, :]
        weights = fractions[:, np.newaxis, np.newaxis]
        layer_xy = (1.0 - weights) * outer + weights * inner
        flat_xy = layer_xy.reshape(-1, 2)
        flat_z = interpolate_surface(x, y, z, flat_xy)
        point_blocks.append(np.column_stack((flat_xy, flat_z)))

        points_per_ring = len(ring.xy)
        angular = np.arange(points_per_ring, dtype=int)
        angular_next = (angular + 1) % points_per_ring
        for layer in range(num_layers):
            outer_start = point_offset + layer * points_per_ring
            inner_start = point_offset + (layer + 1) * points_per_ring
            quad_blocks.append(
                np.column_stack(
                    (
                        outer_start + angular,
                        outer_start + angular_next,
                        inner_start + angular_next,
                        inner_start + angular,
                    )
                )
            )
        point_offset += (num_layers + 1) * points_per_ring

    return SurfaceFillMesh(
        points=np.vstack(point_blocks),
        quads=np.vstack(quad_blocks).astype(int, copy=False),
    )


def _nastran_float(value: float) -> str:
    field = f"{value:16.9E}"
    if len(field) > 16:
        raise ValueError(f"Coordinate cannot be represented in a 16-character NASTRAN field: {value}")
    return field


def validate_surface_fill_mesh(mesh: SurfaceFillMesh) -> None:
    """Reject non-finite, degenerate, or inconsistently oriented fill quads."""

    if mesh.points.ndim != 2 or mesh.points.shape[1] != 3:
        raise ValueError("Hole-fill points must be an N-by-3 array.")
    if mesh.quads.ndim != 2 or mesh.quads.shape[1] != 4:
        raise ValueError("Hole-fill elements must be an M-by-4 array.")
    if not np.isfinite(mesh.points).all():
        raise ValueError("Hole-fill mesh contains non-finite coordinates.")
    if mesh.quads.size == 0 or mesh.quads.min() < 0 or mesh.quads.max() >= len(mesh.points):
        raise ValueError("Hole-fill mesh connectivity is empty or out of bounds.")
    quad_xy = mesh.points[mesh.quads, :2]
    x_coord = quad_xy[:, :, 0]
    y_coord = quad_xy[:, :, 1]
    signed_area = 0.5 * np.sum(
        x_coord * np.roll(y_coord, -1, axis=1)
        - y_coord * np.roll(x_coord, -1, axis=1),
        axis=1,
    )
    area_scale = max(float(np.ptp(mesh.points[:, 0]) * np.ptp(mesh.points[:, 1])), 1.0)
    area_tolerance = np.finfo(float).eps * area_scale * 32.0
    if np.any(np.abs(signed_area) <= area_tolerance):
        raise ValueError("Hole-fill mesh contains a zero-area or degenerate quadrilateral.")
    if np.any(signed_area > 0.0) and np.any(signed_area < 0.0):
        raise ValueError("Hole-fill mesh contains inconsistently oriented quadrilaterals.")
    incoming = quad_xy - np.roll(quad_xy, 1, axis=1)
    outgoing = np.roll(quad_xy, -1, axis=1) - quad_xy
    corner_jacobians = (
        incoming[:, :, 0] * outgoing[:, :, 1]
        - incoming[:, :, 1] * outgoing[:, :, 0]
    )
    orientation = np.sign(signed_area)[:, np.newaxis]
    if np.any(corner_jacobians * orientation <= area_tolerance):
        raise ValueError(
            "Hole-fill mesh contains a concave, folded, or locally degenerate quadrilateral."
        )


def write_nastran_surface(path: Path, mesh: SurfaceFillMesh) -> None:
    """Write a minimal double-precision GRID/CQUAD4 Bulk Data surface."""

    validate_surface_fill_mesh(mesh)
    lines = ["BEGIN BULK\n", "MAT1           12.10E+117.85E+030.30    \n"]
    for node_id, (px, py, pz) in enumerate(mesh.points, start=1):
        lines.append(
            f"{'GRID*':<8}{node_id:>16}{0:>16}"
            f"{_nastran_float(float(px))}{_nastran_float(float(py))}{'*':<8}\n"
        )
        lines.append(f"{'*':<8}{_nastran_float(float(pz))}\n")
    for element_id, nodes in enumerate(mesh.quads, start=1):
        n1, n2, n3, n4 = (int(node) + 1 for node in nodes)
        lines.append(
            f"{'CQUAD4':<8}{element_id:>8}{1:>8}{n1:>8}{n2:>8}{n3:>8}{n4:>8}\n"
        )
    lines.append("ENDDATA\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="ascii", newline="\n")


def prepare_hole_fill_meshes(
    csv_x: Path,
    csv_y: Path,
    csv_zmin: Path,
    csv_zmax: Path,
    holes: Sequence[object],
    output_directory: Path,
    *,
    num_layers: int,
    inflation_factor: float,
    nelem_x: int = 1,
    nelem_y: int = 1,
    tolerance: float = 1.0e-10,
) -> HoleFillMeshSet:
    """Generate and write complete min/max/mean inflated hole-fill meshes."""

    x, y, zmin, zmax = load_surface_csvs(csv_x, csv_y, csv_zmin, csv_zmax)
    rings = detect_circle_rings(
        x,
        y,
        holes,
        tolerance=tolerance,
        nelem_x=nelem_x,
        nelem_y=nelem_y,
    )
    fractions = radial_layer_fractions(num_layers, inflation_factor)
    zmean = 0.5 * (zmin + zmax)
    min_mesh = _build_surface_fill_mesh(x, y, zmin, rings, fractions)
    max_mesh = _build_surface_fill_mesh(x, y, zmax, rings, fractions)
    mean_mesh = _build_surface_fill_mesh(x, y, zmean, rings, fractions)

    output_directory = Path(output_directory)
    min_path = output_directory / "python_hole_fill_min.bdf"
    max_path = output_directory / "python_hole_fill_max.bdf"
    mean_path = output_directory / "python_hole_fill_mean.bdf"
    write_nastran_surface(min_path, min_mesh)
    write_nastran_surface(max_path, max_mesh)
    write_nastran_surface(mean_path, mean_mesh)
    return HoleFillMeshSet(
        min_path=min_path,
        max_path=max_path,
        mean_path=mean_path,
        min_mesh=min_mesh,
        max_mesh=max_mesh,
        mean_mesh=mean_mesh,
        points_per_hole=tuple(len(ring.xy) for ring in rings),
        radial_fractions=fractions,
    )


def _nastran_mesh_reader(label: str, filename: str) -> tuple[str, ...]:
    return (
        f"    py_tab_{label} = LIRE 'NAS' '{filename}' ;",
        f"    py_ind_{label} = INDE (py_tab_{label} . 'MAILLAGES') ;",
        f"    fil_hi_{label} = VIDE 'MAILLAGE' ;",
        f"    REPETER py_bou_{label} (DIME py_ind_{label}) ;",
        f"        py_i_{label} = &py_bou_{label} ;",
        f"        fil_hi_{label} = fil_hi_{label} ET (py_tab_{label} . 'MAILLAGES' . (py_ind_{label} . py_i_{label})) ;",
        f"    FIN py_bou_{label} ;",
        f"    ELIM fil_hi_{label} re_tol ;",
    )


def replace_hole_interpolation_block(
    template_text: str, mesh_files: HoleFillMeshSet
) -> str:
    """Replace full-mesh interpolation with three bulk NASTRAN mesh reads."""

    if template_text.count(MAIN_HOLE_BLOCK_START) != 1 or template_text.count(MAIN_HOLE_BLOCK_END) != 1:
        raise ValueError(
            "The selected DGIBI must contain exactly one recognized baseline hole interpolation block."
        )
    start = template_text.find(MAIN_HOLE_BLOCK_START)
    end = template_text.find(MAIN_HOLE_BLOCK_END, start)
    if start < 0 or end < 0:
        raise ValueError(
            "The selected DGIBI does not contain the expected baseline hole interpolation block."
        )
    replacement_lines = [
        "* Python-side hole interpolation: retain one comparison surface for OPEN_CHAMP.",
        "surf_zmin_comp tab_hole_comp = CR_SURF co_po_x co_po_y co_po_zmin nelem_x nelem_y re_tol (PROG) (PROG) (PROG) ;",
        "",
        "* Bulk-load complete inflated hole-fill meshes generated in Python.",
        "SI (NON (EGA (DIME re_cr) 0)) ;",
    ]
    replacement_lines.extend(_nastran_mesh_reader("min", mesh_files.min_path.name))
    replacement_lines.extend(_nastran_mesh_reader("max", mesh_files.max_path.name))
    replacement_lines.extend(_nastran_mesh_reader("mean", mesh_files.mean_path.name))
    replacement_lines.extend(
        (
            "    surf_zmin = surf_zmin ET fil_hi_min ;",
            "    surf_zmax = surf_zmax ET fil_hi_max ;",
            "    surf_zmean = surf_zmean ET fil_hi_mean ;",
            "    ELIM surf_zmin re_tol ;",
            "    ELIM surf_zmax re_tol ;",
            "    ELIM surf_zmean re_tol ;",
            "FINSI ;",
            "",
        )
    )
    replacement = "\n".join(replacement_lines)
    return template_text[:start] + replacement + template_text[end:]


def build_python_holes_dgibi(
    template_text: str,
    params: object,
    csv_x: Path,
    csv_y: Path,
    csv_zmin: Path,
    csv_zmax: Path,
    patch_main_program,
    *,
    hole_mesh_directory: Path | None = None,
) -> tuple[str, HoleFillMeshSet | None]:
    """Patch parameters and generate bulk-readable inflated hole-fill meshes.

    ``patch_main_program`` is passed by the GUI wrapper so this module remains
    independent from the immutable baseline GUI module.
    """

    patched = patch_main_program(template_text, params)
    if not getattr(params, "holes_enabled", False) or not getattr(params, "holes", None):
        return patched, None
    if hole_mesh_directory is None:
        raise ValueError("hole_mesh_directory is required when holes are enabled.")
    mesh_files = prepare_hole_fill_meshes(
        csv_x,
        csv_y,
        csv_zmin,
        csv_zmax,
        getattr(params, "holes"),
        hole_mesh_directory,
        num_layers=int(getattr(params, "num_el_fill")),
        inflation_factor=float(getattr(params, "re_fact_hole")),
        nelem_x=int(getattr(params, "nelem_x")),
        nelem_y=int(getattr(params, "nelem_y")),
        tolerance=float(getattr(params, "re_tol", 1.0e-10)),
    )
    return replace_hole_interpolation_block(patched, mesh_files), mesh_files


def generated_program_uses_python_holes(program_text: str) -> bool:
    """Return whether a generated program removed the costly calls."""

    return (
        "Bulk-load complete inflated hole-fill meshes generated in Python" in program_text
        and "INT_COMP surf_zmin_comp" not in program_text
        and "DISPLACE surf_zmin" not in program_text
        and "REGL (-1*num_el_fill)" not in program_text
        and "LIRE 'NAS' 'python_hole_fill_min.bdf'" in program_text
        and "py_min_h1_p1 = POIN" not in program_text
    )
