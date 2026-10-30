"""OpenFOAM export of the crack volume mesh: polyMesh and a ready-to-run case.

The exporter reads the named NASTRAN outputs that every mesh backend writes
(``castem_mesh_v.bdf`` plus the ``castem_mesh_surf_*.bdf`` boundaries), a
merged ``combined_*.bdf`` file, or the in-memory Python-only mesh, and writes
an OpenFOAM case directory:

* ``constant/polyMesh`` with named patches (inlet, outlet, crack walls, side
  walls, hole walls and chamber walls), cell zones (crack and chambers) and,
  when chambers exist, face zones on the crack entrance and exit;
* optionally the ``0/``, ``constant/`` and ``system/`` dictionaries of a
  laminar steady run, incompressible (``simpleFoam``) or compressible ideal
  gas (``rhoSimpleFoam``), for OpenFOAM.com (v2xxx) or OpenFOAM.org (11 and
  later), with an ``Allrun`` script.

Thin rough-crack hexahedra are warped sheets whose cell centre can fall outside
the cell; OpenFOAM's face-pyramid check then fails and the solvers diverge.  By
default (``cell_split = auto``) every vertical column holding a hexahedron whose
smallest face pyramid is below ``pyramid_margin`` times that of a box (one sixth
of the cell volume) is split into two triangular prisms per hexahedron, with one
diagonal per column, chosen where the mid-surface rises least.  The prisms keep
every node, wall and patch of the source mesh and are convex, so the check
passes by construction.  Sound hexahedra (constant openings, chambers, gently
curved walls) are kept, which avoids the large non-orthogonality of split
elongated cells.  Coincident nodes are merged, so duplicated seams become conformal
and cells collapsed on a closed crack front become pyramids or tetrahedra, or
are dropped when their volume is zero.

No OpenFOAM installation is needed to export; ``checkMesh`` and the solvers run
wherever OpenFOAM is installed (Linux, WSL, Docker or a cluster).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np

LogFunction = Callable[[str], None]

SURFACE_PREFIX = "castem_mesh_surf_"
VOLUME_FILE = "castem_mesh_v.bdf"
CHAMBER_VOLUME_FILES = {
    "inletChamber": "castem_mesh_v_inlet.bdf",
    "outletChamber": "castem_mesh_v_outlet.bdf",
}
# Aggregate or mid-gap surfaces that never define a patch.
NON_PATCH_SURFACES = {"mean", "all", "inlet_all", "outlet_all"}
# PSHELL order of the maintained BDF merger, used only when a combined BDF has
# lost its "$ ---- castem_mesh_surf_*.bdf ----" comments.
MERGER_SURFACE_ORDER = ("min", "max", "xmin", "xmax", "ymin", "ymax")
EXPORT_MARKER = "openfoam_export.json"

SUPPORTED_SOLVERS = ("simpleFoam", "rhoSimpleFoam", "none")
SUPPORTED_VERSIONS = ("com", "org")
SUPPORTED_FORMATS = ("ascii", "binary")
SUPPORTED_SPLITS = ("auto", "prism", "none")
SUPPORTED_FLOW_DIRECTIONS = ("+y", "-y", "+x", "-x")
SUPPORTED_SIDE_TYPES = ("wall", "symmetry", "patch")
SUPPORTED_PATCH_TYPES = ("patch", "wall", "symmetry", "symmetryPlane", "empty")

LABEL = np.int32
VSMALL = 1.0e-300
ROOTVSMALL = 1.0e-150

# Outward faces of the standard cell shapes (NASTRAN/VTK node order); -1 pads
# a triangle.  Each cell's orientation is checked again from its signed volume.
CELL_FACES = {
    "hex": np.array(
        [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    ),
    "prism": np.array(
        [(0, 2, 1, -1), (3, 4, 5, -1), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)]
    ),
    "pyramid": np.array(
        [(0, 3, 2, 1), (0, 1, 4, -1), (1, 2, 4, -1), (2, 3, 4, -1), (3, 0, 4, -1)]
    ),
    "tet": np.array([(0, 2, 1, -1), (0, 1, 3, -1), (1, 2, 3, -1), (2, 0, 3, -1)]),
}
CELL_NODE_COUNTS = {"hex": 8, "prism": 6, "pyramid": 5, "tet": 4}
NASTRAN_CELL_KINDS = {"CHEXA": "hex", "CPENTA": "prism", "CPYRAM": "pyramid", "CTETRA": "tet"}
# Hexahedron node permutations that put each pair of opposite faces at 0-3/4-7.
HEX_AXIS_PERMUTATIONS = (
    (0, 1, 2, 3, 4, 5, 6, 7),
    (0, 1, 5, 4, 3, 2, 6, 7),
    (0, 3, 7, 4, 1, 2, 6, 5),
)
# Two prisms per hexahedron, split along the diagonal 0-2/4-6 or 1-3/5-7.
PRISMS_02 = ((0, 1, 2, 4, 5, 6), (0, 2, 3, 4, 6, 7))
PRISMS_13 = ((0, 1, 3, 4, 5, 7), (1, 2, 3, 5, 6, 7))


# --------------------------------------------------------------------------- settings
@dataclass(frozen=True)
class OpenFOAMSettings:
    """Export, patch and case options.  Pressures are absolute, in pascals."""

    case_directory: str = "openfoam_case"
    solver: str = "simpleFoam"
    openfoam_version: str = "com"
    write_format: str = "ascii"
    cell_split: str = "auto"
    pyramid_margin: float = 0.25
    merge_tolerance: float = 1.0e-9
    length_scale: float = 1.0
    flow_direction: str = "+y"
    side_walls: str = "wall"
    patches: str = ""
    inlet_pressure: float = 111325.0
    outlet_pressure: float = 101325.0
    temperature: float = 298.15
    dynamic_viscosity: float = 1.831e-5
    gas_constant: float = 287.05
    heat_capacity: float = 1004.4
    thermal_conductivity: float = 0.0261
    density: float | None = None
    iterations: int = 2000
    write_interval: int = 500
    processors: int = 1
    residual_tolerance: float = 1.0e-6
    archive_existing: bool = True

    def validated(self) -> OpenFOAMSettings:
        checks = (
            (self.solver in SUPPORTED_SOLVERS, f"solver must be one of {SUPPORTED_SOLVERS}"),
            (
                self.openfoam_version in SUPPORTED_VERSIONS,
                f"openfoam_version must be one of {SUPPORTED_VERSIONS}",
            ),
            (
                self.write_format in SUPPORTED_FORMATS,
                f"write_format must be one of {SUPPORTED_FORMATS}",
            ),
            (self.cell_split in SUPPORTED_SPLITS, f"cell_split must be one of {SUPPORTED_SPLITS}"),
            (
                self.flow_direction in SUPPORTED_FLOW_DIRECTIONS,
                f"flow_direction must be one of {SUPPORTED_FLOW_DIRECTIONS}",
            ),
            (
                self.side_walls in SUPPORTED_SIDE_TYPES,
                f"side_walls must be one of {SUPPORTED_SIDE_TYPES}",
            ),
            (bool(str(self.case_directory).strip()), "case_directory must not be empty"),
            (
                _finite(self.pyramid_margin) and 0.0 <= self.pyramid_margin < 1.0,
                "pyramid_margin must be in [0, 1)",
            ),
            (
                _finite(self.merge_tolerance) and self.merge_tolerance >= 0.0,
                "merge_tolerance must be >= 0",
            ),
            (_positive(self.length_scale), "length_scale must be > 0"),
            (_positive(self.inlet_pressure), "inlet_pressure must be > 0 Pa (absolute)"),
            (_positive(self.outlet_pressure), "outlet_pressure must be > 0 Pa (absolute)"),
            (_positive(self.temperature), "temperature must be > 0 K"),
            (_positive(self.dynamic_viscosity), "dynamic_viscosity must be > 0"),
            (_positive(self.gas_constant), "gas_constant must be > 0"),
            (
                _positive(self.heat_capacity) and self.heat_capacity > self.gas_constant,
                "heat_capacity must exceed gas_constant",
            ),
            (_positive(self.thermal_conductivity), "thermal_conductivity must be > 0"),
            (self.density is None or _positive(self.density), "density must be > 0 when given"),
            (int(self.iterations) >= 1, "iterations must be >= 1"),
            (int(self.write_interval) >= 1, "write_interval must be >= 1"),
            (int(self.processors) >= 1, "processors must be >= 1"),
            (_positive(self.residual_tolerance), "residual_tolerance must be > 0"),
        )
        for ok, message in checks:
            if not ok:
                raise ValueError(f"OpenFOAM export: {message}.")
        if self.patches.strip():
            parse_patch_rules(self.patches)
        return self

    @property
    def flow_axis(self) -> int:
        return 0 if self.flow_direction.endswith("x") else 1

    @property
    def flow_sign(self) -> int:
        return -1 if self.flow_direction.startswith("-") else 1

    @property
    def mean_density(self) -> float:
        """Density of the incompressible model: given, or ideal gas at mean pressure."""

        if self.density is not None:
            return float(self.density)
        mean_pressure = 0.5 * (self.inlet_pressure + self.outlet_pressure)
        return mean_pressure / (self.gas_constant * self.temperature)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _positive(value: object) -> bool:
    return _finite(value) and value > 0.0


def settings_from_mapping(values: Mapping[str, str], **overrides: object) -> OpenFOAMSettings:
    """Settings from an INI section or any string mapping (unknown keys rejected)."""

    known = {item.name: item for item in fields(OpenFOAMSettings)}
    kwargs: dict[str, object] = {}
    for key, raw in values.items():
        key = key.strip().lower()
        if key not in known:
            raise ValueError(f"Unknown [openfoam] option {key!r}.")
        text = str(raw).strip()
        default = known[key].default
        if key == "density":
            kwargs[key] = None if text.lower() in ("", "auto", "none") else float(text)
        elif isinstance(default, bool):
            if text.lower() not in ("1", "0", "true", "false", "yes", "no", "on", "off"):
                raise ValueError(f"[openfoam] {key} must be true or false.")
            kwargs[key] = text.lower() in ("1", "true", "yes", "on")
        elif isinstance(default, int):
            kwargs[key] = int(text)
        elif isinstance(default, float):
            kwargs[key] = float(text)
        else:
            kwargs[key] = text
    kwargs.update(overrides)
    return OpenFOAMSettings(**kwargs).validated()


def settings_to_mapping(settings: OpenFOAMSettings) -> dict[str, str]:
    """String values for an INI ``[openfoam]`` section."""

    out = {}
    for key, value in asdict(settings).items():
        if value is None:
            out[key] = "auto"
        elif isinstance(value, bool):
            out[key] = "true" if value else "false"
        else:
            out[key] = repr(value) if isinstance(value, float) else str(value)
    return out


@dataclass(frozen=True)
class PatchRule:
    """One OpenFOAM patch built from one or more named boundary surfaces."""

    name: str
    type: str
    surfaces: tuple[str, ...]


def default_patch_rules(
    surface_names: Iterable[str],
    *,
    flow_direction: str = "+y",
    side_walls: str = "wall",
) -> tuple[PatchRule, ...]:
    """Patch table for the tool's surface names (``min``, ``ymax``, ``trou_1`` ...)."""

    names = set(surface_names)
    chambers = "inlet_outer" in names or "outlet_outer" in names
    axis = "x" if flow_direction.endswith("x") else "y"
    other = "y" if axis == "x" else "x"
    upstream, downstream = f"{axis}min", f"{axis}max"
    if flow_direction.startswith("-"):
        upstream, downstream = downstream, upstream
    rules: list[PatchRule] = []
    if chambers:
        if axis != "y":
            raise ValueError("Chambers are attached at Ymin/Ymax: use flow_direction +y or -y.")
        first, second = ("inlet", "outlet") if upstream == "ymin" else ("outlet", "inlet")
        rules += [
            PatchRule("inlet", "patch", (f"{first}_outer",)),
            PatchRule("outlet", "patch", (f"{second}_outer",)),
        ]
    else:
        rules += [
            PatchRule("inlet", "patch", (upstream,)),
            PatchRule("outlet", "patch", (downstream,)),
        ]
    rules += [
        PatchRule("lowerWall", "wall", ("min",)),
        PatchRule("upperWall", "wall", ("max",)),
        PatchRule("sideWalls", side_walls, (f"{other}min", f"{other}max")),
    ]
    holes = sorted(
        (name for name in names if re.fullmatch(r"trou_\d+", name)),
        key=lambda name: int(name.split("_")[1]),
    )
    rules += [PatchRule(f"hole{name.split('_')[1]}", "wall", (name,)) for name in holes]
    used = {surface for rule in rules for surface in rule.surfaces}
    if chambers:
        for patch, chamber in (("inletChamberWalls", first), ("outletChamberWalls", second)):
            members = tuple(
                f"{chamber}_{part}" for part in ("interface", "top", "bottom", "xmin", "xmax")
            )
            rules.append(PatchRule(patch, "wall", members))
            used |= set(members)
        # The crack's own Ymin/Ymax faces are internal once chambers exist.
        used |= {"ymin", "ymax"}
    for name in sorted(names - used - NON_PATCH_SURFACES):
        rules.append(PatchRule(_patch_identifier(name), "wall", (name,)))
    return tuple(rules)


def parse_patch_rules(text: str) -> tuple[PatchRule, ...]:
    """Parse ``name=type:surface+surface; ...``, for example
    ``inlet=patch:ymin; outlet=patch:ymax; walls=wall:min+max+xmin+xmax``."""

    rules = []
    for item in re.split(r"[;\n]", text):
        item = item.strip()
        if not item:
            continue
        match = re.fullmatch(r"([A-Za-z_][\w.-]*)\s*=\s*(\w+)\s*:\s*(.+)", item)
        if not match:
            raise ValueError(f"Bad patch rule {item!r}; use name=type:surface+surface.")
        name, kind, members = match.groups()
        if kind not in SUPPORTED_PATCH_TYPES:
            raise ValueError(f"Unsupported patch type {kind!r} in {item!r}.")
        surfaces = tuple(_surface_stem(s) for s in members.split("+") if s.strip())
        rules.append(PatchRule(name, kind, surfaces))
    if not rules:
        raise ValueError("No patch rule given.")
    names = [rule.name for rule in rules]
    if len(set(names)) != len(names):
        raise ValueError("Patch names must be unique.")
    return tuple(rules)


def _patch_identifier(name: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", name) if part]
    if not parts:
        return "surface"
    word = parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])
    return word if word[0].isalpha() else f"surface{word}"


def _surface_stem(name: str) -> str:
    stem = Path(name.strip()).name
    if stem.lower().endswith(".bdf"):
        stem = stem[:-4]
    if stem.startswith(SURFACE_PREFIX):
        stem = stem[len(SURFACE_PREFIX):]
    return stem


# --------------------------------------------------------------------------- NASTRAN
def nastran_float(text: str) -> float:
    """NASTRAN real, including the compact exponent form ``-5.5-3``."""

    value = text.strip().replace("D", "E").replace("d", "e")
    if not value:
        raise ValueError("Empty NASTRAN real field.")
    try:
        return float(value)
    except ValueError:
        pass
    for index in range(len(value) - 1, 0, -1):
        if value[index] in "+-" and value[index - 1] not in "eE":
            return float(value[:index] + "E" + value[index:])
    raise ValueError(f"Not a NASTRAN real: {text!r}")


@dataclass
class BdfData:
    """Nodes, solid cells and shells of one NASTRAN bulk-data file."""

    grid_ids: np.ndarray
    points: np.ndarray
    cells: dict[str, list[list[int]]]
    shells: list[tuple[int, list[int]]]
    pshell_names: dict[int, str]


def _card_fields(lines: Sequence[str]) -> list[str]:
    """Fields 1.. of one card from its physical lines (small, large or free field)."""

    out: list[str] = []
    for index, line in enumerate(lines):
        if "," in line:
            parts = [part.strip() for part in line.split(",")]
            out.extend(parts[1:])
            continue
        large = line[:8].rstrip().endswith("*")
        width, count = (16, 4) if large else (8, 8)
        out.extend(line[8 + width * k: 8 + width * (k + 1)].strip() for k in range(count))
    return out


def _is_continuation(line: str) -> bool:
    return bool(line) and (line[0] in "*+" or (line[:8].strip() == "" and line.strip() != ""))


def read_bdf(path: Path, *, wanted_ids: set[int] | None = None) -> BdfData:
    """Read GRID, CHEXA/CPENTA/CPYRAM/CTETRA, CQUAD4/CTRIA3 and PSHELL cards.

    ``wanted_ids`` limits GRID parsing to those node IDs (an empty set skips
    every GRID), which keeps the reading of Cast3M boundary files, each of
    which repeats the full GRID table, fast.  The ``$ ---- name.bdf ----``
    comments written by the tool's BDF merger name the PSHELL that follows.
    """

    path = Path(path)
    grid_ids: list[int] = []
    coords: list[tuple[float, ...]] = []
    cells: dict[str, list[list[int]]] = {kind: [] for kind in CELL_NODE_COUNTS}
    shells: list[tuple[int, list[int]]] = []
    pshell_names: dict[int, str] = {}
    pending_name: str | None = None
    with path.open("r", encoding="ascii", errors="ignore") as stream:
        lines = stream.read().splitlines()
    count = len(lines)
    index = 0
    while index < count:
        line = lines[index]
        if not line.strip() or line[0] == "$":
            match = re.match(r"\$\s*-+\s*(\S+\.bdf)\s*-+", line, flags=re.IGNORECASE)
            if match and not re.match(r"\$\s*-+\s*END\b", line, flags=re.IGNORECASE):
                pending_name = _surface_stem(match.group(1))
            index += 1
            continue
        end = index + 1
        while end < count and _is_continuation(lines[end]):
            end += 1
        card = line[:8].split(",")[0].strip().upper().rstrip("*")
        if card == "GRID":
            if line.startswith("GRID*") and "," not in line:
                node = int(line[8:24])
                if wanted_ids is None or node in wanted_ids:
                    continuation = lines[index + 1] if index + 1 < count else ""
                    grid_ids.append(node)
                    coords.append(
                        (
                            nastran_float(line[40:56]),
                            nastran_float(line[56:72]),
                            nastran_float(continuation[8:24]),
                        )
                    )
            else:
                values = _card_fields(lines[index:end])
                node = int(values[0])
                if wanted_ids is None or node in wanted_ids:
                    grid_ids.append(node)
                    coords.append(tuple(nastran_float(value) for value in values[2:5]))
        elif card in NASTRAN_CELL_KINDS:
            kind = NASTRAN_CELL_KINDS[card]
            values = [value for value in _card_fields(lines[index:end]) if value]
            nodes = [int(value) for value in values[2:2 + CELL_NODE_COUNTS[kind]]]
            if len(nodes) != CELL_NODE_COUNTS[kind]:
                raise ValueError(f"{path.name}: incomplete {card} card at line {index + 1}.")
            cells[kind].append(nodes)
        elif card in ("CQUAD4", "CTRIA3"):
            values = [value for value in _card_fields(lines[index:end]) if value]
            size = 4 if card == "CQUAD4" else 3
            nodes = [int(value) for value in values[2:2 + size]]
            if len(nodes) != size:
                raise ValueError(f"{path.name}: incomplete {card} card at line {index + 1}.")
            shells.append((int(values[1]), nodes + [-1] * (4 - size)))
        elif card == "PSHELL":
            values = [value for value in _card_fields(lines[index:end]) if value]
            if pending_name is not None:
                pshell_names[int(values[0])] = pending_name
                pending_name = None
        index = end
    return BdfData(
        grid_ids=np.asarray(grid_ids, dtype=np.int64),
        points=np.asarray(coords, dtype=np.float64).reshape(-1, 3),
        cells=cells,
        shells=shells,
        pshell_names=pshell_names,
    )


# --------------------------------------------------------------------------- source mesh
@dataclass
class SourceMesh:
    """Volume cells, named boundary faces and cell zones of one source mesh.

    ``cells`` maps a cell kind (hex, prism, pyramid, tet) to node rows that
    index ``points``; ``surfaces`` maps a surface stem (``min``, ``ymax``,
    ``trou_1``, ``inlet_outer`` ...) to (n, 4) node rows, -1 padding triangles;
    ``cell_zones`` maps a zone name to {kind: row indices}.
    """

    points: np.ndarray
    cells: dict[str, np.ndarray]
    surfaces: dict[str, np.ndarray]
    cell_zones: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    description: str = ""
    warnings: list[str] = field(default_factory=list)


def _id_lookup(grid_ids: np.ndarray) -> np.ndarray:
    if grid_ids.size == 0:
        raise ValueError("The BDF contains no GRID card.")
    if grid_ids.min() < 0:
        raise ValueError("Negative GRID ID.")
    if np.unique(grid_ids).size != grid_ids.size:
        raise ValueError("Duplicate GRID IDs.")
    lookup = np.full(int(grid_ids.max()) + 1, -1, dtype=np.int64)
    lookup[grid_ids] = np.arange(grid_ids.size)
    return lookup


def _map_ids(lookup: np.ndarray, ids: np.ndarray, what: str) -> np.ndarray:
    ids = np.asarray(ids, dtype=np.int64)
    valid = ids >= 0
    if (ids[valid] >= lookup.size).any():
        raise ValueError(f"{what} references an undefined GRID.")
    mapped = np.where(valid, lookup[np.where(valid, ids, 0)], -1)
    if (mapped[valid] < 0).any():
        raise ValueError(f"{what} references an undefined GRID.")
    return mapped


def _cells_from_bdf(data: BdfData, lookup: np.ndarray, what: str) -> dict[str, np.ndarray]:
    cells = {
        kind: _map_ids(lookup, np.asarray(rows, dtype=np.int64), what)
        for kind, rows in data.cells.items()
        if rows
    }
    if not cells:
        raise ValueError(f"{what} contains no CHEXA, CPENTA, CPYRAM or CTETRA cell.")
    return cells


def mesh_from_python(mesh: object) -> SourceMesh:
    """Source mesh from an in-memory ``python_volume_mesher.PythonVolumeMesh``."""

    points = np.asarray(mesh.points, dtype=np.float64)
    hexes = np.asarray(mesh.hexes, dtype=np.int64)
    surfaces = {
        _surface_stem(name): np.asarray(quads, dtype=np.int64)
        for name, quads in mesh.boundaries.items()
    }
    zones: dict[str, dict[str, np.ndarray]] = {}
    n_inlet, n_outlet = len(mesh.inlet_hexes), len(mesh.outlet_hexes)
    if n_inlet or n_outlet:
        # The Python mesher stacks the crack, inlet and outlet blocks in order.
        n_crack = len(hexes) - n_inlet - n_outlet
        if not (
            np.array_equal(hexes[n_crack:n_crack + n_inlet], mesh.inlet_hexes)
            and np.array_equal(hexes[n_crack + n_inlet:], mesh.outlet_hexes)
        ):
            raise ValueError("Unexpected chamber block order in the Python mesh.")
        zones = {
            "crack": {"hex": np.arange(n_crack)},
            "inletChamber": {"hex": np.arange(n_crack, n_crack + n_inlet)},
            "outletChamber": {"hex": np.arange(n_crack + n_inlet, len(hexes))},
        }
    return SourceMesh(points, {"hex": hexes}, surfaces, zones, "Python-only mesh (in memory)")


def _surface_nodes(
    path: Path,
    shells: np.ndarray,
    volume_points: np.ndarray,
    lookup: np.ndarray,
    tolerance: float,
    sample: int = 2048,
) -> tuple[np.ndarray, str]:
    """Map a boundary file's node IDs onto the volume nodes.

    Cast3M and the Python backend share one global node numbering between the
    volume and boundary files; a sample of coordinates confirms it.  A file
    numbered otherwise is mapped by coordinates instead.
    """

    ids = np.unique(shells[shells >= 0])
    probe = ids if ids.size <= sample else ids[np.linspace(0, ids.size - 1, sample).astype(int)]
    data = read_bdf(path, wanted_ids=set(probe.tolist()))
    if data.grid_ids.size == probe.size and probe.max() < lookup.size:
        mapped = lookup[np.sort(data.grid_ids)]
        if (mapped >= 0).all():
            delta = data.points[np.argsort(data.grid_ids)] - volume_points[mapped]
            if np.abs(delta).max() <= tolerance:
                return _map_ids(lookup, shells, path.name), "node_ids"
    from scipy.spatial import cKDTree

    full = read_bdf(path, wanted_ids=set(ids.tolist()))
    distance, nearest = cKDTree(volume_points).query(full.points)
    if distance.size and distance.max() > tolerance:
        raise ValueError(
            f"{path.name}: {int((distance > tolerance).sum())} boundary node(s) are not "
            "nodes of the volume mesh."
        )
    local = _id_lookup(full.grid_ids)
    valid = shells >= 0
    return np.where(valid, nearest[local[np.where(valid, shells, 0)]], -1), "coordinates"


def mesh_from_workdir(workdir: Path, *, log: LogFunction | None = None) -> SourceMesh:
    """Source mesh from the named BDF outputs of any mesh backend in ``workdir``."""

    log = log or (lambda _message: None)
    workdir = Path(workdir)
    volume_path = workdir / VOLUME_FILE
    if not volume_path.is_file():
        raise FileNotFoundError(f"{volume_path} not found; run the mesher first.")
    started = time.perf_counter()
    volume = read_bdf(volume_path)
    lookup = _id_lookup(volume.grid_ids)
    cells = _cells_from_bdf(volume, lookup, volume_path.name)
    points = volume.points
    tolerance = 1.0e-7 * (float(np.linalg.norm(np.ptp(points, axis=0))) or 1.0)
    log(
        f"[OpenFOAM] {volume_path.name}: {len(points):,} nodes, "
        + ", ".join(f"{len(rows):,} {kind}" for kind, rows in cells.items())
        + f" ({time.perf_counter() - started:.1f} s).\n"
    )
    surfaces: dict[str, np.ndarray] = {}
    remapped = []
    for path in sorted(workdir.glob(f"{SURFACE_PREFIX}*.bdf")):
        stem = _surface_stem(path.name)
        if stem in NON_PATCH_SURFACES:
            continue
        data = read_bdf(path, wanted_ids=set())
        if not data.shells:
            continue
        shells = np.asarray([nodes for _pid, nodes in data.shells], dtype=np.int64)
        surfaces[stem], mode = _surface_nodes(path, shells, points, lookup, tolerance)
        if mode != "node_ids":
            remapped.append(stem)
    if not surfaces:
        raise ValueError(f"No {SURFACE_PREFIX}*.bdf boundary file found in {workdir}.")
    warnings = []
    if remapped:
        warnings.append("Boundary files mapped by coordinates: " + ", ".join(remapped))
    zones: dict[str, dict[str, np.ndarray]] = {}
    if "hex" in cells:
        chamber_rows = []
        for zone, name in CHAMBER_VOLUME_FILES.items():
            path = workdir / name
            if not path.is_file():
                continue
            data = read_bdf(path, wanted_ids=set())
            hexes = _map_ids(lookup, np.asarray(data.cells["hex"], dtype=np.int64), name)
            table = _row_keys(np.sort(cells["hex"], axis=1))
            found = _lookup_rows(table, _row_keys(np.sort(hexes, axis=1)))
            if (found < 0).any():
                start = len(cells["hex"])
                cells["hex"] = np.vstack((cells["hex"], hexes[found < 0]))
                found[found < 0] = np.arange(start, len(cells["hex"]))
                warnings.append(f"{name}: chamber cells absent from {VOLUME_FILE} were added.")
            zones[zone] = {"hex": found}
            chamber_rows.append(found)
        if chamber_rows:
            crack = np.setdiff1d(np.arange(len(cells["hex"])), np.concatenate(chamber_rows))
            zones = {"crack": {"hex": crack}, **zones}
    log(
        "[OpenFOAM] Boundary surfaces: "
        + ", ".join(f"{stem} ({len(rows):,})" for stem, rows in surfaces.items())
        + "\n"
    )
    return SourceMesh(points, cells, surfaces, zones, f"BDF outputs in {workdir.name}", warnings)


def parse_pshell_map(text: str) -> dict[int, str]:
    """Parse ``1=min,2=max,3=ymin`` into {PSHELL ID: surface stem}."""

    out = {}
    for item in re.split(r"[,;\s]+", text.strip()):
        if not item:
            continue
        key, sep, value = item.partition("=")
        if not sep or not key.strip().isdigit() or not value.strip():
            raise ValueError(f"Bad PSHELL map entry {item!r}; use ID=surface.")
        out[int(key)] = _surface_stem(value)
    return out


def mesh_from_combined_bdf(
    path: Path,
    *,
    pshell_surfaces: Mapping[int, str] | None = None,
    log: LogFunction | None = None,
) -> SourceMesh:
    """Source mesh from one merged BDF: volume cells plus PSHELL-tagged shells."""

    log = log or (lambda _message: None)
    path = Path(path)
    data = read_bdf(path)
    lookup = _id_lookup(data.grid_ids)
    cells = _cells_from_bdf(data, lookup, path.name)
    if not data.shells:
        raise ValueError(f"{path.name} has no CQUAD4/CTRIA3 boundary card.")
    pids = np.asarray([pid for pid, _nodes in data.shells], dtype=np.int64)
    shells = _map_ids(
        lookup, np.asarray([nodes for _pid, nodes in data.shells], dtype=np.int64), path.name
    )
    warnings = []
    if pshell_surfaces:
        names = {int(k): _surface_stem(v) for k, v in pshell_surfaces.items()}
        origin = "the PSHELL map"
    elif data.pshell_names:
        names = dict(data.pshell_names)
        origin = "the merger comments"
    else:
        ordered = sorted(set(pids.tolist()))
        defaults = list(MERGER_SURFACE_ORDER) + [f"trou_{k}" for k in range(1, len(ordered) + 1)]
        names = {pid: defaults[index] for index, pid in enumerate(ordered)}
        origin = "the merger order (assumed)"
        warnings.append(
            "PSHELL names assumed from the merger order (min, max, xmin, xmax, ymin, ymax, "
            "trou_1, ...); give a PSHELL map if the file was merged otherwise."
        )
    surfaces: dict[str, list[np.ndarray]] = {}
    for pid in sorted(set(pids.tolist())):
        surfaces.setdefault(names.get(pid, f"pshell_{pid}"), []).append(shells[pids == pid])
    log(f"[OpenFOAM] {path.name}: surface names from {origin}.\n")
    return SourceMesh(
        data.points,
        cells,
        {name: np.vstack(parts) for name, parts in surfaces.items()},
        {},
        f"combined BDF {path.name} (surface names from {origin})",
        warnings,
    )


# --------------------------------------------------------------------------- array helpers
def _row_keys(rows: np.ndarray) -> np.ndarray:
    """One fixed-width byte key per integer row (rows compare equal iff keys do)."""

    rows = np.ascontiguousarray(rows, dtype=np.int64)
    if rows.ndim != 2:
        raise ValueError("rows must be two-dimensional")
    width = rows.shape[1] * rows.dtype.itemsize
    return rows.view(np.dtype((np.void, width))).ravel()


def _lookup_rows(table: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Position of every query key in ``table`` (any order), -1 when absent."""

    if table.size == 0 or query.size == 0:
        return np.full(query.size, -1, dtype=np.int64)
    order = np.argsort(table, kind="stable")
    ordered = table[order]
    position = np.minimum(np.searchsorted(ordered, query), ordered.size - 1)
    return np.where(ordered[position] == query, order[position], -1)


def _merge_points(points: np.ndarray, tolerance: float) -> np.ndarray:
    """Representative node of every node once coincident nodes are merged."""

    _unique, first, inverse = np.unique(points, axis=0, return_index=True, return_inverse=True)
    representative = first[np.ravel(inverse)]
    if tolerance > 0.0 and len(points) > 1:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        from scipy.spatial import cKDTree

        pairs = cKDTree(points).query_pairs(tolerance, output_type="ndarray")
        if len(pairs):
            n = len(points)
            graph = coo_matrix(
                (
                    np.ones(len(pairs)),
                    (representative[pairs[:, 0]], representative[pairs[:, 1]]),
                ),
                shape=(n, n),
            )
            _count, labels = connected_components(graph, directed=False)
            smallest = np.full(labels.max() + 1, n, dtype=np.int64)
            np.minimum.at(smallest, labels, np.arange(n))
            representative = smallest[labels[representative]]
    return representative


def _pad_points(points: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """(n, 4, 3) face points; a triangle repeats its first node in slot 4."""

    return points[np.where(faces < 0, faces[:, :1], faces)]


def _newell(face_points: np.ndarray) -> np.ndarray:
    """Area vectors of (n, 4, 3) faces (a padded triangle adds a zero edge)."""

    return 0.5 * sum(
        np.cross(face_points[:, i], face_points[:, (i + 1) % 4]) for i in range(4)
    )


def _zones_from_mouths(
    owner: np.ndarray,
    neighbour: np.ndarray,
    patches: Sequence[Mapping],
    mouths: Sequence[np.ndarray],
    n_cells: int,
) -> dict[str, np.ndarray]:
    """Crack and chamber cell zones of a mesh read without them (a combined BDF).

    The crack mouths cut the cell graph into parts: the parts that touch the
    inlet and outlet patches are the chambers, the rest is the crack.
    """

    cut = np.zeros(len(neighbour), dtype=bool)
    for faces in mouths:
        cut[faces] = True
    a, b = owner[: len(neighbour)][~cut], neighbour[~cut]
    # Minimum-label propagation with pointer jumping: label[i] <= i, same part.
    label = np.arange(n_cells)
    while True:
        low = np.minimum(label[a], label[b])
        new = label.copy()
        np.minimum.at(new, a, low)
        np.minimum.at(new, b, low)
        new = new[new]
        if np.array_equal(new, label):
            break
        label = new

    def part(name: str) -> np.ndarray:
        for patch in patches:
            if patch["name"] == name and patch["nFaces"]:
                start = patch["startFace"]
                return np.unique(label[owner[start : start + patch["nFaces"]]])
        return np.empty(0, dtype=label.dtype)

    inlet, outlet = part("inlet"), part("outlet")
    if inlet.size != 1 or outlet.size != 1 or inlet[0] == outlet[0]:
        return {}
    crack = np.nonzero((label != inlet[0]) & (label != outlet[0]))[0]
    if not crack.size:
        return {}
    return {
        "crack": crack,
        "inletChamber": np.nonzero(label == inlet[0])[0],
        "outletChamber": np.nonzero(label == outlet[0])[0],
    }


def _collapse_faces(faces: np.ndarray) -> np.ndarray:
    """Drop the repeated nodes of collapsed faces; < 3 distinct nodes gives a -1 row."""

    faces = faces.copy()
    ordered = np.sort(faces, axis=1)
    repeated = ((ordered[:, 1:] == ordered[:, :-1]) & (ordered[:, 1:] >= 0)).any(axis=1)
    for row in np.nonzero(repeated)[0]:
        kept = list(dict.fromkeys(int(node) for node in faces[row] if node >= 0))
        faces[row] = (kept + [-1] * 4)[:4] if len(kept) >= 3 else (-1, -1, -1, -1)
    return faces


def hex_pyramid_margin(points: np.ndarray, hexes: np.ndarray) -> np.ndarray:
    """Smallest face-pyramid volume of each hexahedron over that of a box (V/6).

    The cell centre is OpenFOAM's (pyramid decomposition about the mean of the
    face centres), so a negative value is a face-pyramid failure in checkMesh.
    Zero-volume cells get +inf: they are dropped later, not split.
    """

    faces = np.asarray(hexes)[:, CELL_FACES["hex"]].reshape(-1, 4)
    centres, areas = _openfoam_face_geometry(points, faces)
    centres = centres.reshape(-1, 6, 3)
    areas = areas.reshape(-1, 6, 3)
    estimate = centres.mean(axis=1)
    pyramids = np.einsum("nfi,nfi->nf", areas, centres - estimate[:, None])
    volume3 = pyramids.sum(axis=1)
    dead = np.abs(volume3) <= VSMALL
    volume3 = np.where(dead, 1.0, volume3)
    centre = (pyramids[:, :, None] * (0.75 * centres + 0.25 * estimate[:, None])).sum(axis=1)
    centre /= volume3[:, None]
    margin = 6.0 * np.einsum("nfi,nfi->nf", areas, centres - centre[:, None]) / volume3[:, None]
    return np.where(dead, np.inf, margin.min(axis=1))


def _orient_and_split(
    hexes: np.ndarray,
    points: np.ndarray,
    xy_id: np.ndarray,
    z_mid: np.ndarray,
    settings: OpenFOAMSettings,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Bottom(0-3)/top(4-7) order for vertical-column hexahedra and the split choice.

    Returns the reordered hexahedra, the split flag, the diagonal flag (True
    for 0-2/4-6) and the number of vertical-column hexahedra.
    """

    hexes = hexes.copy()
    vertical = np.zeros(len(hexes), dtype=bool)
    for permutation in HEX_AXIS_PERMUTATIONS:
        candidate = hexes[:, permutation]
        ids = xy_id[candidate]
        found = np.all(ids[:, :4] == ids[:, 4:], axis=1) & ~vertical
        hexes[found] = candidate[found]
        vertical |= found
    z = points[:, 2]
    flip = vertical & (z[hexes[:, 4:]].mean(axis=1) < z[hexes[:, :4]].mean(axis=1))
    hexes[flip] = hexes[flip][:, [4, 5, 6, 7, 0, 1, 2, 3]]
    split = np.zeros(len(hexes), dtype=bool)
    use02 = np.ones(len(hexes), dtype=bool)
    if settings.cell_split == "none" or not vertical.any():
        return hexes, split, use02, int(vertical.sum())
    rows = np.nonzero(vertical)[0]
    H = hexes[rows]
    xy = xy_id[H[:, :4]]
    # Column-consistent diagonal: the mid-surface jump across each candidate
    # internal face uses XY-keyed data only, and ties go to the diagonal holding
    # the smallest XY key, so every layer of a column cuts the same XY pair.
    zm = z_mid[xy]
    d02 = np.abs(zm[:, 1] - zm[:, 3])
    d13 = np.abs(zm[:, 0] - zm[:, 2])
    smallest_on_02 = np.minimum(xy[:, 0], xy[:, 2]) < np.minimum(xy[:, 1], xy[:, 3])
    use02[rows] = np.where(d02 == d13, smallest_on_02, d02 < d13)
    if settings.cell_split == "prism":
        split[rows] = True
    else:
        weak = hex_pyramid_margin(points, H) < settings.pyramid_margin
        # Decide per vertical column (footprint) so stacked cells stay conformal.
        _unique, column = np.unique(np.sort(xy, axis=1), axis=0, return_inverse=True)
        column = np.ravel(column)
        column_weak = np.zeros(column.max() + 1, dtype=bool)
        np.logical_or.at(column_weak, column, weak)
        split[rows] = column_weak[column]
    return hexes, split, use02, int(vertical.sum())


# --------------------------------------------------------------------------- polyMesh
@dataclass
class PolyMesh:
    """An OpenFOAM polyMesh with patches, zones and the checks of its geometry."""

    points: np.ndarray
    faces: np.ndarray
    owner: np.ndarray
    neighbour: np.ndarray
    patches: list[dict[str, object]]
    cell_zones: dict[str, np.ndarray]
    face_zones: dict[str, tuple[np.ndarray, np.ndarray]]
    cell_centres: np.ndarray = field(default_factory=lambda: np.empty((0, 3)))
    cell_volumes: np.ndarray = field(default_factory=lambda: np.empty(0))
    report: dict[str, object] = field(default_factory=dict)

    @property
    def n_cells(self) -> int:
        if not self.owner.size:
            return 0
        top = int(self.owner.max())
        return max(top, int(self.neighbour.max()) if self.neighbour.size else top) + 1

    @property
    def n_internal_faces(self) -> int:
        return int(self.neighbour.size)


def build_polymesh(
    source: SourceMesh,
    settings: OpenFOAMSettings | None = None,
    *,
    log: LogFunction | None = None,
) -> PolyMesh:
    """Convert a source mesh to a checked OpenFOAM polyMesh with named patches and zones."""

    settings = (settings or OpenFOAMSettings()).validated()
    log = log or (lambda _message: None)
    started = time.perf_counter()
    warnings = list(source.warnings)
    # OpenFOAM works in metres: length_scale converts other mesh units (1e-3 for mm).
    points = np.asarray(source.points, dtype=np.float64) * settings.length_scale
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError("The source mesh needs finite (n, 3) coordinates.")
    span = float(np.linalg.norm(np.ptp(points, axis=0))) or 1.0
    representative = _merge_points(points, settings.merge_tolerance * span)
    n_merged = int(len(points) - np.unique(representative).size)
    if n_merged:
        log(f"[OpenFOAM] Merged {n_merged:,} coincident node(s).\n")

    # XY identity of every node: the cells of a vertical column share it.
    quantum = max(settings.merge_tolerance, 1.0e-7) * span
    _unique, xy_id = np.unique(
        np.round(points[:, :2] / quantum).astype(np.int64), axis=0, return_inverse=True
    )
    xy_id = np.ravel(xy_id)
    z_low = np.full(xy_id.max() + 1, np.inf)
    z_high = np.full(xy_id.max() + 1, -np.inf)
    np.minimum.at(z_low, xy_id, points[:, 2])
    np.maximum.at(z_high, xy_id, points[:, 2])
    z_mid = 0.5 * (z_low + z_high)

    kinds = sorted(source.cells)
    stats = {kind: 0 for kind in CELL_NODE_COUNTS}
    face_blocks, parent_blocks, cell_blocks, origin_blocks = [], [], [], []
    split_keys, split_pairs = [], []
    n_cells = 0

    def add_cells(kind: str, nodes: np.ndarray, rows: np.ndarray, kind_index: int) -> None:
        nonlocal n_cells
        template = CELL_FACES[kind]
        count = len(nodes)
        faces = nodes[:, np.where(template < 0, 0, template)].reshape(-1, 4)
        faces[np.tile(template < 0, (count, 1))] = -1
        face_blocks.append(faces)
        parent_blocks.append(faces.copy())
        cell_blocks.append(np.repeat(np.arange(n_cells, n_cells + count), len(template)))
        origin_blocks.append(np.column_stack((np.full(count, kind_index), rows)))
        n_cells += count
        stats[kind] += count

    for kind_index, kind in enumerate(kinds):
        nodes = representative[np.asarray(source.cells[kind], dtype=np.int64)]
        rows = np.arange(len(nodes))
        if kind == "hex":
            nodes, split, use02, n_vertical = _orient_and_split(
                nodes, points, xy_id, z_mid, settings
            )
            stats["hex_in_vertical_columns"] = n_vertical
            stats["hex_split_into_prisms"] = int(split.sum())
            if split.any():
                hexes, flags = nodes[split], use02[split]
                prisms = np.empty((len(hexes), 2, 6), dtype=np.int64)
                for k in range(2):
                    prisms[:, k] = np.where(
                        flags[:, None], hexes[:, PRISMS_02[k]], hexes[:, PRISMS_13[k]]
                    )
                before = len(face_blocks)
                add_cells("prism", prisms.reshape(-1, 6), np.repeat(rows[split], 2), kind_index)
                # A prism triangle inherits its hexahedron's bottom or top quad.
                parents = parent_blocks[before]
                role = np.tile(np.arange(len(CELL_FACES["prism"])), 2 * len(hexes))
                hex_of_face = np.repeat(np.arange(len(hexes)), 2 * len(CELL_FACES["prism"]))
                parents[role == 0] = hexes[hex_of_face[role == 0], :4]
                parents[role == 1] = hexes[hex_of_face[role == 1], 4:]
                split_keys += [hexes[:, :4], hexes[:, 4:]]
                split_pairs += [
                    np.where(flags[:, None], hexes[:, [0, 2]], hexes[:, [1, 3]]),
                    np.where(flags[:, None], hexes[:, [4, 6]], hexes[:, [5, 7]]),
                ]
            nodes, rows = nodes[~split], rows[~split]
        if len(nodes):
            add_cells(kind, nodes, rows, kind_index)

    faces = np.vstack(face_blocks)
    parents = np.sort(np.vstack(parent_blocks), axis=1)
    face_cell = np.concatenate(cell_blocks)
    origin = np.vstack(origin_blocks)

    # A quad of an unsplit cell shared with a split column is cut along the
    # column's diagonal too, so the mesh stays conformal (the cell becomes a
    # polyhedron bounded by triangles there).
    if split_keys:
        table = _row_keys(np.sort(np.vstack(split_keys), axis=1))
        pairs = np.vstack(split_pairs)
        quads = np.nonzero(faces[:, 3] >= 0)[0]
        position = _lookup_rows(table, _row_keys(np.sort(faces[quads], axis=1)))
        hit = quads[position >= 0]
        if hit.size:
            pair = pairs[position[position >= 0]]
            a, b, c, d = faces[hit].T
            on_ac = ((a == pair[:, 0]) & (c == pair[:, 1])) | ((a == pair[:, 1]) & (c == pair[:, 0]))
            first = np.where(on_ac[:, None], np.column_stack((a, b, c)), np.column_stack((a, b, d)))
            second = np.where(on_ac[:, None], np.column_stack((a, c, d)), np.column_stack((b, c, d)))
            pad = np.full((hit.size, 1), -1)
            keep = np.ones(len(faces), dtype=bool)
            keep[hit] = False
            faces = np.vstack(
                (faces[keep], np.hstack((first, pad)), np.hstack((second, pad)))
            )
            parents = np.vstack((parents[keep], parents[hit], parents[hit]))
            face_cell = np.concatenate((face_cell[keep], face_cell[hit], face_cell[hit]))
            stats["polyhedra_next_to_split_columns"] = int(np.unique(face_cell[-hit.size:]).size)

    # Collapsed faces (merged nodes) lose repeated nodes or vanish.
    faces = _collapse_faces(faces)
    alive = faces[:, 0] >= 0
    faces, parents, face_cell = faces[alive], parents[alive], face_cell[alive]

    # Orientation from each cell's signed volume; zero-volume cells are dropped.
    fp = _pad_points(points, faces)
    count = (faces >= 0).sum(axis=1)
    centre = (fp * (faces >= 0)[:, :, None]).sum(axis=1) / count[:, None]
    signed = np.zeros(n_cells)
    np.add.at(signed, face_cell, np.einsum("ij,ij->i", centre, _newell(fp)) / 3.0)
    del fp, centre
    magnitude = np.abs(signed)
    scale = float(np.median(magnitude[magnitude > 0.0])) if (magnitude > 0.0).any() else 0.0
    dead = magnitude <= 1.0e-9 * scale
    flip = (signed < 0.0)[face_cell]
    triangle = faces[:, 3] < 0
    faces[flip & triangle, :3] = faces[flip & triangle, 2::-1]
    faces[flip & ~triangle] = faces[flip & ~triangle][:, ::-1]
    n_dead = int(dead.sum())
    if n_dead:
        warnings.append(f"{n_dead} zero-volume cell(s) on closed contact were dropped.")
        log(f"[OpenFOAM] Dropped {n_dead:,} zero-volume cell(s).\n")
        keep = ~dead[face_cell]
        faces, parents, face_cell = faces[keep], parents[keep], face_cell[keep]
        face_cell = (np.cumsum(~dead) - 1)[face_cell]
        origin = origin[~dead]
        n_cells -= n_dead

    # Face matching: two copies -> internal, one -> boundary.
    keys = np.sort(faces, axis=1)
    order = np.lexsort(keys.T[::-1])
    ordered = keys[order]
    same = np.all(ordered[1:] == ordered[:-1], axis=1)
    if (same[1:] & same[:-1]).any():
        raise ValueError("Non-manifold mesh: a face is shared by more than two cells.")
    i1 = order[np.nonzero(same)[0]]
    i2 = order[np.nonzero(same)[0] + 1]
    c1, c2 = face_cell[i1], face_cell[i2]
    if (c1 == c2).any():
        raise ValueError("A cell holds the same face twice.")
    s1 = _newell(_pad_points(points, faces[i1]))
    s2 = _newell(_pad_points(points, faces[i2]))
    wrong = int((np.einsum("ij,ij->i", s1, s2) > 0.0).sum())
    if wrong:
        raise ValueError(f"{wrong} internal face(s) are oriented alike by both cells.")
    first_owns = c1 < c2
    internal = np.where(first_owns[:, None], faces[i1], faces[i2])
    internal_parents = np.where(first_owns[:, None], parents[i1], parents[i2])
    own = np.minimum(c1, c2)
    nei = np.maximum(c1, c2)
    sequence = np.lexsort((nei, own))  # upper-triangular order
    internal, internal_parents = internal[sequence], internal_parents[sequence]
    own, nei = own[sequence], nei[sequence]
    is_boundary = np.ones(len(faces), dtype=bool)
    is_boundary[i1] = False
    is_boundary[i2] = False
    bfaces, bparents, bcells = faces[is_boundary], parents[is_boundary], face_cell[is_boundary]

    # Patches from the named surfaces; the first matching rule wins.
    rules = (
        parse_patch_rules(settings.patches)
        if settings.patches.strip()
        else default_patch_rules(
            source.surfaces,
            flow_direction=settings.flow_direction,
            side_walls=settings.side_walls,
        )
    )
    surface_keys = {}
    for name, quads in source.surfaces.items():
        quads = np.asarray(quads, dtype=np.int64).reshape(-1, 4)
        mapped = np.where(quads >= 0, representative[np.where(quads >= 0, quads, 0)], -1)
        surface_keys[name] = np.unique(_row_keys(np.sort(mapped, axis=1)))
    bkeys = _row_keys(bparents)
    assigned = np.full(len(bfaces), -1, dtype=np.int64)
    absent = []
    for index, rule in enumerate(rules):
        members = [surface_keys[s] for s in rule.surfaces if s in surface_keys]
        absent += [s for s in rule.surfaces if s not in surface_keys]
        if members:
            hit = (_lookup_rows(np.concatenate(members), bkeys) >= 0) & (assigned < 0)
            assigned[hit] = index
    patch_table = [(rule.name, rule.type) for rule in rules]
    if (assigned < 0).any():
        n_other = int((assigned < 0).sum())
        warnings.append(
            f"{n_other} boundary face(s) belong to no named surface; they form the wall "
            "patch 'otherWalls'."
        )
        patch_table.append(("otherWalls", "wall"))
        assigned[assigned < 0] = len(patch_table) - 1
    patches, face_parts, owner_parts = [], [internal], [own]
    start = len(internal)
    for index, (name, kind) in enumerate(patch_table):
        members = np.nonzero(assigned == index)[0]
        members = members[np.argsort(bcells[members], kind="stable")]
        face_parts.append(bfaces[members])
        owner_parts.append(bcells[members])
        patches.append(
            {"name": name, "type": kind, "nFaces": int(members.size), "startFace": int(start)}
        )
        start += members.size
    empty = [p["name"] for p in patches if p["name"] in ("inlet", "outlet") and not p["nFaces"]]
    if empty and settings.solver != "none":
        raise ValueError(
            "Empty patch(es) " + ", ".join(empty) + ": check flow_direction, the patch rules "
            "and the boundary surfaces of the mesh."
        )
    all_faces = np.vstack(face_parts)
    all_owner = np.concatenate(owner_parts)

    # Keep only the points used by faces, in their original order.
    used = np.zeros(len(points), dtype=bool)
    used[all_faces[all_faces >= 0]] = True
    renumber = np.cumsum(used) - 1
    all_faces = np.where(all_faces >= 0, renumber[np.where(all_faces >= 0, all_faces, 0)], -1)
    out_points = points[used]

    # Cell zones follow every split or collapsed child cell.
    cell_zones: dict[str, np.ndarray] = {}
    for zone, members in source.cell_zones.items():
        mask = np.zeros(len(origin), dtype=bool)
        for kind, zone_rows in members.items():
            if kind not in kinds:
                continue
            selected = np.zeros(len(source.cells[kind]), dtype=bool)
            selected[np.asarray(zone_rows, dtype=np.int64)] = True
            match = origin[:, 0] == kinds.index(kind)
            mask[match] |= selected[origin[match, 1]]
        if mask.any():
            cell_zones[zone] = np.nonzero(mask)[0]

    # Face zones on the crack entrance and exit when they are internal (chambers),
    # oriented along the flow so that a flux sum is the leakage rate.
    face_zones: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    axis = "xy"[settings.flow_axis]
    ends = (f"{axis}min", f"{axis}max")[:: settings.flow_sign]
    flow = np.zeros(3)
    flow[settings.flow_axis] = settings.flow_sign
    internal_keys = _row_keys(internal_parents)
    for zone, surface in zip(("crackInlet", "crackOutlet"), ends):
        if surface in surface_keys:
            hit = np.nonzero(_lookup_rows(surface_keys[surface], internal_keys) >= 0)[0]
            if hit.size:
                normal = _newell(_pad_points(out_points, all_faces[hit]))
                face_zones[zone] = (hit, (normal @ flow) < 0.0)
    if not cell_zones and len(face_zones) == 2:
        # A combined BDF carries no volume groups; the crack mouths still split it.
        cell_zones = _zones_from_mouths(
            all_owner, nei, patches, [item[0] for item in face_zones.values()], len(origin)
        )

    poly = PolyMesh(out_points, all_faces, all_owner, nei, patches, cell_zones, face_zones)
    quality = mesh_quality(poly)
    if quality["nonpositive_volumes"]:
        raise ValueError(f"{quality['nonpositive_volumes']} cell(s) have a non-positive volume.")
    if quality["open_cells"]:
        raise ValueError(f"{quality['open_cells']} cell(s) are not closed by their faces.")
    if quality["face_pyramid_failures"]:
        warnings.append(
            f"{quality['face_pyramid_failures']} face pyramid(s) fail OpenFOAM's check"
            + ("; export with cell_split = prism" if settings.cell_split != "prism" else "")
            + "."
        )
    if quality["abrupt_size_jump_faces_gt20"]:
        warnings.append(
            f"{quality['abrupt_size_jump_faces_gt20']} internal face(s) join cells whose sizes "
            f"differ by more than 20x (max {quality['max_cell_size_jump']:.0f}x), typically "
            "chamber cells beside thin crack layers. The case interpolates the pressure "
            "coefficient harmonically to stay stable; a smoother chamber grading is more accurate."
        )
    for message in warnings:
        log(f"[OpenFOAM] Warning: {message}\n")
    poly.report = {
        "source": source.description,
        "cell_counts": {kind: int(value) for kind, value in stats.items() if value},
        "n_points": int(len(out_points)),
        "n_cells": int(poly.n_cells),
        "n_faces": int(len(all_faces)),
        "n_internal_faces": int(poly.n_internal_faces),
        "merged_points": n_merged,
        "dropped_zero_volume_cells": n_dead,
        "patches": patches,
        "patch_rules": [asdict(rule) for rule in rules],
        "rule_surfaces_absent": sorted(set(absent)),
        "cell_zones": {zone: int(cells.size) for zone, cells in cell_zones.items()},
        "face_zones": {zone: int(item[0].size) for zone, item in face_zones.items()},
        "quality": quality,
        "warnings": warnings,
        "build_seconds": round(time.perf_counter() - started, 3),
    }
    log(
        f"[OpenFOAM] polyMesh: {poly.n_cells:,} cells, {len(all_faces):,} faces, "
        f"{len(patches)} patches, total volume {quality['total_volume']:.6g} m3; "
        f"max non-orthogonality {quality['max_non_orthogonality_deg']:.1f} deg, "
        f"max skewness {quality['max_skewness']:.3g}.\n"
    )
    return poly


# --------------------------------------------------------------------------- quality
def _openfoam_face_geometry(points: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, ...]:
    """Face centres and area vectors computed as OpenFOAM does (fan about the mean)."""

    fp = _pad_points(points, faces)
    triangle = faces[:, 3] < 0
    centres = np.empty((len(faces), 3))
    areas = np.empty((len(faces), 3))
    t = fp[triangle][:, :3]
    centres[triangle] = t.mean(axis=1)
    areas[triangle] = 0.5 * np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    q = fp[~triangle]
    mean = q.mean(axis=1)
    sum_n = np.zeros_like(mean)
    sum_a = np.zeros(len(q))
    sum_ac = np.zeros_like(mean)
    for i in range(4):
        this, following = q[:, i], q[:, (i + 1) % 4]
        n = np.cross(following - this, mean - this)
        a = np.linalg.norm(n, axis=1)
        sum_n += n
        sum_a += a
        sum_ac += a[:, None] * (this + following + mean)
    degenerate = sum_a < ROOTVSMALL
    centres[~triangle] = np.where(
        degenerate[:, None], mean, sum_ac / np.where(degenerate, 1.0, sum_a)[:, None] / 3.0
    )
    areas[~triangle] = np.where(degenerate[:, None], 0.0, 0.5 * sum_n)
    return centres, areas


def mesh_quality(poly: PolyMesh) -> dict[str, object]:
    """OpenFOAM-style geometry checks; also stores cell centres and volumes on ``poly``."""

    points, faces, owner, neighbour = poly.points, poly.faces, poly.owner, poly.neighbour
    n_cells = poly.n_cells
    n_int = neighbour.size
    fc, fa = _openfoam_face_geometry(points, faces)
    # Cell centres: pyramid decomposition about the mean of the face centres.
    estimate = np.zeros((n_cells, 3))
    counts = np.zeros(n_cells)
    np.add.at(estimate, owner, fc)
    np.add.at(counts, owner, 1.0)
    np.add.at(estimate, neighbour, fc[:n_int])
    np.add.at(counts, neighbour, 1.0)
    estimate /= counts[:, None]
    volume3 = np.zeros(n_cells)
    moment = np.zeros((n_cells, 3))
    v = np.einsum("ij,ij->i", fa, fc - estimate[owner])
    np.add.at(volume3, owner, v)
    np.add.at(moment, owner, v[:, None] * (0.75 * fc + 0.25 * estimate[owner]))
    v = np.einsum("ij,ij->i", fa[:n_int], estimate[neighbour] - fc[:n_int])
    np.add.at(volume3, neighbour, v)
    np.add.at(moment, neighbour, v[:, None] * (0.75 * fc[:n_int] + 0.25 * estimate[neighbour]))
    small = np.abs(volume3) <= VSMALL
    centres = np.where(small[:, None], estimate, moment / np.where(small, 1.0, volume3)[:, None])
    volumes = volume3 / 3.0
    poly.cell_centres, poly.cell_volumes = centres, volumes

    # Closedness and aspect ratio (primitiveMesh::checkClosedCells).
    sum_closed = np.zeros((n_cells, 3))
    sum_mag = np.zeros((n_cells, 3))
    np.add.at(sum_closed, owner, fa)
    np.add.at(sum_mag, owner, np.abs(fa))
    np.subtract.at(sum_closed, neighbour, fa[:n_int])
    np.add.at(sum_mag, neighbour, np.abs(fa[:n_int]))
    openness = (np.abs(sum_closed) / (sum_mag + VSMALL)).max(axis=1)
    positive = volumes > VSMALL
    aspect = np.maximum(
        sum_mag.max(axis=1) / (sum_mag.min(axis=1) + VSMALL),
        sum_mag.sum(axis=1) / 6.0 / np.cbrt(np.where(positive, volumes, 1.0)) ** 2,
    )

    # Face pyramids (primitiveMesh::checkFacePyramids, strict sign).
    bad = np.einsum("ij,ij->i", fa, fc - centres[owner]) < 0.0
    bad[:n_int] |= np.einsum("ij,ij->i", fa[:n_int], centres[neighbour] - fc[:n_int]) < 0.0

    # Non-orthogonality and skewness (internal faces, then boundary faces).
    d = centres[neighbour] - centres[owner[:n_int]]
    mag_a = np.linalg.norm(fa, axis=1)
    cosine = np.einsum("ij,ij->i", d, fa[:n_int]) / (
        np.linalg.norm(d, axis=1) * mag_a[:n_int] + VSMALL
    )
    angle = np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0)))
    cpf_int = fc[:n_int] - centres[owner[:n_int]]
    sv = cpf_int - (np.einsum("ij,ij->i", fa[:n_int], cpf_int) / (
        np.einsum("ij,ij->i", fa[:n_int], d) + ROOTVSMALL
    ))[:, None] * d
    skew_int = _skewness(points, faces[:n_int], fc[:n_int], sv, 0.2 * np.linalg.norm(d, axis=1))
    cpf = fc[n_int:] - centres[owner[n_int:]]
    normal = fa[n_int:] / (mag_a[n_int:, None] + VSMALL)
    dn = normal * np.einsum("ij,ij->i", normal, cpf)[:, None]
    skew_b = _skewness(points, faces[n_int:], fc[n_int:], cpf - dn, 0.4 * np.linalg.norm(dn, axis=1))
    skewness = np.concatenate((skew_int, skew_b))
    # Size jump across a face: ratio of the two face-normal centre distances.
    unit = fa[:n_int] / (mag_a[:n_int, None] + VSMALL)
    near = np.abs(np.einsum("ij,ij->i", unit, cpf_int))
    far = np.abs(np.einsum("ij,ij->i", unit, d)) - near
    jump = np.maximum(near, far) / (np.minimum(near, far) + VSMALL)
    return {
        "total_volume": float(volumes.sum()),
        "min_volume": float(volumes.min()) if n_cells else 0.0,
        "max_volume": float(volumes.max()) if n_cells else 0.0,
        "nonpositive_volumes": int((volumes <= 0.0).sum()),
        "open_cells": int((openness > 1.0e-6).sum()),
        "max_openness": float(openness.max()) if n_cells else 0.0,
        "face_pyramid_failures": int(bad.sum()),
        "max_non_orthogonality_deg": float(angle.max()) if n_int else 0.0,
        "mean_non_orthogonality_deg": float(angle.mean()) if n_int else 0.0,
        "severely_non_orthogonal_faces_gt70": int((angle > 70.0).sum()),
        "max_skewness": float(skewness.max()) if skewness.size else 0.0,
        "highly_skewed_faces_gt4": int((skewness > 4.0).sum()),
        "max_aspect_ratio": float(aspect.max()) if n_cells else 0.0,
        "high_aspect_ratio_cells_gt1000": int((aspect > 1000.0).sum()),
        "max_cell_size_jump": float(jump.max()) if n_int else 1.0,
        "abrupt_size_jump_faces_gt20": int((jump > 20.0).sum()),
        "min_face_area": float(mag_a.min()) if mag_a.size else 0.0,
    }


def _skewness(points, faces, centres, sv, base) -> np.ndarray:
    """|sv| / distance from the face centre to its edge along sv (OpenFOAM's skewness)."""

    if not len(faces):
        return np.empty(0)
    mag_sv = np.linalg.norm(sv, axis=1)
    hat = sv / (mag_sv[:, None] + ROOTVSMALL)
    reach = base + ROOTVSMALL
    fp = _pad_points(points, faces)
    for i in range(4):
        reach = np.maximum(reach, np.abs(np.einsum("ij,ij->i", hat, fp[:, i] - centres)))
    return mag_sv / reach


# --------------------------------------------------------------------------- writers
BANNER = (
    "/*--------------------------------*- C++ -*----------------------------------*\\\n"
    "  =========                 |\n"
    "  \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox\n"
    "   \\\\    /   O peration     |\n"
    "    \\\\  /    A nd           | Written by DEM Crack Surface Mesher\n"
    "     \\\\/     M anipulation  |\n"
    "\\*---------------------------------------------------------------------------*/\n"
)
FOOTER = "\n\n// ************************************************************************* //\n"


def _header(cls: str, obj: str, location: str, fmt: str = "ascii", note: str | None = None) -> str:
    text = BANNER + "FoamFile\n{\n    version     2.0;\n" + f"    format      {fmt};\n"
    if fmt == "binary":
        text += '    arch        "LSB;label=32;scalar=64";\n'
    if note:
        text += f'    note        "{note}";\n'
    text += f"    class       {cls};\n"
    text += f'    location    "{location}";\n    object      {obj};\n}}\n'
    return text + "// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n\n"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(text)


def _list_bytes(array: np.ndarray, fmt: str, kind: str) -> bytes:
    """One OpenFOAM List body (``n ( ... )``) of labels, scalars or vectors."""

    n = array.shape[0]
    if fmt == "binary":
        dtype = LABEL if kind == "label" else np.float64
        return f"{n}\n(".encode() + np.ascontiguousarray(array, dtype=dtype).tobytes() + b")"
    if kind == "vector":
        body = "\n".join("(%.17g %.17g %.17g)" % tuple(row) for row in array.tolist())
    elif kind == "scalar":
        body = "\n".join("%.17g" % value for value in array.tolist())
    else:
        body = "\n".join(map(str, array.tolist()))
    return f"{n}\n(\n{body}\n)".encode()


def _write_binary(path: Path, header: str, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(header.encode())
        stream.write(body)
        stream.write(FOOTER.encode())


def write_polymesh(case_directory: Path, poly: PolyMesh, fmt: str = "ascii") -> Path:
    """Write ``constant/polyMesh`` (points, faces, owner, neighbour, boundary, zones)."""

    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"fmt must be one of {SUPPORTED_FORMATS}")
    mesh_dir = Path(case_directory) / "constant" / "polyMesh"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    for stale in mesh_dir.iterdir():
        if stale.is_dir():
            shutil.rmtree(stale)
        else:
            stale.unlink()
    location = "constant/polyMesh"
    note = (
        f"nPoints:{len(poly.points)}  nCells:{poly.n_cells}  nFaces:{len(poly.faces)}  "
        f"nInternalFaces:{poly.n_internal_faces}"
    )
    _write_binary(
        mesh_dir / "points",
        _header("vectorField", "points", location, fmt),
        _list_bytes(poly.points, fmt, "vector"),
    )
    sizes = (poly.faces >= 0).sum(axis=1)
    flat = poly.faces[poly.faces >= 0]
    if fmt == "binary":
        offsets = np.concatenate(([0], np.cumsum(sizes)))
        body = _list_bytes(offsets, fmt, "label") + b"\n" + _list_bytes(flat, fmt, "label")
        _write_binary(mesh_dir / "faces", _header("faceCompactList", "faces", location, fmt), body)
    else:
        lines = [
            f"{size}({' '.join(map(str, row[:size]))})"
            for size, row in zip(sizes.tolist(), poly.faces.tolist())
        ]
        body = f"{len(lines)}\n(\n" + "\n".join(lines) + "\n)"
        _write_binary(mesh_dir / "faces", _header("faceList", "faces", location, fmt), body.encode())
    for name, values in (("owner", poly.owner), ("neighbour", poly.neighbour)):
        _write_binary(
            mesh_dir / name,
            _header("labelList", name, location, fmt, note),
            _list_bytes(values, fmt, "label"),
        )
    text = f"{len(poly.patches)}\n(\n"
    for patch in poly.patches:
        text += f"    {patch['name']}\n    {{\n        type            {patch['type']};\n"
        if patch["type"] in ("wall", "symmetry", "symmetryPlane", "empty"):
            text += f"        inGroups        1({patch['type']});\n"
        text += (
            f"        nFaces          {patch['nFaces']};\n"
            f"        startFace       {patch['startFace']};\n    }}\n"
        )
    _write_text(mesh_dir / "boundary", _header("polyBoundaryMesh", "boundary", location) + text + ")" + FOOTER)
    if poly.cell_zones:
        text = f"{len(poly.cell_zones)}\n(\n"
        for name, cells in poly.cell_zones.items():
            text += f"{name}\n{{\n    type cellZone;\n    cellLabels List<label> "
            text += _list_bytes(np.asarray(cells), "ascii", "label").decode() + ";\n}\n"
        _write_text(mesh_dir / "cellZones", _header("regIOobject", "cellZones", location) + text + ")" + FOOTER)
    if poly.face_zones:
        text = f"{len(poly.face_zones)}\n(\n"
        for name, (zone_faces, flip) in poly.face_zones.items():
            text += f"{name}\n{{\n    type faceZone;\n    faceLabels List<label> "
            text += _list_bytes(np.asarray(zone_faces), "ascii", "label").decode() + ";\n"
            text += "    flipMap List<bool> "
            text += _list_bytes(np.asarray(flip, dtype=int), "ascii", "label").decode() + ";\n}\n"
        _write_text(mesh_dir / "faceZones", _header("regIOobject", "faceZones", location) + text + ")" + FOOTER)
    return mesh_dir


# --------------------------------------------------------------------------- case files
def _gamma(settings: OpenFOAMSettings) -> float:
    return settings.heat_capacity / (settings.heat_capacity - settings.gas_constant)


def _flow_fraction(poly: PolyMesh, settings: OpenFOAMSettings) -> np.ndarray:
    """0 at the crack entrance, 1 at its exit (chambers clipped), per cell."""

    coordinate = poly.cell_centres[:, settings.flow_axis] * settings.flow_sign
    crack = poly.cell_zones.get("crack")
    if crack is not None and crack.size:
        nodes = np.unique(poly.faces[np.isin(poly.owner, crack)])
        nodes = nodes[nodes >= 0]
        span = poly.points[nodes, settings.flow_axis] * settings.flow_sign
    else:
        span = poly.points[:, settings.flow_axis] * settings.flow_sign
    low, high = float(span.min()), float(span.max())
    return np.clip((coordinate - low) / max(high - low, VSMALL), 0.0, 1.0)


def _boundary_conditions(poly: PolyMesh, table: Mapping[str, Sequence[str]]) -> str:
    """boundaryField from a table keyed by patch name or patch type."""

    text = "\nboundaryField\n{\n"
    for patch in poly.patches:
        name, kind = patch["name"], patch["type"]
        if kind in ("symmetry", "symmetryPlane", "empty"):
            body = [f"type {kind};"]
        elif name in table:
            body = table[name]
        elif kind == "patch":
            body = table["opening"]
        else:
            body = table["wall"]
        text += f"    {name}\n    {{\n" + "".join(f"        {line}\n" for line in body) + "    }\n"
    return text + "}\n"


def _write_field(
    case: Path,
    name: str,
    cls: str,
    dimensions: str,
    internal: np.ndarray | str,
    boundary: str,
    fmt: str,
) -> None:
    if isinstance(internal, str):
        body = f"internalField   {internal};\n".encode()
    else:
        kind = "scalar" if internal.ndim == 1 else "vector"
        body = (
            f"internalField   nonuniform List<{kind}> ".encode()
            + _list_bytes(internal, fmt, kind)
            + b";\n"
        )
    _write_binary(
        case / "0" / name,
        _header(cls, name, "0", fmt),
        f"dimensions      {dimensions};\n\n".encode() + body + boundary.encode(),
    )


def _dictionary(case: Path, location: str, name: str, body: str) -> None:
    _write_text(case / location / name, _header("dictionary", name, location) + body + FOOTER)


def _functions(poly: PolyMesh, settings: OpenFOAMSettings, fields_list: Sequence[str]) -> str:
    org = settings.openfoam_version == "org"
    text = "functions\n{\n"
    if org:
        text += (
            "    residuals\n    {\n        type            residuals;\n"
            '        libs            ("libutilityFunctionObjects.so");\n'
            f"        fields          ({' '.join(fields_list)});\n    }}\n"
        )
    else:
        text += (
            "    residuals\n    {\n        type            solverInfo;\n"
            '        libs            ("libutilityFunctionObjects.so");\n'
            f"        fields          ({' '.join(fields_list)});\n"
            "        writeResidualFields no;\n    }\n"
        )
    regions = [("patch", name) for name in ("inlet", "outlet") if _has_patch(poly, name)]
    regions += [("faceZone", name) for name in poly.face_zones]
    for kind, name in regions:
        text += f"    flowRate_{name}\n    {{\n        type            surfaceFieldValue;\n"
        text += '        libs            ("libfieldFunctionObjects.so");\n'
        if org:
            text += f"        select          {kind};\n        {kind:<16}{name};\n"
            operation = "orientedSum" if kind == "faceZone" else "sum"
        else:
            text += f"        regionType      {kind};\n        name            {name};\n"
            operation = "sum"
        text += (
            f"        operation       {operation};\n        fields          (phi);\n"
            "        writeFields     false;\n        log             true;\n"
            "        writeControl    timeStep;\n        writeInterval   1;\n    }\n"
        )
    return text + "}\n"


def _has_patch(poly: PolyMesh, name: str) -> bool:
    return any(p["name"] == name and p["nFaces"] for p in poly.patches)


def _pressure_solver(relative_tolerance: float) -> str:
    """PCG preconditioned by a GAMG cycle: plain GAMG stalls on thin, high-aspect cells."""

    return (
        "    \"p.*\"\n    {\n        solver          PCG;\n        preconditioner\n        {\n"
        "            preconditioner  GAMG;\n            smoother        DICGaussSeidel;\n"
        "            agglomerator    faceAreaPair;\n            nCellsInCoarsestLevel 50;\n"
        "            mergeLevels     1;\n        }\n        tolerance       1e-12;\n"
        f"        relTol          {relative_tolerance!r};\n        maxIter         200;\n    }}\n\n"
    )


def write_case(case: Path, poly: PolyMesh, settings: OpenFOAMSettings) -> list[str]:
    """Write ``0/``, ``constant/`` and ``system/`` for the selected solver."""

    case = Path(case)
    org = settings.openfoam_version == "org"
    fmt = settings.write_format
    written = []
    s = _flow_fraction(poly, settings)
    if settings.solver == "simpleFoam":
        fields_list = ("U", "p")
        rho = settings.mean_density
        nu = settings.dynamic_viscosity / rho
        dp = (settings.inlet_pressure - settings.outlet_pressure) / rho
        zero_gradient = ["type zeroGradient;"]
        _write_field(
            case, "U", "volVectorField", "[0 1 -1 0 0 0 0]", "uniform (0 0 0)",
            _boundary_conditions(poly, {
                "inlet": zero_gradient, "outlet": zero_gradient,
                "opening": ["type pressureInletOutletVelocity;", "value uniform (0 0 0);"],
                "wall": ["type noSlip;"],
            }),
            fmt,
        )
        _write_field(
            case, "p", "volScalarField", "[0 2 -2 0 0 0 0]", dp * (1.0 - s),
            _boundary_conditions(poly, {
                "inlet": ["type fixedValue;", f"value uniform {dp!r};"],
                "outlet": ["type fixedValue;", "value uniform 0;"],
                "opening": ["type fixedValue;", "value uniform 0;"],
                "wall": zero_gradient,
            }),
            fmt,
        )
        _dictionary(case, "constant", "transportProperties",
                    f"transportModel  Newtonian;\n\nnu              {nu!r};\n")
        _dictionary(case, "constant", "physicalProperties",
                    f"viscosityModel  constant;\n\nnu              {nu!r};\n")
        application, org_solver = "simpleFoam", "incompressibleFluid"
        schemes = (
            "ddtSchemes\n{\n    default         steadyState;\n}\n\n"
            "gradSchemes\n{\n    default         Gauss linear;\n"
            "    grad(U)         cellLimited Gauss linear 1;\n}\n\n"
            "divSchemes\n{\n    default         Gauss linear;\n"
            "    div(phi,U)      bounded Gauss linearUpwind grad(U);\n"
            "    div((nuEff*dev2(T(grad(U))))) Gauss linear;\n}\n\n"
        )
        solvers = (
            _pressure_solver(0.01)
            + "    \"(U|U.*)\"\n    {\n        solver          smoothSolver;\n"
            "        smoother        symGaussSeidel;\n        tolerance       1e-12;\n"
            "        relTol          0.05;\n    }\n"
        )
        residuals = f"p {settings.residual_tolerance!r}; U {settings.residual_tolerance!r};"
        relax = "    fields\n    {\n        p               0.3;\n    }\n" \
            "    equations\n    {\n        U               0.7;\n        \".*\"            0.7;\n    }\n"
        pressure_limits = ""
    elif settings.solver == "rhoSimpleFoam":
        fields_list = ("U", "p", "h")
        p_in, p_out, temperature = settings.inlet_pressure, settings.outlet_pressure, settings.temperature
        gamma = _gamma(settings)
        p0 = np.sqrt(p_out ** 2 + (p_in ** 2 - p_out ** 2) * (1.0 - s))
        velocity_opening = ["type pressureInletOutletVelocity;", "value uniform (0 0 0);"]
        _write_field(
            case, "U", "volVectorField", "[0 1 -1 0 0 0 0]", "uniform (0 0 0)",
            _boundary_conditions(poly, {"opening": velocity_opening, "wall": ["type noSlip;"]}),
            fmt,
        )
        _write_field(
            case, "p", "volScalarField", "[1 -1 -2 0 0 0 0]", p0,
            _boundary_conditions(poly, {
                "inlet": ["type fixedValue;", f"value uniform {p_in!r};"],
                "outlet": ["type fixedValue;", f"value uniform {p_out!r};"],
                "opening": ["type fixedValue;", f"value uniform {p_out!r};"],
                "wall": ["type zeroGradient;"],
            }),
            fmt,
        )
        _write_field(
            case, "T", "volScalarField", "[0 0 0 1 0 0 0]", f"uniform {temperature!r}",
            _boundary_conditions(poly, {
                "inlet": ["type totalTemperature;", f"T0 uniform {temperature!r};",
                          f"gamma {gamma!r};", f"value uniform {temperature!r};"],
                "opening": ["type inletOutlet;", f"inletValue uniform {temperature!r};",
                            f"value uniform {temperature!r};"],
                "wall": ["type fixedValue;", f"value uniform {temperature!r};"],
            }),
            fmt,
        )
        molar_mass = 8314.46261815324 / settings.gas_constant
        prandtl = settings.dynamic_viscosity * settings.heat_capacity / settings.thermal_conductivity
        thermo = (
            "thermoType\n{\n    type            hePsiThermo;\n    mixture         pureMixture;\n"
            "    transport       const;\n    thermo          hConst;\n"
            "    equationOfState perfectGas;\n    specie          specie;\n"
            "    energy          sensibleEnthalpy;\n}\n\nmixture\n{\n"
            f"    specie\n    {{\n        molWeight       {molar_mass!r};\n    }}\n"
            "    thermodynamics\n    {\n"
            f"        Cp              {settings.heat_capacity!r};\n        Hf              0;\n"
            "        hf              0;\n    }\n"
            f"    transport\n    {{\n        mu              {settings.dynamic_viscosity!r};\n"
            f"        Pr              {prandtl!r};\n    }}\n}}\n"
        )
        _dictionary(case, "constant", "thermophysicalProperties", thermo)
        _dictionary(case, "constant", "physicalProperties", thermo)
        application, org_solver = "rhoSimpleFoam", "fluid"
        schemes = (
            "ddtSchemes\n{\n    default         steadyState;\n}\n\n"
            "gradSchemes\n{\n    default         Gauss linear;\n"
            "    grad(U)         cellLimited Gauss linear 1;\n"
            "    grad(h)         cellLimited Gauss linear 1;\n}\n\n"
            "divSchemes\n{\n    default         Gauss linear;\n"
            "    div(phi,U)      bounded Gauss linearUpwind grad(U);\n"
            "    div(phi,h)      bounded Gauss linearUpwind grad(h);\n"
            "    div(phi,K)      bounded Gauss linear;\n"
            "    div(phid,p)     Gauss limitedLinear 1;\n"
            "    div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear;\n}\n\n"
        )
        solvers = (
            _pressure_solver(0.05)
            + "    \"(U|h|e|U.*|h.*|e.*)\"\n    {\n        solver          PBiCGStab;\n"
            "        preconditioner  DILU;\n        tolerance       1e-12;\n"
            "        relTol          0.05;\n    }\n"
        )
        tol = settings.residual_tolerance
        residuals = f"p {tol!r}; U {tol!r}; h {tol!r};"
        relax = "    fields\n    {\n        p               0.3;\n        rho             1;\n    }\n" \
            "    equations\n    {\n        U               0.7;\n        h               0.7;\n" \
            "        \".*\"            0.7;\n    }\n"
        # OpenFOAM.org reads pressure limits from fvConstraints only.
        pressure_limits = "" if org else "    pMinFactor      0.5;\n    pMaxFactor      1.5;\n"
        if org:
            _dictionary(
                case, "system", "fvConstraints",
                "limitp\n{\n    type            limitPressure;\n"
                "    minFactor       0.5;\n    maxFactor       1.5;\n}\n",
            )
    else:
        fields_list = ()
        application, org_solver = "checkMesh", None
        schemes = ""
        solvers = ""
        residuals = ""
        relax = ""
        pressure_limits = ""

    turbulence = "simulationType  laminar;\n"
    if settings.solver != "none":
        _dictionary(case, "constant", "turbulenceProperties", turbulence)
        _dictionary(case, "constant", "momentumTransport", turbulence)
    end_time = settings.iterations
    control = f"application     {'foamRun' if org and org_solver else application};\n"
    if org and org_solver:
        control += f"solver          {org_solver};\n"
    control += (
        "\nstartFrom       latestTime;\nstartTime       0;\nstopAt          endTime;\n"
        f"endTime         {end_time};\ndeltaT          1;\nwriteControl    timeStep;\n"
        f"writeInterval   {settings.write_interval};\npurgeWrite      2;\n"
        f"writeFormat     {fmt};\nwritePrecision  12;\nwriteCompression off;\n"
        "timeFormat      general;\ntimePrecision   8;\nrunTimeModifiable true;\n\n"
    )
    if fields_list:
        control += _functions(poly, settings, fields_list)
    _dictionary(case, "system", "controlDict", control)
    _dictionary(
        case,
        "system",
        "fvSchemes",
        (schemes or "ddtSchemes\n{\n    default         steadyState;\n}\n\n"
         "gradSchemes\n{\n    default         Gauss linear;\n}\n\n"
         "divSchemes\n{\n    default         none;\n}\n\n")
        # The pressure-equation coefficient (r)AU is interpolated harmonically: where
        # thin crack layers meet much larger chamber cells, linear weights let the
        # large cell dominate the face and SIMPLE diverges.  rhoSimpleFoam and the
        # .org fluid solver interpolate rho*rAU explicitly, hence the named entries.
        + "laplacianSchemes\n{\n    default         Gauss harmonic limited corrected 0.5;\n}\n\n"
        "interpolationSchemes\n{\n    default         linear;\n"
        "    interpolate((rho*(1|A(U)))) harmonic;\n"
        "    interpolate((rho*rAU)) harmonic;\n}\n\n"
        "snGradSchemes\n{\n    default         limited corrected 0.5;\n}\n\n"
        "wallDist\n{\n    method          meshWave;\n}\n",
    )
    if fields_list:
        # Non-orthogonal correctors only where the mesh needs them.
        worst = float(poly.report.get("quality", {}).get("max_non_orthogonality_deg", 90.0))
        n_nonorth = 0 if worst < 5.0 else 1 if worst < 40.0 else 2
        # Standard SIMPLE: the SIMPLEC coefficient 1/(1/rAU - H1) can approach zero,
        # which harmonic interpolation turns into a blow-up.
        algorithm = (
            f"    nNonOrthogonalCorrectors {n_nonorth};\n    consistent      no;\n"
            + ("    transonic       no;\n" if settings.solver == "rhoSimpleFoam" else "")
        )
        solution = (
            f"solvers\n{{\n{solvers}}}\n\n"
            f"SIMPLE\n{{\n{algorithm}{pressure_limits}"
            f"    residualControl\n    {{\n        {residuals}\n    }}\n}}\n\n"
            "// OpenFOAM.org foamRun reads PIMPLE; OpenFOAM.com reads SIMPLE.\n"
            f"PIMPLE\n{{\n    nOuterCorrectors 1;\n{algorithm}{pressure_limits}"
            f"    residualControl\n    {{\n        {residuals}\n    }}\n}}\n\n"
            f"relaxationFactors\n{{\n{relax}}}\n"
        )
    else:
        solution = ""
    _dictionary(case, "system", "fvSolution", solution)
    if settings.processors > 1:
        _dictionary(
            case,
            "system",
            "decomposeParDict",
            f"numberOfSubdomains {settings.processors};\n\nmethod          scotch;\n",
        )
    written += ["0", "constant", "system"] if fields_list else ["constant", "system"]
    _write_allrun(case, settings, application, org_solver)
    (case / f"{case.name}.foam").touch()
    return written


def _write_allrun(
    case: Path, settings: OpenFOAMSettings, application: str, org_solver: str | None
) -> None:
    org = settings.openfoam_version == "org"
    run = "foamRun" if org and org_solver else application
    lines = [
        "#!/bin/sh",
        "# Generated by DEM Crack Surface Mesher. Run inside an OpenFOAM environment",
        f"# ({'OpenFOAM.org 11 or later' if org else 'OpenFOAM.com v2xxx'}); on Windows use WSL",
        "# or Docker: wsl ./Allrun",
        'cd "${0%/*}" || exit 1',
        "",
        "checkMesh > log.checkMesh 2>&1",
        'grep -E "cells:|Mesh OK|Failed|\\*\\*\\*" log.checkMesh',
    ]
    if settings.solver != "none":
        if settings.processors > 1:
            lines += [
                "decomposePar -force > log.decomposePar 2>&1 || exit 1",
                f"mpirun -np {settings.processors} {run} -parallel > log.{run} 2>&1 || exit 1",
                "reconstructPar -latestTime > log.reconstructPar 2>&1 || exit 1",
            ]
        else:
            lines += [f"{run} > log.{run} 2>&1 || exit 1"]
        lines += [f'echo "Finished: see log.{run} and postProcessing/"']
    path = case / "Allrun"
    _write_text(path, "\n".join(lines) + "\n")
    try:
        path.chmod(0o755)
    except OSError:
        pass
    _write_text(
        case / "Allclean",
        "#!/bin/sh\n# Remove solver results; keeps the mesh, 0/ and the dictionaries.\n"
        'cd "${0%/*}" || exit 1\n'
        "rm -rf processor* postProcessing log.* [1-9]* 0.[0-9]* constant/polyMesh/sets\n",
    )
    try:
        (case / "Allclean").chmod(0o755)
    except OSError:
        pass


# --------------------------------------------------------------------------- high level
@dataclass(frozen=True)
class OpenFOAMExportResult:
    case_directory: Path
    report: dict[str, object]
    elapsed_seconds: float
    archived_previous: Path | None = None


def _prepare_case_directory(case: Path, settings: OpenFOAMSettings, log: LogFunction) -> Path | None:
    """Archive a previous export; never touch a non-empty directory the tool did not write."""

    if not case.exists():
        return None
    if not case.is_dir():
        raise FileExistsError(f"{case} exists and is not a directory.")
    if not any(case.iterdir()):
        return None
    if not (case / EXPORT_MARKER).is_file():
        raise FileExistsError(
            f"{case} is not empty and was not written by this exporter; choose another "
            "case_directory."
        )
    if not settings.archive_existing:
        raise FileExistsError(f"{case} holds a previous export; enable archive_existing.")
    archive_root = case.parent / "_previous_openfoam_cases"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = archive_root / f"{case.name}-{stamp}"
    suffix = 1
    while target.exists():
        target = archive_root / f"{case.name}-{stamp}-{suffix}"
        suffix += 1
    archive_root.mkdir(parents=True, exist_ok=True)
    case.replace(target)
    log(f"[OpenFOAM] Archived the previous case in {target}.\n")
    return target


def export_openfoam(
    source: SourceMesh,
    case_directory: Path,
    settings: OpenFOAMSettings | None = None,
    *,
    log: LogFunction | None = None,
) -> OpenFOAMExportResult:
    """Build, check and write an OpenFOAM case from a source mesh."""

    settings = (settings or OpenFOAMSettings()).validated()
    log = log or (lambda _message: None)
    started = time.perf_counter()
    case = Path(case_directory)
    poly = build_polymesh(source, settings, log=log)
    archived = _prepare_case_directory(case, settings, log)
    case.mkdir(parents=True, exist_ok=True)
    write_polymesh(case, poly, settings.write_format)
    write_case(case, poly, settings)
    report = dict(poly.report)
    report.update(
        {
            "tool": "DEM Crack Surface Mesher openfoam_export",
            "created": datetime.now().isoformat(timespec="seconds"),
            "case_directory": str(case),
            "settings": asdict(settings),
            "solver_application": (
                ("foamRun" if settings.openfoam_version == "org" else settings.solver)
                if settings.solver != "none"
                else None
            ),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    )
    if settings.solver == "simpleFoam":
        rho = settings.mean_density
        report["incompressible_model"] = {
            "density": rho,
            "kinematic_viscosity": settings.dynamic_viscosity / rho,
            "kinematic_pressure_difference": (settings.inlet_pressure - settings.outlet_pressure)
            / rho,
            "note": "simpleFoam fluxes are volumetric (m3/s); multiply by density for kg/s.",
        }
    _write_text(case / EXPORT_MARKER, json.dumps(report, indent=2) + "\n")
    log(
        f"[OpenFOAM] Case written to {case} ({report['elapsed_seconds']:.2f} s); "
        f"run ./Allrun inside OpenFOAM.\n"
    )
    return OpenFOAMExportResult(case, report, report["elapsed_seconds"], archived)


def export_workdir(
    workdir: Path,
    settings: OpenFOAMSettings | None = None,
    *,
    python_mesh: object | None = None,
    log: LogFunction | None = None,
) -> OpenFOAMExportResult:
    """Export the mesh of a completed run; the case goes to ``workdir/case_directory``."""

    settings = (settings or OpenFOAMSettings()).validated()
    workdir = Path(workdir)
    source = (
        mesh_from_python(python_mesh)
        if python_mesh is not None
        else mesh_from_workdir(workdir, log=log)
    )
    case = Path(settings.case_directory)
    if not case.is_absolute():
        case = workdir / case
    return export_openfoam(source, case, settings, log=log)


def export_summary(result: OpenFOAMExportResult) -> dict[str, object]:
    """Compact JSON-serializable summary for run reports."""

    report = result.report
    return {
        "case_directory": str(result.case_directory),
        "solver": report["settings"]["solver"],
        "openfoam_version": report["settings"]["openfoam_version"],
        "n_cells": report["n_cells"],
        "cell_counts": report["cell_counts"],
        "patches": {p["name"]: p["nFaces"] for p in report["patches"]},
        "cell_zones": report["cell_zones"],
        "face_zones": report["face_zones"],
        "quality": {
            key: report["quality"][key]
            for key in (
                "total_volume",
                "face_pyramid_failures",
                "max_non_orthogonality_deg",
                "max_skewness",
                "max_aspect_ratio",
            )
        },
        "warnings": report["warnings"],
        "archived_previous": str(result.archived_previous) if result.archived_previous else None,
        "success": True,
    }


# --------------------------------------------------------------------------- command line
def build_parser() -> argparse.ArgumentParser:
    defaults = OpenFOAMSettings()
    parser = argparse.ArgumentParser(
        description=(
            "Export a DEM Crack Surface Mesher mesh (a run directory holding castem_mesh_v.bdf "
            "and the castem_mesh_surf_*.bdf boundaries, or one combined BDF) as an OpenFOAM case."
        )
    )
    parser.add_argument("source", type=Path, help="run directory or combined .bdf file")
    parser.add_argument(
        "-o", "--case", type=Path,
        help="case directory (default: <run directory>/openfoam_case or <bdf stem>_openfoam)",
    )
    parser.add_argument("--solver", choices=SUPPORTED_SOLVERS, default=defaults.solver)
    parser.add_argument(
        "--openfoam-version", choices=SUPPORTED_VERSIONS, default=defaults.openfoam_version,
        help="com: OpenFOAM.com v2xxx (simpleFoam/rhoSimpleFoam); org: OpenFOAM.org 11+ (foamRun)",
    )
    parser.add_argument("--format", choices=SUPPORTED_FORMATS, default=defaults.write_format)
    parser.add_argument("--cell-split", choices=SUPPORTED_SPLITS, default=defaults.cell_split)
    parser.add_argument(
        "--pyramid-margin", type=float, default=defaults.pyramid_margin,
        help="auto split: smallest face pyramid kept, as a fraction of a box's (default 0.25)",
    )
    parser.add_argument("--merge-tolerance", type=float, default=defaults.merge_tolerance)
    parser.add_argument(
        "--scale", type=float, default=defaults.length_scale,
        help="multiply mesh coordinates to obtain metres (e.g. 1e-3 for a mesh in mm)",
    )
    parser.add_argument(
        "--flow-direction", choices=SUPPORTED_FLOW_DIRECTIONS, default=defaults.flow_direction
    )
    parser.add_argument("--side-walls", choices=SUPPORTED_SIDE_TYPES, default=defaults.side_walls)
    parser.add_argument(
        "--patches", default="",
        help="custom patch table 'name=type:surface+surface; ...' (surfaces: min, max, xmin, "
        "xmax, ymin, ymax, trou_1, inlet_outer, ...)",
    )
    parser.add_argument(
        "--pshell", default="",
        help="combined BDF only: PSHELL ID to surface map, e.g. '1=min,2=max,3=ymin,4=ymax'",
    )
    parser.add_argument("--inlet-pressure", type=float, default=defaults.inlet_pressure)
    parser.add_argument("--outlet-pressure", type=float, default=defaults.outlet_pressure)
    parser.add_argument("--temperature", type=float, default=defaults.temperature)
    parser.add_argument("--viscosity", type=float, default=defaults.dynamic_viscosity)
    parser.add_argument("--density", type=float, default=None)
    parser.add_argument("--iterations", type=int, default=defaults.iterations)
    parser.add_argument("--write-interval", type=int, default=defaults.write_interval)
    parser.add_argument("--processors", type=int, default=defaults.processors)
    parser.add_argument(
        "--no-archive", action="store_true",
        help="fail instead of archiving a previous export in the case directory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = lambda message: print(message, end="", flush=True)  # noqa: E731
    try:
        source_path = args.source
        if source_path.is_dir():
            source = mesh_from_workdir(source_path, log=log)
            case = args.case or source_path / OpenFOAMSettings.case_directory
        elif source_path.is_file():
            source = mesh_from_combined_bdf(
                source_path,
                pshell_surfaces=parse_pshell_map(args.pshell) if args.pshell else None,
                log=log,
            )
            case = args.case or source_path.with_name(f"{source_path.stem}_openfoam")
        else:
            raise FileNotFoundError(f"{source_path} does not exist.")
        settings = OpenFOAMSettings(
            case_directory=str(case),
            solver=args.solver,
            openfoam_version=args.openfoam_version,
            write_format=args.format,
            cell_split=args.cell_split,
            pyramid_margin=args.pyramid_margin,
            merge_tolerance=args.merge_tolerance,
            length_scale=args.scale,
            flow_direction=args.flow_direction,
            side_walls=args.side_walls,
            patches=args.patches,
            inlet_pressure=args.inlet_pressure,
            outlet_pressure=args.outlet_pressure,
            temperature=args.temperature,
            dynamic_viscosity=args.viscosity,
            density=args.density,
            iterations=args.iterations,
            write_interval=args.write_interval,
            processors=args.processors,
            archive_existing=not args.no_archive,
        ).validated()
        result = export_openfoam(source, case, settings, log=log)
        print(json.dumps(export_summary(result), indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 - command-line error report
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


__all__ = [
    "OpenFOAMSettings",
    "OpenFOAMExportResult",
    "PatchRule",
    "PolyMesh",
    "SourceMesh",
    "build_polymesh",
    "default_patch_rules",
    "export_openfoam",
    "export_summary",
    "export_workdir",
    "mesh_from_combined_bdf",
    "mesh_from_python",
    "mesh_from_workdir",
    "mesh_quality",
    "parse_patch_rules",
    "parse_pshell_map",
    "read_bdf",
    "settings_from_mapping",
    "settings_to_mapping",
    "write_case",
    "write_polymesh",
]


if __name__ == "__main__":
    raise SystemExit(main())
