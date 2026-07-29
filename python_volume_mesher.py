"""Source-free Python HEXA8 meshing for reconstructed crack surfaces.

The maintained Cast3M program remains available as a reference backend.  This
module reproduces its active meshing path directly in NumPy:

* bilinear subdivision of every structured surface cell;
* conformal, inflated fills around supported internal hole shapes;
* two graded HEXA8 blocks through the crack opening;
* optional graded inlet and outlet chambers; and
* the same named volume and boundary BDF exports.

No Cast3M source, Cast3M executable, or Gmsh executable is used here.  The
fixed-count grading follows Cast3M's ``DECOUP`` and ``VOLUME`` algorithms,
including their normalized endpoint-density convention.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from chamber_geometry import ChamberParameters
from python_hole_interpolation import (
    HoleGeometry,
    detect_hole_rings,
    interpolate_surface,
    normalize_hole_geometry,
    radial_layer_fractions,
)

LogFunction = Callable[[str], None]


@dataclass(frozen=True)
class SurfaceTopology:
    """One conformal XY quadrilateral topology shared by all crack surfaces."""

    xy: np.ndarray
    quads: np.ndarray
    outer_edges: dict[str, np.ndarray]
    hole_edges: tuple[np.ndarray, ...]
    points_per_hole: tuple[int, ...]
    radial_fractions: np.ndarray


@dataclass(frozen=True)
class PythonVolumeMesh:
    """Complete source-free mesh and all exportable named subsets."""

    points: np.ndarray
    hexes: np.ndarray
    inlet_hexes: np.ndarray
    outlet_hexes: np.ndarray
    boundaries: dict[str, np.ndarray]
    topology: SurfaceTopology
    grading: dict[str, object]
    counts: dict[str, int]


@dataclass(frozen=True)
class PythonMeshWriteResult:
    """Files and measurements produced by one Python-only mesh run."""

    mesh: PythonVolumeMesh
    elapsed_seconds: float
    volume_bdf: Path
    med_path: Path | None
    preview_path: Path
    written_bdfs: tuple[Path, ...]
    quality: dict[str, float | int | bool]


def _quantized_xy(x: float, y: float, tolerance: float) -> tuple[int, int]:
    return int(round(x / tolerance)), int(round(y / tolerance))


def _cell_hits_hole(
    corners: np.ndarray,
    holes: Sequence[HoleGeometry],
    *,
    margin: float = 1.05,
) -> bool:
    for hole in holes:
        inflated = margin * hole.selection_radius
        inside = (
            (corners[:, 0] > hole.cx - inflated)
            & (corners[:, 0] < hole.cx + inflated)
            & (corners[:, 1] > hole.cy - inflated)
            & (corners[:, 1] < hole.cy + inflated)
        )
        if bool(np.any(inside)):
            return True
    return False


def _bilinear_point(corners: np.ndarray, u: float, v: float) -> np.ndarray:
    p00, p01, p11, p10 = corners
    return (
        (1.0 - u) * (1.0 - v) * p00
        + (1.0 - u) * v * p01
        + u * v * p11
        + u * (1.0 - v) * p10
    )


def _boundary_edges(quads: np.ndarray) -> np.ndarray:
    """Return consistently oriented boundary edges of an oriented quad mesh."""

    edge_map: dict[tuple[int, int], tuple[int, int] | None] = {}
    for n0, n1, n2, n3 in quads:
        for start, end in ((n0, n1), (n1, n2), (n2, n3), (n3, n0)):
            key = (int(min(start, end)), int(max(start, end)))
            if key in edge_map:
                edge_map[key] = None
            else:
                edge_map[key] = (int(start), int(end))
    return np.asarray(
        [edge for edge in edge_map.values() if edge is not None],
        dtype=np.int64,
    )


def build_surface_topology(
    x: np.ndarray,
    y: np.ndarray,
    holes: Sequence[object],
    *,
    nelem_x: int,
    nelem_y: int,
    hole_radial_cells: int,
    hole_outer_inner_ratio: float,
    tolerance: float,
) -> SurfaceTopology:
    """Reproduce ``CR_SURF`` plus the active Python hole-fill topology."""

    if x.shape != y.shape or x.ndim != 2 or min(x.shape) < 2:
        raise ValueError("x and y must be equally shaped 2D grids.")
    if nelem_x < 1 or nelem_y < 1:
        raise ValueError("elements_x and elements_y must be >= 1.")
    if tolerance <= 0.0 or not math.isfinite(tolerance):
        raise ValueError("geometric_tolerance must be finite and > 0.")

    normalized_holes = tuple(
        normalize_hole_geometry(hole, index)
        for index, hole in enumerate(holes, start=1)
    )
    rings = detect_hole_rings(
        x,
        y,
        normalized_holes,
        tolerance=tolerance,
        nelem_x=nelem_x,
        nelem_y=nelem_y,
    )
    radial_fractions = radial_layer_fractions(
        hole_radial_cells,
        hole_outer_inner_ratio,
    )

    points: list[tuple[float, float]] = []
    quads: list[tuple[int, int, int, int]] = []
    lookup: dict[tuple[int, int], int] = {}

    def node_id(point: np.ndarray) -> int:
        key = _quantized_xy(float(point[0]), float(point[1]), tolerance)
        existing = lookup.get(key)
        if existing is not None:
            current = np.asarray(points[existing])
            if float(np.linalg.norm(current - point, ord=np.inf)) <= tolerance:
                return existing
        identifier = len(points)
        points.append((float(point[0]), float(point[1])))
        lookup[key] = identifier
        return identifier

    rows, columns = x.shape
    # Cast3M's CR_SURF applies nelem_x along table rows (physical Y in the
    # bundled grids) and nelem_y between the ruled lines (physical X).
    for row in range(rows - 1):
        for column in range(columns - 1):
            corners = np.asarray(
                (
                    (x[row, column], y[row, column]),
                    (x[row + 1, column], y[row + 1, column]),
                    (x[row + 1, column + 1], y[row + 1, column + 1]),
                    (x[row, column + 1], y[row, column + 1]),
                ),
                dtype=float,
            )
            if _cell_hits_hole(corners, normalized_holes):
                continue
            local = np.empty((nelem_x + 1, nelem_y + 1), dtype=np.int64)
            for row_subdivision in range(nelem_x + 1):
                v = row_subdivision / nelem_x
                for column_subdivision in range(nelem_y + 1):
                    u = column_subdivision / nelem_y
                    local[row_subdivision, column_subdivision] = node_id(
                        _bilinear_point(corners, u, v)
                    )
            for row_subdivision in range(nelem_x):
                for column_subdivision in range(nelem_y):
                    quads.append(
                        (
                            int(local[row_subdivision, column_subdivision]),
                            int(local[row_subdivision, column_subdivision + 1]),
                            int(local[row_subdivision + 1, column_subdivision + 1]),
                            int(local[row_subdivision + 1, column_subdivision]),
                        )
                    )

    hole_edges: list[np.ndarray] = []
    for ring in rings:
        layer_ids = np.empty(
            (len(radial_fractions), len(ring.xy)),
            dtype=np.int64,
        )
        for layer, fraction in enumerate(radial_fractions):
            layer_xy = (
                (1.0 - fraction) * ring.outer_xy
                + fraction * ring.xy
            )
            layer_ids[layer] = np.fromiter(
                (node_id(point) for point in layer_xy),
                dtype=np.int64,
                count=len(layer_xy),
            )
        angular_next = np.roll(np.arange(len(ring.xy), dtype=np.int64), -1)
        for layer in range(len(radial_fractions) - 1):
            quads.extend(
                zip(
                    layer_ids[layer],
                    layer_ids[layer, angular_next],
                    layer_ids[layer + 1, angular_next],
                    layer_ids[layer + 1],
                    strict=True,
                )
            )
        # A +Z-oriented annulus traverses its inner edge clockwise.
        inner = layer_ids[-1]
        hole_edges.append(
            np.column_stack((inner[angular_next], inner)).astype(
                np.int64,
                copy=False,
            )
        )

    xy = np.asarray(points, dtype=float)
    quad_array = np.asarray(quads, dtype=np.int64)
    if quad_array.size == 0:
        raise ValueError("Surface construction produced no quadrilateral elements.")

    boundary = _boundary_edges(quad_array)
    xmin, xmax = float(np.min(xy[:, 0])), float(np.max(xy[:, 0]))
    ymin, ymax = float(np.min(xy[:, 1])), float(np.max(xy[:, 1]))
    outer_edges: dict[str, np.ndarray] = {}
    for name, axis, value in (
        ("xmin", 0, xmin),
        ("xmax", 0, xmax),
        ("ymin", 1, ymin),
        ("ymax", 1, ymax),
    ):
        mask = np.all(
            np.abs(xy[boundary, axis] - value) <= tolerance * 10.0,
            axis=1,
        )
        outer_edges[name] = boundary[mask]

    expected_boundary_edges = sum(len(edges) for edges in outer_edges.values())
    expected_boundary_edges += sum(len(edges) for edges in hole_edges)
    if expected_boundary_edges != len(boundary):
        raise RuntimeError(
            "The generated surface boundary could not be classified into "
            "the four outer sides and configured holes."
        )

    return SurfaceTopology(
        xy=xy,
        quads=quad_array,
        outer_edges=outer_edges,
        hole_edges=tuple(hole_edges),
        points_per_hole=tuple(len(ring.xy) for ring in rings),
        radial_fractions=radial_fractions,
    )


def cast3m_fixed_count_fractions(
    element_count: int,
    start_density: float,
    end_density: float,
    interval_length: float,
) -> tuple[np.ndarray, float]:
    """Return the exact fixed-count fractions used by DECOUP/VOLUME.

    ``start_density`` and ``end_density`` are Cast3M's DINI and DFIN values.
    The ratio is derived from their normalized difference, not directly from
    their quotient.  ``VOLUME`` multiplies the initial width by the ratio
    before accumulating its first layer.
    """

    if element_count < 1:
        raise ValueError("A graded interval requires at least one element.")
    values = (start_density, end_density, interval_length)
    if not np.isfinite(values).all() or min(values) <= 0.0:
        raise ValueError("Densities and interval length must be finite and > 0.")

    density_1 = abs(start_density / interval_length)
    density_2 = abs(end_density / interval_length)
    auxiliary = abs((density_1 - density_2) ** 2 / 2.0)
    root = math.sqrt(auxiliary * (2.0 + auxiliary))
    ratio = (
        1.0 + auxiliary - root
        if density_2 < density_1
        else 1.0 + auxiliary + root
    )
    progression = abs(ratio - 1.0) > 1.0e-5
    if progression:
        first_before_shift = (1.0 - ratio) / (
            (1.0 - ratio**element_count) * ratio
        )
    else:
        first_before_shift = 1.0 / element_count
    widths = first_before_shift * ratio ** np.arange(
        1,
        element_count + 1,
        dtype=float,
    )
    fractions = np.concatenate((np.array((0.0,)), np.cumsum(widths)))
    fractions[-1] = 1.0
    if np.any(np.diff(fractions) <= 0.0):
        raise ValueError("Cast3M-equivalent grading produced a non-positive layer.")
    return fractions, ratio


def _grid_quads(node_grid: np.ndarray) -> np.ndarray:
    """Create +normal quads from a 2D node grid (row then column)."""

    return np.column_stack(
        (
            node_grid[:-1, :-1].ravel(),
            node_grid[:-1, 1:].ravel(),
            node_grid[1:, 1:].ravel(),
            node_grid[1:, :-1].ravel(),
        )
    ).astype(np.int64, copy=False)


def _grid_hexes(node_grid: np.ndarray) -> np.ndarray:
    """Create positively oriented HEXA8 cells from a Z,Y,X node grid."""

    return np.column_stack(
        (
            node_grid[:-1, :-1, :-1].ravel(),
            node_grid[:-1, :-1, 1:].ravel(),
            node_grid[:-1, 1:, 1:].ravel(),
            node_grid[:-1, 1:, :-1].ravel(),
            node_grid[1:, :-1, :-1].ravel(),
            node_grid[1:, :-1, 1:].ravel(),
            node_grid[1:, 1:, 1:].ravel(),
            node_grid[1:, 1:, :-1].ravel(),
        )
    ).astype(np.int64, copy=False)


def _reverse_quads(quads: np.ndarray) -> np.ndarray:
    return quads[:, (0, 3, 2, 1)]


def _extruded_edge_quads(
    edges: np.ndarray,
    layer_node_ids: np.ndarray,
) -> np.ndarray:
    blocks = []
    for layer in range(layer_node_ids.shape[0] - 1):
        lower = layer_node_ids[layer]
        upper = layer_node_ids[layer + 1]
        blocks.append(
            np.column_stack(
                (
                    lower[edges[:, 0]],
                    lower[edges[:, 1]],
                    upper[edges[:, 1]],
                    upper[edges[:, 0]],
                )
            )
        )
    return np.vstack(blocks).astype(np.int64, copy=False)


class _MeshBlocks:
    """Append-only point and element blocks with stable global node IDs."""

    def __init__(self, initial_points: np.ndarray) -> None:
        self.point_blocks = [np.asarray(initial_points, dtype=float)]
        self.point_count = len(initial_points)
        self.hex_blocks: list[np.ndarray] = []

    def append_points(self, points: np.ndarray) -> np.ndarray:
        values = np.asarray(points, dtype=float).reshape(-1, 3)
        start = self.point_count
        self.point_blocks.append(values)
        self.point_count += len(values)
        return np.arange(start, self.point_count, dtype=np.int64)

    def points(self) -> np.ndarray:
        return np.vstack(self.point_blocks)

    def hexes(self) -> np.ndarray:
        return np.vstack(self.hex_blocks).astype(np.int64, copy=False)


@dataclass(frozen=True)
class _ChamberMesh:
    hexes: np.ndarray
    all_surface: np.ndarray
    interface: np.ndarray
    interface_extension: np.ndarray
    outer: np.ndarray
    top: np.ndarray
    bottom: np.ndarray
    xmin: np.ndarray
    xmax: np.ndarray


def _build_chamber(
    blocks: _MeshBlocks,
    *,
    crack_layer_ids: np.ndarray,
    crack_layer_z: np.ndarray,
    boundary_indices: np.ndarray,
    boundary_y: float,
    direction: int,
    length: float,
    height: float,
    length_elements: int,
    height_elements: int,
    length_ratio: float,
    height_ratio: float,
) -> tuple[_ChamberMesh, dict[str, object]]:
    """Build one chamber while sharing its crack-interface nodes exactly."""

    x_values = blocks.point_blocks[0][boundary_indices, 0]
    order = np.argsort(x_values, kind="stable")
    boundary_indices = boundary_indices[order]
    x_values = x_values[order]
    if np.any(np.diff(x_values) <= 0.0):
        raise ValueError("The crack end face must have strictly increasing X nodes.")

    length_density = length / length_elements
    length_fractions, length_progression = cast3m_fixed_count_fractions(
        length_elements,
        length_density,
        length_ratio * length_density,
        length,
    )
    if direction < 0:
        y_values = boundary_y - length * length_fractions[::-1]
        interface_column = length_elements
    else:
        y_values = boundary_y + length * length_fractions
        interface_column = 0

    z_layer_count = crack_layer_ids.shape[0]
    x_count = len(boundary_indices)
    base_ids = np.empty(
        (z_layer_count, length_elements + 1, x_count),
        dtype=np.int64,
    )
    base_ids[:, interface_column, :] = crack_layer_ids[:, boundary_indices]
    z_values = crack_layer_z[:, boundary_indices]
    for length_index, y_value in enumerate(y_values):
        if length_index == interface_column:
            continue
        coordinates = np.column_stack(
            (
                np.tile(x_values, z_layer_count),
                np.full(z_layer_count * x_count, y_value),
                z_values.ravel(),
            )
        )
        base_ids[:, length_index, :] = blocks.append_points(coordinates).reshape(
            z_layer_count,
            x_count,
        )

    half_height = 0.5 * height
    half_height_elements = height_elements // 2
    height_density = half_height / half_height_elements
    height_fractions, height_progression = cast3m_fixed_count_fractions(
        half_height_elements,
        height_density,
        height_ratio * height_density,
        half_height,
    )

    upper_ids = np.empty(
        (half_height_elements + 1, length_elements + 1, x_count),
        dtype=np.int64,
    )
    upper_ids[0] = base_ids[-1]
    upper_base_z = z_values[-1]
    for height_index in range(1, half_height_elements + 1):
        coordinates = np.column_stack(
            (
                np.tile(x_values, length_elements + 1),
                np.repeat(y_values, x_count),
                np.tile(
                    upper_base_z + half_height * height_fractions[height_index],
                    length_elements + 1,
                ),
            )
        )
        upper_ids[height_index] = blocks.append_points(coordinates).reshape(
            length_elements + 1,
            x_count,
        )

    lower_ids = np.empty_like(upper_ids)
    lower_ids[-1] = base_ids[0]
    lower_base_z = z_values[0]
    for height_index in range(half_height_elements):
        fraction_from_base = height_fractions[
            half_height_elements - height_index
        ]
        coordinates = np.column_stack(
            (
                np.tile(x_values, length_elements + 1),
                np.repeat(y_values, x_count),
                np.tile(
                    lower_base_z - half_height * fraction_from_base,
                    length_elements + 1,
                ),
            )
        )
        lower_ids[height_index] = blocks.append_points(coordinates).reshape(
            length_elements + 1,
            x_count,
        )

    base_hexes = _grid_hexes(base_ids)
    upper_hexes = _grid_hexes(upper_ids)
    lower_hexes = _grid_hexes(lower_ids)
    chamber_hexes = np.vstack((base_hexes, upper_hexes, lower_hexes))

    full_ids = np.concatenate(
        (lower_ids[:-1], base_ids, upper_ids[1:]),
        axis=0,
    )
    interface = _grid_quads(full_ids[:, interface_column, :])
    outer_column = 0 if interface_column else length_elements
    outer = _grid_quads(full_ids[:, outer_column, :])
    if direction < 0:
        interface = _reverse_quads(interface)
    else:
        outer = _reverse_quads(outer)

    xmin = _reverse_quads(_grid_quads(full_ids[:, :, 0]))
    xmax = _grid_quads(full_ids[:, :, -1])
    top = _grid_quads(upper_ids[-1])
    bottom = _reverse_quads(_grid_quads(lower_ids[0]))

    # Cast3M's chamber boundary exports carry the opposite winding on the two
    # Y faces and both X faces.  Preserve that observable BDF/STL convention,
    # including on the interface extensions included in surf_all.
    interface = _reverse_quads(interface)
    outer = _reverse_quads(outer)
    xmin = _reverse_quads(xmin)
    xmax = _reverse_quads(xmax)

    rows_per_height_interval = x_count - 1
    lower_extension_count = half_height_elements * rows_per_height_interval
    upper_extension_count = half_height_elements * rows_per_height_interval
    interface_extension = np.vstack(
        (
            interface[:lower_extension_count],
            interface[-upper_extension_count:],
        )
    )
    # The volume-derived Cast3M ``CONT`` used for ``*_all`` carries the
    # opposite top/bottom winding from the separately named surface exports.
    all_surface = np.vstack(
        (
            interface,
            outer,
            xmin,
            xmax,
            _reverse_quads(top),
            _reverse_quads(bottom),
        )
    )
    return (
        _ChamberMesh(
            hexes=chamber_hexes,
            all_surface=all_surface,
            interface=interface,
            interface_extension=interface_extension,
            outer=outer,
            top=top,
            bottom=bottom,
            xmin=xmin,
            xmax=xmax,
        ),
        {
            "length_fractions": length_fractions.tolist(),
            "height_half_fractions": height_fractions.tolist(),
            "length_progression_ratio": length_progression,
            "height_progression_ratio": height_progression,
        },
    )


def build_python_volume_mesh(
    x: np.ndarray,
    y: np.ndarray,
    zmin: np.ndarray,
    zmax: np.ndarray,
    params: object,
) -> PythonVolumeMesh:
    """Build the complete crack and optional chamber mesh in memory."""

    arrays = tuple(np.asarray(values, dtype=float) for values in (x, y, zmin, zmax))
    x, y, zmin, zmax = arrays
    if len({values.shape for values in arrays}) != 1:
        raise ValueError("x, y, zmin, and zmax must have identical shapes.")
    if not all(np.isfinite(values).all() for values in arrays):
        raise ValueError("Surface grids contain non-finite coordinates.")
    aperture_grid = zmax - zmin
    if np.any(aperture_grid <= 0.0):
        raise ValueError(
            "Python-only volume meshing requires strictly positive zmax-zmin "
            "at every structured-grid point."
        )

    holes = (
        getattr(params, "hole_shapes", getattr(params, "holes", ()))
        if getattr(params, "holes_enabled", False)
        else ()
    )
    topology = build_surface_topology(
        x,
        y,
        holes,
        nelem_x=int(getattr(params, "nelem_x")),
        nelem_y=int(getattr(params, "nelem_y")),
        hole_radial_cells=int(getattr(params, "num_el_fill")),
        hole_outer_inner_ratio=float(getattr(params, "re_fact_hole")),
        tolerance=float(getattr(params, "re_tol")),
    )
    surface_zmin = interpolate_surface(x, y, zmin, topology.xy)
    surface_zmax = interpolate_surface(x, y, zmax, topology.xy)
    surface_zmean = 0.5 * (surface_zmin + surface_zmax)
    surface_aperture = surface_zmax - surface_zmin

    # OPEN_CHAMP samples lower-left source-cell values and MAXI selects the
    # largest original opening as the requested Z density.
    z_density = float(np.max(aperture_grid[:-1, :-1]))
    mean_half_opening = float(
        np.mean(
            (surface_zmean - surface_zmin)[topology.quads]
        )
    )
    z_elements = int(getattr(params, "nelem_z"))
    z_factor = float(getattr(params, "re_fact_z"))
    lower_fractions, lower_progression = cast3m_fixed_count_fractions(
        z_elements,
        z_density,
        z_factor * z_density,
        mean_half_opening,
    )
    upper_fractions, upper_progression = cast3m_fixed_count_fractions(
        z_elements,
        z_factor * z_density,
        z_density,
        mean_half_opening,
    )
    lower_layers = (
        surface_zmin[np.newaxis, :]
        + lower_fractions[:, np.newaxis]
        * (surface_zmean - surface_zmin)[np.newaxis, :]
    )
    upper_layers = (
        surface_zmean[np.newaxis, :]
        + upper_fractions[:, np.newaxis]
        * (surface_zmax - surface_zmean)[np.newaxis, :]
    )
    crack_layer_z = np.vstack((lower_layers, upper_layers[1:]))
    surface_node_count = len(topology.xy)
    crack_points = np.column_stack(
        (
            np.tile(topology.xy[:, 0], len(crack_layer_z)),
            np.tile(topology.xy[:, 1], len(crack_layer_z)),
            crack_layer_z.ravel(),
        )
    )
    crack_layer_ids = np.arange(
        len(crack_points),
        dtype=np.int64,
    ).reshape(len(crack_layer_z), surface_node_count)
    crack_hexes = np.column_stack(
        (
            crack_layer_ids[:-1, topology.quads[:, 0]].ravel(),
            crack_layer_ids[:-1, topology.quads[:, 1]].ravel(),
            crack_layer_ids[:-1, topology.quads[:, 2]].ravel(),
            crack_layer_ids[:-1, topology.quads[:, 3]].ravel(),
            crack_layer_ids[1:, topology.quads[:, 0]].ravel(),
            crack_layer_ids[1:, topology.quads[:, 1]].ravel(),
            crack_layer_ids[1:, topology.quads[:, 2]].ravel(),
            crack_layer_ids[1:, topology.quads[:, 3]].ravel(),
        )
    ).astype(np.int64, copy=False)

    blocks = _MeshBlocks(crack_points)
    blocks.hex_blocks.append(crack_hexes)
    boundaries: dict[str, np.ndarray] = {
        "castem_mesh_surf_min": topology.quads.copy(),
        "castem_mesh_surf_mean": (
            topology.quads + z_elements * surface_node_count
        ),
        "castem_mesh_surf_max": (
            topology.quads + 2 * z_elements * surface_node_count
        ),
    }
    for side in ("xmin", "xmax", "ymin", "ymax"):
        boundaries[f"castem_mesh_surf_{side}"] = _extruded_edge_quads(
            topology.outer_edges[side],
            crack_layer_ids,
        )
    for index, edges in enumerate(topology.hole_edges, start=1):
        boundaries[f"castem_mesh_surf_trou_{index}"] = _extruded_edge_quads(
            edges,
            crack_layer_ids,
        )

    chambers = getattr(params, "chambers", ChamberParameters())
    chambers = chambers if isinstance(chambers, ChamberParameters) else ChamberParameters()
    chambers.validated()
    inlet_hexes = np.empty((0, 8), dtype=np.int64)
    outlet_hexes = np.empty((0, 8), dtype=np.int64)
    chamber_grading: dict[str, object] = {}
    exterior_parts = [
        boundaries["castem_mesh_surf_min"],
        _reverse_quads(boundaries["castem_mesh_surf_max"]),
        _reverse_quads(boundaries["castem_mesh_surf_xmin"]),
        _reverse_quads(boundaries["castem_mesh_surf_xmax"]),
        *(
            _reverse_quads(
                boundaries[f"castem_mesh_surf_trou_{index}"]
            )
            for index in range(1, len(topology.hole_edges) + 1)
        ),
    ]

    if chambers.enabled:
        ymin_indices = np.unique(topology.outer_edges["ymin"])
        ymax_indices = np.unique(topology.outer_edges["ymax"])
        inlet, inlet_grading = _build_chamber(
            blocks,
            crack_layer_ids=crack_layer_ids,
            crack_layer_z=crack_layer_z,
            boundary_indices=ymin_indices,
            boundary_y=float(np.min(topology.xy[:, 1])),
            direction=-1,
            length=chambers.inlet_length,
            height=chambers.height,
            length_elements=chambers.inlet_length_elements,
            height_elements=chambers.inlet_height_elements,
            length_ratio=chambers.inlet_length_ratio,
            height_ratio=chambers.inlet_height_ratio,
        )
        outlet, outlet_grading = _build_chamber(
            blocks,
            crack_layer_ids=crack_layer_ids,
            crack_layer_z=crack_layer_z,
            boundary_indices=ymax_indices,
            boundary_y=float(np.max(topology.xy[:, 1])),
            direction=1,
            length=chambers.outlet_length,
            height=chambers.height,
            length_elements=chambers.outlet_length_elements,
            height_elements=chambers.outlet_height_elements,
            length_ratio=chambers.outlet_length_ratio,
            height_ratio=chambers.outlet_height_ratio,
        )
        inlet_hexes = inlet.hexes
        outlet_hexes = outlet.hexes
        blocks.hex_blocks.extend((inlet_hexes, outlet_hexes))
        for prefix, chamber in (("inlet", inlet), ("outlet", outlet)):
            boundaries[f"castem_mesh_surf_{prefix}_all"] = chamber.all_surface
            boundaries[f"castem_mesh_surf_{prefix}_interface"] = chamber.interface
            boundaries[f"castem_mesh_surf_{prefix}_outer"] = chamber.outer
            boundaries[f"castem_mesh_surf_{prefix}_top"] = chamber.top
            boundaries[f"castem_mesh_surf_{prefix}_bottom"] = chamber.bottom
            boundaries[f"castem_mesh_surf_{prefix}_xmin"] = chamber.xmin
            boundaries[f"castem_mesh_surf_{prefix}_xmax"] = chamber.xmax
        exterior_parts.extend(
            (
                inlet.interface_extension,
                inlet.outer,
                inlet.xmin,
                inlet.xmax,
                _reverse_quads(inlet.top),
                _reverse_quads(inlet.bottom),
                outlet.interface_extension,
                outlet.outer,
                outlet.xmin,
                outlet.xmax,
                _reverse_quads(outlet.top),
                _reverse_quads(outlet.bottom),
            )
        )
        boundaries["castem_mesh_surf_all"] = np.vstack(exterior_parts)
        chamber_grading = {
            "inlet": inlet_grading,
            "outlet": outlet_grading,
        }
    else:
        exterior_parts.extend(
            (
                boundaries["castem_mesh_surf_ymin"],
                boundaries["castem_mesh_surf_ymax"],
            )
        )

    points = blocks.points()
    hexes = blocks.hexes()
    counts = {
        "points": len(points),
        "hexa8": len(hexes),
        "surface_quads": len(topology.quads),
        "crack_hexa8": len(crack_hexes),
        "inlet_hexa8": len(inlet_hexes),
        "outlet_hexa8": len(outlet_hexes),
        "exterior_quads": len(np.vstack(exterior_parts)),
    }
    grading = {
        "z_density": z_density,
        "mean_half_opening": mean_half_opening,
        "lower_fractions": lower_fractions.tolist(),
        "upper_fractions": upper_fractions.tolist(),
        "lower_progression_ratio": lower_progression,
        "upper_progression_ratio": upper_progression,
        "chambers": chamber_grading,
        "surface_aperture_min": float(np.min(surface_aperture)),
        "surface_aperture_max": float(np.max(surface_aperture)),
    }
    return PythonVolumeMesh(
        points=points,
        hexes=hexes,
        inlet_hexes=inlet_hexes,
        outlet_hexes=outlet_hexes,
        boundaries=boundaries,
        topology=topology,
        grading=grading,
        counts=counts,
    )


def _nastran_float(value: float) -> str:
    field = f"{value:16.9E}"
    if len(field) > 16:
        raise ValueError(
            f"Coordinate cannot fit a 16-character NASTRAN field: {value}"
        )
    return field


def _write_grid(stream, node_id: int, point: np.ndarray) -> None:
    px, py, pz = (float(value) for value in point)
    stream.write(
        f"{'GRID*':<8}{node_id:>16}{0:>16}"
        f"{_nastran_float(px)}{_nastran_float(py)}{'*':<8}\n"
    )
    stream.write(f"{'*':<8}{_nastran_float(pz)}\n")


def write_volume_bdf(
    path: Path,
    points: np.ndarray,
    hexes: np.ndarray,
) -> None:
    """Write a standalone GRID/CHEXA NASTRAN bulk-data file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write("BEGIN BULK\n")
        stream.write("MAT1           12.10E+117.85E+030.30    \n")
        for node_index, point in enumerate(points, start=1):
            _write_grid(stream, node_index, point)
        for element_index, nodes in enumerate(hexes, start=1):
            values = [int(node) + 1 for node in nodes]
            stream.write(
                f"{'CHEXA':<8}{element_index:>8}{1:>8}"
                + "".join(f"{node:>8}" for node in values[:6])
                + "+\n"
            )
            stream.write(f"{'+':<8}{values[6]:>8}{values[7]:>8}\n")
        stream.write("ENDDATA\n")


def write_surface_bdf(
    path: Path,
    points: np.ndarray,
    quads: np.ndarray,
) -> None:
    """Write a compact standalone boundary BDF with stable global node IDs."""

    referenced = np.unique(quads)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write("BEGIN BULK\n")
        stream.write("MAT1           12.10E+117.85E+030.30    \n")
        for node in referenced:
            _write_grid(stream, int(node) + 1, points[int(node)])
        for element_index, nodes in enumerate(quads, start=1):
            values = [int(node) + 1 for node in nodes]
            stream.write(
                f"{'CQUAD4':<8}{element_index:>8}{1:>8}"
                + "".join(f"{node:>8}" for node in values)
                + "\n"
            )
        stream.write("ENDDATA\n")


def _write_med(path: Path, mesh: PythonVolumeMesh) -> None:
    try:
        import meshio
    except ImportError as exc:
        raise RuntimeError(
            "MED export in Python-only mode requires meshio. "
            "Install the repository requirements and run again."
        ) from exc
    meshio.write(
        path,
        meshio.Mesh(
            points=mesh.points,
            cells=[("hexahedron", mesh.hexes)],
        ),
        file_format="med",
    )


def write_mesh_preview(
    path: Path,
    mesh: PythonVolumeMesh,
    *,
    maximum_quads: int = 6000,
) -> None:
    """Write a dependency-local PNG preview, avoiding an external Gmsh viewer."""

    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    exterior = mesh.boundaries.get("castem_mesh_surf_all")
    if exterior is None:
        names = (
            "castem_mesh_surf_min",
            "castem_mesh_surf_max",
            "castem_mesh_surf_xmin",
            "castem_mesh_surf_xmax",
            "castem_mesh_surf_ymin",
            "castem_mesh_surf_ymax",
        )
        exterior = np.vstack(
            [
                mesh.boundaries[name]
                for name in names
                if name in mesh.boundaries
            ]
            + [
                quads
                for name, quads in mesh.boundaries.items()
                if name.startswith("castem_mesh_surf_trou_")
            ]
        )
    stride = max(1, math.ceil(len(exterior) / maximum_quads))
    polygons = mesh.points[exterior[::stride]]
    figure = plt.figure(figsize=(10.5, 6.8), constrained_layout=True)
    axis = figure.add_subplot(111, projection="3d")
    collection = Poly3DCollection(
        polygons,
        linewidths=0.15,
        edgecolors=(0.09, 0.20, 0.30, 0.28),
        facecolors=(0.19, 0.62, 0.82, 0.40),
    )
    axis.add_collection3d(collection)
    minimum = np.min(mesh.points, axis=0)
    maximum = np.max(mesh.points, axis=0)
    centre = 0.5 * (minimum + maximum)
    radius = 0.52 * float(np.max(maximum - minimum))
    axis.set_xlim(centre[0] - radius, centre[0] + radius)
    axis.set_ylim(centre[1] - radius, centre[1] + radius)
    axis.set_zlim(centre[2] - radius, centre[2] + radius)
    axis.set_xlabel("X")
    axis.set_ylabel("Y")
    axis.set_zlabel("Z")
    axis.set_title("Python-only crack volume mesh")
    axis.view_init(elev=23, azim=-52)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180)
    plt.close(figure)


def hexa8_quality(
    points: np.ndarray,
    hexes: np.ndarray,
    *,
    chunk_size: int = 20_000,
) -> dict[str, float | int | bool]:
    """Evaluate Jacobians at all eight 2x2x2 Gauss points."""

    local_nodes = np.asarray(
        (
            (-1.0, -1.0, -1.0),
            (1.0, -1.0, -1.0),
            (1.0, 1.0, -1.0),
            (-1.0, 1.0, -1.0),
            (-1.0, -1.0, 1.0),
            (1.0, -1.0, 1.0),
            (1.0, 1.0, 1.0),
            (-1.0, 1.0, 1.0),
        )
    )
    gauss_value = 1.0 / math.sqrt(3.0)
    gauss_points = gauss_value * local_nodes
    gradients = np.empty((8, 8, 3), dtype=float)
    for gauss_index, (xi, eta, zeta) in enumerate(gauss_points):
        sx, sy, sz = local_nodes.T
        gradients[gauss_index, :, 0] = (
            sx * (1.0 + sy * eta) * (1.0 + sz * zeta) / 8.0
        )
        gradients[gauss_index, :, 1] = (
            sy * (1.0 + sx * xi) * (1.0 + sz * zeta) / 8.0
        )
        gradients[gauss_index, :, 2] = (
            sz * (1.0 + sx * xi) * (1.0 + sy * eta) / 8.0
        )

    minimum_determinant = math.inf
    maximum_determinant = -math.inf
    minimum_scaled = math.inf
    nonpositive = 0
    for start in range(0, len(hexes), chunk_size):
        coordinates = points[hexes[start : start + chunk_size]]
        jacobians = np.einsum(
            "eic,gip->egcp",
            coordinates,
            gradients,
            optimize=True,
        )
        determinants = np.linalg.det(jacobians)
        column_norms = np.linalg.norm(jacobians, axis=2)
        denominator = np.prod(column_norms, axis=2)
        scaled = np.divide(
            determinants,
            denominator,
            out=np.full_like(determinants, -np.inf),
            where=denominator > 0.0,
        )
        minimum_determinant = min(minimum_determinant, float(np.min(determinants)))
        maximum_determinant = max(maximum_determinant, float(np.max(determinants)))
        minimum_scaled = min(minimum_scaled, float(np.min(scaled)))
        nonpositive += int(np.count_nonzero(determinants <= 0.0))
    return {
        "evaluated_hexa8": len(hexes),
        "gauss_points_per_element": 8,
        "minimum_jacobian_determinant": minimum_determinant,
        "maximum_jacobian_determinant": maximum_determinant,
        "minimum_scaled_jacobian": minimum_scaled,
        "nonpositive_jacobians": nonpositive,
        "valid": nonpositive == 0 and math.isfinite(minimum_scaled),
    }


def write_python_mesh_outputs(
    output_directory: Path,
    x: np.ndarray,
    y: np.ndarray,
    zmin: np.ndarray,
    zmax: np.ndarray,
    params: object,
    *,
    export_med: bool,
    log: LogFunction | None = None,
) -> PythonMeshWriteResult:
    """Build, validate, and serialize every Python-only mesh artifact."""

    log = log or (lambda _message: None)
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    log("[Python-only] Building conformal surface and HEXA8 topology...\n")
    mesh = build_python_volume_mesh(x, y, zmin, zmax, params)
    log(
        "[Python-only] "
        f"{mesh.counts['points']:,} nodes, {mesh.counts['hexa8']:,} HEXA8, "
        f"{mesh.counts['surface_quads']:,} crack-surface quads.\n"
    )
    quality = hexa8_quality(mesh.points, mesh.hexes)
    if not quality["valid"]:
        raise ValueError(
            "Python-only mesh contains non-positive HEXA8 Jacobians; "
            f"minimum determinant={quality['minimum_jacobian_determinant']:.6e}."
        )
    log(
        "[Python-only] Quality passed: "
        f"min scaled Jacobian={quality['minimum_scaled_jacobian']:.6g}.\n"
    )

    written: list[Path] = []
    volume_path = output_directory / "castem_mesh_v.bdf"
    write_volume_bdf(volume_path, mesh.points, mesh.hexes)
    written.append(volume_path)
    if len(mesh.inlet_hexes):
        inlet_path = output_directory / "castem_mesh_v_inlet.bdf"
        write_volume_bdf(inlet_path, mesh.points, mesh.inlet_hexes)
        written.append(inlet_path)
    if len(mesh.outlet_hexes):
        outlet_path = output_directory / "castem_mesh_v_outlet.bdf"
        write_volume_bdf(outlet_path, mesh.points, mesh.outlet_hexes)
        written.append(outlet_path)
    for stem, quads in mesh.boundaries.items():
        path = output_directory / f"{stem}.bdf"
        write_surface_bdf(path, mesh.points, quads)
        written.append(path)

    med_path = output_directory / "castem_mesh_v.med" if export_med else None
    if med_path is not None:
        _write_med(med_path, mesh)
    preview_path = output_directory / "python_mesh_preview.png"
    write_mesh_preview(preview_path, mesh)
    elapsed = time.perf_counter() - started
    log(
        "[Python-only] Wrote source-free BDF outputs and preview in "
        f"{elapsed:.3f} s.\n"
    )
    return PythonMeshWriteResult(
        mesh=mesh,
        elapsed_seconds=elapsed,
        volume_bdf=volume_path,
        med_path=med_path,
        preview_path=preview_path,
        written_bdfs=tuple(written),
        quality=quality,
    )
