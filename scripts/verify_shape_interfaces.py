"""Verify final BDF hole-wall counts and absence of square/fill boundary seams."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from castem_pipeline_headless import load_setup, validate_setup  # noqa: E402
from python_hole_interpolation import hole_boundary_vertices  # noqa: E402


def _polygon_distance(points: np.ndarray, vertices: np.ndarray) -> np.ndarray:
    starts = vertices
    edges = np.roll(vertices, -1, axis=0) - starts
    relative = points[:, np.newaxis, :] - starts[np.newaxis, :, :]
    scale = np.sum(relative * edges[np.newaxis, :, :], axis=2) / np.sum(edges * edges, axis=1)
    scale = np.clip(scale, 0.0, 1.0)
    closest = starts[np.newaxis, :, :] + scale[:, :, np.newaxis] * edges[np.newaxis, :, :]
    return np.min(np.linalg.norm(points[:, np.newaxis, :] - closest, axis=2), axis=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "examples" / "shaped-holes" / "all-shapes.ini",
    )
    parser.add_argument(
        "--bdf",
        type=Path,
        default=ROOT / "_runtime" / "all-hole-shapes" / "castem_mesh_surf_max.bdf",
    )
    parser.add_argument(
        "--volume",
        type=Path,
        default=ROOT / "_runtime" / "all-hole-shapes" / "castem_mesh_v.bdf",
    )
    parser.add_argument("--tolerance", type=float, default=2.0e-7)
    args = parser.parse_args()

    setup = load_setup(args.config)
    expected = validate_setup(setup)
    bdf = args.bdf.resolve()
    if not bdf.is_file():
        raise FileNotFoundError(f"Surface BDF does not exist: {bdf}")

    import meshio

    mesh = meshio.read(bdf)
    quads = mesh.cells_dict.get("quad")
    if quads is None or len(quads) == 0:
        raise ValueError("Expected CQUAD4 cells in the final surface BDF.")
    edge_counts: Counter[tuple[int, int]] = Counter()
    for quad in quads:
        for start, end in zip(quad, np.roll(quad, -1), strict=True):
            edge_counts[tuple(sorted((int(start), int(end))))] += 1
    boundary = np.asarray([edge for edge, count in edge_counts.items() if count == 1], dtype=int)
    endpoints = mesh.points[boundary, :2]
    midpoints = endpoints.mean(axis=1)

    results = []
    success = True
    for index, (geometry, expected_edges) in enumerate(
        zip(setup.params.hole_shapes, expected, strict=True), start=1
    ):
        center = np.array((geometry.cx, geometry.cy))
        near = np.linalg.norm(midpoints - center, axis=1) <= 1.8 * geometry.selection_radius
        if geometry.shape == "circle":
            distances = np.abs(np.linalg.norm(endpoints - center, axis=2) - float(geometry.radius))
        else:
            vertices = hole_boundary_vertices(geometry)
            distances = _polygon_distance(endpoints.reshape(-1, 2), vertices).reshape(-1, 2)
        wall = np.all(distances <= args.tolerance, axis=1)
        near_count = int(np.count_nonzero(near))
        wall_count = int(np.count_nonzero(wall))
        unmatched = near_count - wall_count
        shape_ok = wall_count == expected_edges and unmatched == 0
        success = success and shape_ok
        results.append(
            {
                "hole": index,
                "shape": geometry.shape,
                "expected_square_interface_edges": expected_edges,
                "final_hole_wall_edges": wall_count,
                "unmatched_square_fill_boundary_edges": unmatched,
                "passed": shape_ok,
            }
        )

    report = {
        "surface_quads": int(len(quads)),
        "total_boundary_edges": int(len(boundary)),
        "holes": results,
    }
    volume_path = args.volume.resolve()
    if not volume_path.is_file():
        raise FileNotFoundError(f"Volume BDF does not exist: {volume_path}")
    volume = meshio.read(volume_path)
    hexahedra = volume.cells_dict.get("hexahedron")
    if hexahedra is None or len(hexahedra) == 0:
        raise ValueError("Expected HEXA8 cells in the volume BDF.")
    signs = np.array(
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
    coordinates = volume.points[hexahedra]
    jacobians = np.einsum("hni,nj->hij", coordinates, signs / 8.0)
    determinants = np.linalg.det(jacobians)
    scale = max(float(np.ptp(volume.points, axis=0).max()), 1.0)
    determinant_tolerance = np.finfo(float).eps * scale**3 * 64.0
    positive = int(np.count_nonzero(determinants > determinant_tolerance))
    negative = int(np.count_nonzero(determinants < -determinant_tolerance))
    zero = int(len(determinants) - positive - negative)
    volume_ok = zero == 0 and (positive == len(determinants) or negative == len(determinants))
    success = success and volume_ok
    report["volume"] = {
        "hexahedra": int(len(hexahedra)),
        "positive_center_jacobians": positive,
        "negative_center_jacobians": negative,
        "zero_center_jacobians": zero,
        "consistent_nonzero_orientation": volume_ok,
    }
    report["passed"] = success
    print(json.dumps(report, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
