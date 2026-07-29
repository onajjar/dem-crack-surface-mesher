"""Compare Python-only and Cast3M meshes independently of node numbering.

The validator compares the referenced coordinate set, HEXA8 topology, every
named boundary CQUAD4 topology and winding, separate chamber volumes, recorded
timings, and the Python-only Jacobian report. Connectivity comparisons use two
independent 64-bit fingerprints after mapping nodes to canonical coordinate
ranks. A separate boundary check permits cyclic quad rotations but rejects
reversed winding.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = ROOT / "_runtime" / "chambers-headless-example"
DEFAULT_PYTHON = ROOT / "_runtime" / "python-only-chambers-example"
DEFAULT_OUTPUT = (
    ROOT
    / "examples"
    / "python-only-chambers"
    / "validation-summary.json"
)


def _small_integer_fields(line: str) -> list[int]:
    return [
        int(field)
        for start in range(8, len(line), 8)
        if (field := line[start : start + 8].strip())
        and field not in {"+", "*"}
    ]


def _large_float(field: str) -> float:
    value = field.strip()
    if "e" not in value.lower():
        for index in range(1, len(value)):
            if value[index] in "+-" and value[index - 1].isdigit():
                value = value[:index] + "E" + value[index:]
                break
    return float(value)


def _bdf_counts(path: Path) -> tuple[int, int, int]:
    maximum_node = 0
    hexahedra = 0
    quadrilaterals = 0
    with path.open("r", encoding="ascii", errors="ignore") as stream:
        for line in stream:
            card = line[:8].strip().upper()
            if card == "GRID*":
                maximum_node = max(maximum_node, int(line[8:24]))
                next(stream)
            elif card == "CHEXA":
                hexahedra += 1
                next(stream)
            elif card == "CQUAD4":
                quadrilaterals += 1
    return maximum_node, hexahedra, quadrilaterals


def _read_volume(path: Path) -> tuple[np.ndarray, np.ndarray]:
    maximum_node, hexahedron_count, _quadrilateral_count = _bdf_counts(path)
    points = np.full((maximum_node + 1, 3), np.nan, dtype=np.float64)
    hexes = np.empty((hexahedron_count, 8), dtype=np.int64)
    element_index = 0
    with path.open("r", encoding="ascii", errors="ignore") as stream:
        while line := stream.readline():
            card = line[:8].strip().upper()
            if card == "GRID*":
                node = int(line[8:24])
                continuation = stream.readline()
                points[node] = (
                    _large_float(line[40:56]),
                    _large_float(line[56:72]),
                    _large_float(continuation[8:24]),
                )
            elif card == "CHEXA":
                values = _small_integer_fields(line)
                continuation = _small_integer_fields(stream.readline())
                hexes[element_index] = (*values[2:8], *continuation[:2])
                element_index += 1
    if element_index != hexahedron_count:
        raise RuntimeError(f"Could not parse every CHEXA in {path}.")
    return points, hexes


def _read_elements(path: Path, card_name: str) -> np.ndarray:
    _maximum_node, hexahedron_count, quadrilateral_count = _bdf_counts(path)
    element_count = (
        hexahedron_count if card_name == "CHEXA" else quadrilateral_count
    )
    width = 8 if card_name == "CHEXA" else 4
    elements = np.empty((element_count, width), dtype=np.int64)
    index = 0
    with path.open("r", encoding="ascii", errors="ignore") as stream:
        while line := stream.readline():
            card = line[:8].strip().upper()
            if card == "GRID*":
                stream.readline()
                continue
            if card == "CHEXA":
                values = _small_integer_fields(line)
                continuation = _small_integer_fields(stream.readline())
                if card_name == "CHEXA":
                    elements[index] = (*values[2:8], *continuation[:2])
                    index += 1
            elif card == "CQUAD4" and card_name == "CQUAD4":
                values = _small_integer_fields(line)
                elements[index] = values[2:6]
                index += 1
    if index != element_count:
        raise RuntimeError(
            f"Parsed {index} of {element_count} {card_name} elements in {path}."
        )
    return elements


def _coordinate_bijection(
    reference_points: np.ndarray,
    reference_hexes: np.ndarray,
    python_points: np.ndarray,
    python_hexes: np.ndarray,
    tolerance: float,
) -> tuple[dict[str, object], np.ndarray, np.ndarray]:
    """Map Python nodes one-to-one onto reference nodes within tolerance."""

    reference_nodes = np.unique(reference_hexes)
    python_nodes = np.unique(python_hexes)
    reference_coordinates = reference_points[reference_nodes]
    python_coordinates = python_points[python_nodes]
    if not np.isfinite(reference_coordinates).all() or not np.isfinite(
        python_coordinates
    ).all():
        raise ValueError("A referenced volume node has no finite GRID coordinates.")

    count_match = len(reference_nodes) == len(python_nodes)
    if count_match:
        distances, matches = cKDTree(reference_coordinates).query(
            python_coordinates,
            workers=-1,
        )
        unique_matches = len(np.unique(matches))
        bijective = unique_matches == len(reference_nodes)
        maximum_euclidean = float(np.max(distances))
        maximum_absolute = float(
            np.max(
                np.abs(
                    python_coordinates
                    - reference_coordinates[matches]
                )
            )
        )
    else:
        matches = np.empty(len(python_nodes), dtype=np.int64)
        unique_matches = 0
        bijective = False
        maximum_euclidean = math.inf
        maximum_absolute = math.inf

    coordinate_set_match = (
        count_match
        and bijective
        and maximum_euclidean <= tolerance
    )
    reference_rank = np.full(len(reference_points), -1, dtype=np.int64)
    reference_rank[reference_nodes] = np.arange(
        len(reference_nodes),
        dtype=np.int64,
    )
    python_rank = np.full(len(python_points), -1, dtype=np.int64)
    if coordinate_set_match:
        python_rank[python_nodes] = matches
    return (
        {
            "reference_referenced_nodes": len(reference_nodes),
            "python_referenced_nodes": len(python_nodes),
            "count_match": count_match,
            "nearest_mapping_is_bijective": bijective,
            "unique_reference_nodes_matched": unique_matches,
            "coordinate_set_match": coordinate_set_match,
            "maximum_euclidean_difference": (
                maximum_euclidean if count_match else None
            ),
            "maximum_absolute_difference": (
                maximum_absolute if count_match else None
            ),
        },
        reference_rank,
        python_rank,
    )


def _element_fingerprints(
    elements: np.ndarray,
    node_rank: np.ndarray,
) -> np.ndarray:
    ranks = node_rank[elements]
    if np.any(ranks < 0):
        raise ValueError("An element references a node outside the volume mesh.")
    canonical = np.sort(ranks, axis=1).astype(np.uint64, copy=False)
    primes = np.asarray(
        (
            0x9E3779B185EBCA87,
            0xC2B2AE3D27D4EB4F,
            0x165667B19E3779F9,
            0x85EBCA77C2B2AE63,
            0x27D4EB2F165667C5,
            0x94D049BB133111EB,
            0xD6E8FEB86659FD93,
            0xA0761D6478BD642F,
        )[: canonical.shape[1]],
        dtype=np.uint64,
    )
    with np.errstate(over="ignore"):
        first = np.sum((canonical + 1) * primes, axis=1, dtype=np.uint64)
        second = np.full(
            len(canonical),
            np.uint64(0xCBF29CE484222325),
            dtype=np.uint64,
        )
        for column in range(canonical.shape[1]):
            second ^= canonical[:, column] + primes[column]
            second *= np.uint64(0x100000001B3)
    fingerprints = np.column_stack((first, second))
    order = np.lexsort((fingerprints[:, 1], fingerprints[:, 0]))
    return fingerprints[order]


def _canonical_oriented_quad_rows(ranks: np.ndarray) -> np.ndarray:
    """Canonicalize cyclic quad rotations without sorting the element rows."""

    candidates = np.stack(
        tuple(np.roll(ranks, -shift, axis=1) for shift in range(4)),
        axis=1,
    )
    canonical = candidates[:, 0].copy()
    row_indices = np.arange(len(canonical))
    for candidate_index in range(1, 4):
        candidate = candidates[:, candidate_index]
        differences = candidate != canonical
        different = np.any(differences, axis=1)
        first_difference = np.argmax(differences, axis=1)
        use_candidate = different & (
            candidate[row_indices, first_difference]
            < canonical[row_indices, first_difference]
        )
        canonical[use_candidate] = candidate[use_candidate]
    return canonical


def _lexicographic_row_order(values: np.ndarray) -> np.ndarray:
    return np.lexsort(
        tuple(
            values[:, column]
            for column in range(values.shape[1] - 1, -1, -1)
        )
    )


def _canonical_oriented_quads(
    elements: np.ndarray,
    node_rank: np.ndarray,
) -> np.ndarray:
    """Canonicalize cyclic quad rotations while preserving normal direction."""

    ranks = node_rank[elements]
    if np.any(ranks < 0):
        raise ValueError("A boundary element references a node outside the volume mesh.")
    canonical = _canonical_oriented_quad_rows(ranks)
    order = np.lexsort(
        (
            canonical[:, 3],
            canonical[:, 2],
            canonical[:, 1],
            canonical[:, 0],
        )
    )
    return canonical[order]


def _quad_orientation_counts(
    reference_elements: np.ndarray,
    python_elements: np.ndarray,
    reference_rank: np.ndarray,
    python_rank: np.ndarray,
) -> tuple[int, int, int]:
    """Count same, reversed, and unclassified quad windings by topology."""

    reference_nodes = reference_rank[reference_elements]
    python_nodes = python_rank[python_elements]
    reference_order = _lexicographic_row_order(
        np.sort(reference_nodes, axis=1)
    )
    python_order = _lexicographic_row_order(np.sort(python_nodes, axis=1))
    reference_oriented = _canonical_oriented_quad_rows(
        reference_nodes[reference_order]
    )
    python_oriented = _canonical_oriented_quad_rows(
        python_nodes[python_order]
    )
    python_reversed = _canonical_oriented_quad_rows(
        python_nodes[python_order][:, (0, 3, 2, 1)]
    )
    same = np.all(reference_oriented == python_oriented, axis=1)
    reversed_winding = np.all(
        reference_oriented == python_reversed,
        axis=1,
    )
    return (
        int(np.count_nonzero(same)),
        int(np.count_nonzero(reversed_winding)),
        int(np.count_nonzero(~same & ~reversed_winding)),
    )


def _quad_orientation_map(
    elements: np.ndarray,
    node_rank: np.ndarray,
) -> dict[tuple[int, int, int, int], tuple[int, int, int, int]]:
    nodes = node_rank[elements]
    topology = np.sort(nodes, axis=1)
    oriented = _canonical_oriented_quad_rows(nodes)
    return {
        tuple(int(value) for value in topology_row): tuple(
            int(value) for value in oriented_row
        )
        for topology_row, oriented_row in zip(
            topology,
            oriented,
            strict=True,
        )
    }


def _combined_surface_orientation_groups(
    reference_path: Path,
    python_path: Path,
    component_paths: dict[str, Path],
    reference_rank: np.ndarray,
    python_rank: np.ndarray,
) -> dict[str, dict[str, int]]:
    """Classify complete-exterior winding by its named component topology."""

    reference_map = _quad_orientation_map(
        _read_elements(reference_path, "CQUAD4"),
        reference_rank,
    )
    python_map = _quad_orientation_map(
        _read_elements(python_path, "CQUAD4"),
        python_rank,
    )
    results: dict[str, dict[str, int]] = {}
    for name, path in sorted(component_paths.items()):
        if name.endswith("_all.bdf") or name.endswith("_mean.bdf"):
            continue
        component_nodes = python_rank[_read_elements(path, "CQUAD4")]
        topologies = {
            tuple(int(value) for value in row)
            for row in np.sort(component_nodes, axis=1)
        }
        same = 0
        reversed_winding = 0
        unclassified = 0
        included = 0
        for topology in topologies:
            python_oriented = python_map.get(topology)
            if python_oriented is None:
                continue
            included += 1
            reference_oriented = reference_map[topology]
            if reference_oriented == python_oriented:
                same += 1
            elif reference_oriented == (
                python_oriented[0],
                python_oriented[3],
                python_oriented[2],
                python_oriented[1],
            ):
                reversed_winding += 1
            else:
                unclassified += 1
        if included:
            results[name] = {
                "included_elements": included,
                "same": same,
                "reversed": reversed_winding,
                "unclassified": unclassified,
            }
    return results


def _compare_elements(
    reference_path: Path,
    python_path: Path,
    card: str,
    reference_rank: np.ndarray,
    python_rank: np.ndarray,
) -> dict[str, object]:
    reference_elements = _read_elements(reference_path, card)
    python_elements = _read_elements(python_path, card)
    count_match = len(reference_elements) == len(python_elements)
    topology_match = False
    orientation_match = None
    reversed_orientation_match = None
    orientation_counts = None
    if count_match:
        reference_fingerprints = _element_fingerprints(
            reference_elements,
            reference_rank,
        )
        python_fingerprints = _element_fingerprints(
            python_elements,
            python_rank,
        )
        topology_match = bool(
            np.array_equal(reference_fingerprints, python_fingerprints)
        )
        if card == "CQUAD4" and topology_match:
            reference_oriented = _canonical_oriented_quads(
                reference_elements,
                reference_rank,
            )
            orientation_match = bool(
                np.array_equal(
                    reference_oriented,
                    _canonical_oriented_quads(python_elements, python_rank),
                )
            )
            reversed_orientation_match = bool(
                np.array_equal(
                    reference_oriented,
                    _canonical_oriented_quads(
                        python_elements[:, (0, 3, 2, 1)],
                        python_rank,
                    ),
                )
            )
            orientation_counts = _quad_orientation_counts(
                reference_elements,
                python_elements,
                reference_rank,
                python_rank,
            )
    return {
        "card": card,
        "reference_elements": len(reference_elements),
        "python_elements": len(python_elements),
        "count_match": count_match,
        "topology_match": topology_match,
        "orientation_match": orientation_match,
        "reversed_orientation_match": reversed_orientation_match,
        "orientation_counts": (
            {
                "same": orientation_counts[0],
                "reversed": orientation_counts[1],
                "unclassified": orientation_counts[2],
            }
            if orientation_counts is not None
            else None
        ),
    }


def _timing(directory: Path) -> dict[str, float | None]:
    report_path = directory / "headless-run-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    mesh = report["mesh"]
    return {
        "mesh_seconds": float(mesh["elapsed_seconds"]),
        "total_seconds": (
            float(mesh["total_elapsed_seconds"])
            if mesh.get("total_elapsed_seconds") is not None
            else None
        ),
    }


def validate(
    reference_directory: Path,
    python_directory: Path,
    *,
    tolerance: float,
) -> dict[str, object]:
    reference_volume = reference_directory / "castem_mesh_v.bdf"
    python_volume = python_directory / "castem_mesh_v.bdf"
    reference_points, reference_hexes = _read_volume(reference_volume)
    python_points, python_hexes = _read_volume(python_volume)
    (
        coordinate_result,
        reference_rank,
        python_rank,
    ) = _coordinate_bijection(
        reference_points,
        reference_hexes,
        python_points,
        python_hexes,
        tolerance,
    )
    coordinate_set_match = bool(coordinate_result["coordinate_set_match"])
    volume = _compare_elements(
        reference_volume,
        python_volume,
        "CHEXA",
        reference_rank,
        python_rank,
    )

    reference_surfaces = {
        path.name: path
        for path in reference_directory.glob("castem_mesh_surf_*.bdf")
    }
    python_surfaces = {
        path.name: path
        for path in python_directory.glob("castem_mesh_surf_*.bdf")
    }
    surface_names_match = set(reference_surfaces) == set(python_surfaces)
    surface_results = {}
    for name in sorted(set(reference_surfaces) & set(python_surfaces)):
        surface_results[name] = _compare_elements(
            reference_surfaces[name],
            python_surfaces[name],
            "CQUAD4",
            reference_rank,
            python_rank,
        )
    combined_surface_orientation_groups = {}
    combined_name = "castem_mesh_surf_all.bdf"
    if (
        combined_name in reference_surfaces
        and combined_name in python_surfaces
    ):
        combined_surface_orientation_groups = (
            _combined_surface_orientation_groups(
                reference_surfaces[combined_name],
                python_surfaces[combined_name],
                python_surfaces,
                reference_rank,
                python_rank,
            )
        )

    chamber_volume_results = {}
    for name in ("castem_mesh_v_inlet.bdf", "castem_mesh_v_outlet.bdf"):
        reference_path = reference_directory / name
        python_path = python_directory / name
        if reference_path.is_file() and python_path.is_file():
            chamber_volume_results[name] = _compare_elements(
                reference_path,
                python_path,
                "CHEXA",
                reference_rank,
                python_rank,
            )

    reference_timing = _timing(reference_directory)
    python_timing = _timing(python_directory)
    speedup = (
        reference_timing["mesh_seconds"] / python_timing["mesh_seconds"]
        if python_timing["mesh_seconds"]
        else None
    )
    python_report = json.loads(
        (python_directory / "headless-run-report.json").read_text(
            encoding="utf-8"
        )
    )["mesh"]["python_only"]
    all_surface_topologies_match = surface_names_match and all(
        result["topology_match"] for result in surface_results.values()
    )
    all_surface_orientations_match = surface_names_match and all(
        result["orientation_match"] for result in surface_results.values()
    )
    all_chamber_volumes_match = all(
        result["topology_match"]
        for result in chamber_volume_results.values()
    )
    success = all(
        (
            coordinate_set_match,
            volume["topology_match"],
            all_surface_topologies_match,
            all_surface_orientations_match,
            all_chamber_volumes_match,
            python_report["quality"]["valid"],
        )
    )
    return {
        "success": success,
        "comparison_basis": {
            "node_numbering_independent": True,
            "topology_comparison_orientation_independent": True,
            "boundary_winding_compared_separately": True,
            "boundary_winding_rule": (
                "cyclic rotations allowed; reversals rejected"
            ),
            "coordinate_tolerance": tolerance,
            "coordinate_matching": "one-to-one nearest-neighbour bijection",
            "connectivity_fingerprints": "two independent uint64 values",
        },
        "coordinates": coordinate_result,
        "volume": volume,
        "chamber_volumes": chamber_volume_results,
        "surface_file_sets_match": surface_names_match,
        "surfaces": surface_results,
        "all_surface_topologies_match": all_surface_topologies_match,
        "all_surface_orientations_match": all_surface_orientations_match,
        "combined_surface_orientation_groups": (
            combined_surface_orientation_groups
        ),
        "quality": python_report["quality"],
        "counts": python_report["counts"],
        "timing": {
            "reference_cast3m_mesh_seconds": reference_timing["mesh_seconds"],
            "python_only_mesh_seconds": python_timing["mesh_seconds"],
            "python_only_total_seconds": python_timing["total_seconds"],
            "mesh_phase_speedup": speedup,
            "note": (
                "The speedup compares the recorded mesh-generation phases. "
                "Only the newer Python report records complete post-processing time."
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference-directory",
        type=Path,
        default=DEFAULT_REFERENCE,
    )
    parser.add_argument(
        "--python-directory",
        type=Path,
        default=DEFAULT_PYTHON,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument("--tolerance", type=float, default=1.0e-9)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate(
        args.reference_directory.resolve(),
        args.python_directory.resolve(),
        tolerance=args.tolerance,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
