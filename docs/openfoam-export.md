# OpenFOAM case export

## Purpose

The exporter turns any mesh the tool produces into a ready-to-run OpenFOAM
case: a `constant/polyMesh` with named patches and zones, initial fields,
physical properties, numerics, flow-rate monitors and an `Allrun` script. It
uses only NumPy and SciPy, which the tool already requires: OpenFOAM is needed
to run the case, not to write it.

It accepts three sources:

| Source | How it is read |
|---|---|
| `python_only` mesh in memory | the HEXA8 arrays and named boundaries directly, no BDF round trip |
| a run directory (`python_only`, `python` or `reference`) | `castem_mesh_v.bdf`, every `castem_mesh_surf_*.bdf` and the chamber volumes |
| one merged `combined_*.bdf` | the volume cells and the `PSHELL`-tagged boundaries written by the merger |

Both OpenFOAM families are supported:

| `openfoam_version` | Distribution | Solver call |
|---|---|---|
| `com` | OpenFOAM.com v2xxx (ESI) | `simpleFoam` / `rhoSimpleFoam` |
| `org` | OpenFOAM.org 11 or later (Foundation) | `foamRun` with `incompressibleFluid` / `fluid` |

The case carries the dictionary names of both families where they differ
(`transportProperties` and `physicalProperties`, `turbulenceProperties` and
`momentumTransport`, `SIMPLE` and `PIMPLE`), so the same files run on either
after the `controlDict` application line, which is set for the chosen family.

## Use

### Scientific Workbench

Tick **Export an OpenFOAM case** on the Mesh tab, then choose the solver, the
distribution, the cell split, the case folder, the absolute inlet and outlet
pressures, the temperature, the number of iterations and the length scale. The
case is written after a successful mesh run, for every backend, and its path is
reported in the run log and in the completion message. An export error is
reported without discarding the mesh.

### Headless INI

```ini
[mesh]
export_openfoam = true

[openfoam]
solver = simpleFoam
openfoam_version = com
inlet_pressure = 111325
outlet_pressure = 101325
```

Every field of the table below is accepted in `[openfoam]`; unknown keys are
rejected. The case directory is resolved relative to the run directory. The
headless report (`headless-run-report.json`) stores the export summary under
`mesh.openfoam`, and the run fails if the export fails. A complete example is
[`examples/openfoam/run.ini`](../examples/openfoam/run.ini).

### Command line, for an existing run

```bash
python3 openfoam_export.py path/to/run_directory --solver rhoSimpleFoam --openfoam-version org
python3 openfoam_export.py path/to/combined_mesh.bdf -o my_case --format binary
python3 openfoam_export.py --help
```

On Windows, call `python.exe .\openfoam_export.py` with the same arguments.
Then, inside an OpenFOAM environment (Linux, or WSL or Docker on Windows):

```bash
cd path/to/run_directory/openfoam_case && ./Allrun
```

On Windows, run `wsl sh ./Allrun` from the case folder. `Allrun` runs
`checkMesh`, then the solver (with `decomposePar`, `mpirun` and
`reconstructPar` when `processors > 1`). `Allclean` removes results and keeps
the mesh and the dictionaries. The `<case>.foam` file opens the case in
ParaView.

## Options

| Option | Default | Meaning |
|---|---|---|
| `case_directory` | `openfoam_case` | case folder; relative paths are taken from the run directory |
| `solver` | `simpleFoam` | `simpleFoam` (incompressible), `rhoSimpleFoam` (compressible ideal gas) or `none` (mesh only) |
| `openfoam_version` | `com` | `com` or `org`, see above |
| `write_format` | `ascii` | `ascii` or `binary` polyMesh and fields |
| `cell_split` | `auto` | `auto`, `prism` or `none`, see *Cell conversion* |
| `pyramid_margin` | `0.25` | `auto` split threshold, see *Cell conversion* |
| `merge_tolerance` | `1e-9` | node merge distance, relative to the mesh diagonal |
| `length_scale` | `1` | factor that converts mesh coordinates to metres (`1e-3` for millimetres) |
| `flow_direction` | `+y` | `+y`, `-y`, `+x` or `-x`; the chambers of the tool sit on the Y ends |
| `side_walls` | `wall` | type of the lateral crack faces: `wall`, `symmetry` or `patch` |
| `patches` | (empty) | custom patch table, see *Patches* |
| `inlet_pressure`, `outlet_pressure` | `111325`, `101325` | absolute pressures (Pa) |
| `temperature` | `298.15` | gas and wall temperature (K) |
| `dynamic_viscosity` | `1.831e-5` | Pa s (air at 25 °C) |
| `gas_constant`, `heat_capacity`, `thermal_conductivity` | `287.05`, `1004.4`, `0.0261` | J/(kg K), J/(kg K), W/(m K) |
| `density` | ideal gas at the mean pressure | density of the incompressible model (kg/m³) |
| `iterations`, `write_interval` | `2000`, `500` | SIMPLE iterations and output interval |
| `processors` | `1` | MPI ranks; `> 1` writes `decomposeParDict` (scotch) |
| `residual_tolerance` | `1e-6` | `residualControl` on every solved field |
| `archive_existing` | `true` | move a previous export of the tool to `_previous_openfoam_cases/` |

The exporter never deletes a folder. A previous case it wrote (recognised by its
`openfoam_export.json`) is archived with a time stamp; a non-empty folder it did
not write stops the export with an error and is left untouched.

## Patches

The default table maps the tool's boundary files to OpenFOAM patches:

| Patch | Type | Boundary files |
|---|---|---|
| `inlet` | patch | `surf_ymin`, or the remote face `surf_inlet_outer` when chambers exist |
| `outlet` | patch | `surf_ymax`, or `surf_outlet_outer` |
| `lowerWall`, `upperWall` | wall | `surf_min`, `surf_max` |
| `sideWalls` | `side_walls` | `surf_xmin`, `surf_xmax` |
| `hole1`, `hole2`, ... | wall | `surf_trou_1`, `surf_trou_2`, ... |
| `inletChamberWalls`, `outletChamberWalls` | wall | the other faces of each chamber |

For `flow_direction = ±x` the inlet and outlet move to the X ends and the Y
ends become side walls. Boundary faces not claimed by any rule go to
`otherWalls`, so no face is left without a patch.

A custom table replaces the default one:

```ini
patches = inlet=patch:ymin; outlet=patch:ymax; walls=wall:min+max+xmin+xmax
```

Each entry is `name=type:surface+surface`, with a surface named by its file
(`min`, `max`, `xmin`, `trou_1`, `inlet_outer`, ...). When chambers are present
the case also has the cell zones `crack`, `inletChamber` and `outletChamber`,
and the oriented face zones `crackInlet` and `crackOutlet` on the two crack
mouths. A combined BDF holds no volume groups, so its cell zones are rebuilt
from the parts into which the crack mouths divide the mesh.

## Cell conversion

The crack volume is a stack of thin HEXA8 cells whose top and bottom follow
rough surfaces. A warped thin hexahedron can fail OpenFOAM's face-pyramid test:
the cell centre falls outside one of its faces, `checkMesh` reports it and the
solver may diverge. The exporter therefore tests every hexahedron with
OpenFOAM's own centre and face decomposition and measures its smallest face
pyramid, normalised so that a box scores 1.

- `auto` (default) splits into two prisms only the vertical columns that hold a
  cell scoring below `pyramid_margin`. Every cell of such a column is split
  along the same diagonal, so the column stays conformal with its neighbours.
  On the BPM crack of the examples this splits about 4 to 6 % of the cells.
- `prism` splits every column. All pyramids pass, but splitting an elongated
  footprint creates faces close to 90° non-orthogonal, so `auto` is preferred.
- `none` keeps every hexahedron.

Coincident nodes (Cast3M writes separate nodes on a closed contact) are merged,
faces that collapse on a closed crack front become triangles, and cells whose
volume vanishes are dropped and reported.

## Generated case

| Field | `simpleFoam` | `rhoSimpleFoam` |
|---|---|---|
| `p` | kinematic, fixed at inlet and outlet | absolute, fixed at inlet and outlet |
| `U` | zero gradient at inlet and outlet, no slip on walls | `pressureInletOutletVelocity` at inlet and outlet |
| `T` | | `totalTemperature` at the inlet, `inletOutlet` at the outlet, fixed on walls |

The flow is laminar. The initial pressure is uniform in each chamber and varies
linearly along the crack (in p² for the compressible case). The numerics are second order
(`linearUpwind` for convection) with SIMPLE (pressure relaxed by 0.3, velocity
and enthalpy by 0.7). Non-orthogonal correctors are added only when the mesh
needs them. The pressure equation interpolates its coefficient (`rAU`, or
`rho*rAU`) harmonically: where thin crack layers meet chamber cells tens of
times thicker, linear interpolation lets the large cell dominate the face
coefficient and SIMPLE diverges. SIMPLEC (`consistent yes`) is not used because
its coefficient can approach zero, which the harmonic mean amplifies. For
OpenFOAM.org the compressible pressure limits are written to
`system/fvConstraints`.

`postProcessing/` receives the residuals and the flow rate through `inlet`,
`outlet` and, with chambers, the face zones `crackInlet` and `crackOutlet`.
The rate is the sum of `phi`: m³/s for `simpleFoam`, kg/s for
`rhoSimpleFoam`.

## Quality report

Every export writes `openfoam_export.json` in the case: the settings, the
source, the cell counts by type, the patches and zones, and OpenFOAM-style
quality figures (volumes, closedness, face pyramids, non-orthogonality,
skewness, aspect ratio, size jump across faces). Warnings are also logged:

- *face pyramids*: some cells still fail; use `cell_split = prism`;
- *size jumps above 20×*: usually chamber cells beside thin crack layers. The
  case stays stable, but the coarse chamber cells limit the accuracy near the
  crack mouths; more chamber height elements (or a smaller ratio) help;
- *zero-volume cells dropped* on a closed contact.

`checkMesh` may report a high aspect ratio where the crack nearly closes, for
example around holes. This is the geometry of the crack, not an export defect.

## Verification

The export is covered by `tests/test_openfoam_export.py`: constant-opening
volume and patch counts, unit scaling, warped columns split only where pyramids
fail, chamber zones and oriented crack face zones, run-directory export equal to
the in-memory export, ASCII and binary round trips, the dictionaries of both
distributions, archiving, a closed crack front with a degenerate cell, the
bundled Cast3M BDFs, the headless runner, and `checkMesh` when an OpenFOAM
environment is sourced.

Exported cases were also run on OpenFOAM v2412 (`com`) and OpenFOAM 12
(`org`): laminar air at 25 °C, 111325 Pa at the inlet and 101325 Pa at the
outlet. All ran without error, and both distributions gave the same rates.

| Case | Cells | Solver | Result |
|---|---:|---|---|
| Parallel plates, 0.1 mm apart, 50 mm wide, 40 mm long, 12 layers | 1,440 | `simpleFoam` | Q = 5.7680e-5 m³/s; discrete Poiseuille value 5.7681e-5 (cubic law × (1 + 2/n²)) |
| same | 1,440 | `rhoSimpleFoam` | ṁ = 7.1494e-5 kg/s, 0.23 % below the isothermal lubrication value 7.1660e-5 (same discrete factor), which ignores gas acceleration |
| Rough fractal crack, binary format | 7,680 | both | converged in 1,166 (`simpleFoam`) and 949 (`rhoSimpleFoam`) iterations |
| BPM crack of the examples, `auto` split | 20,384 | both | converged in 134 (`simpleFoam`) and 176 (`rhoSimpleFoam`) iterations |
| BPM crack with two holes and 0.2 m chambers, size jump 2,583× | 26,728 | both | `simpleFoam` converged in 1,116 iterations; `rhoSimpleFoam` rate steady to 5e-5 after 3,000 |
| [`examples/openfoam`](../examples/openfoam/README.md): holes and 0.04 m chambers, size jump 41× | 49,464 | both | `simpleFoam` converged in 100 iterations, Q = 1.8556e-5 m³/s; `rhoSimpleFoam` (`com` case written from the combined BDF) ṁ = 2.3053e-5 kg/s, steady to 1e-4 after 3,000 |

The residual control may not stop a run whose velocity has a component close
to zero everywhere (the plates above): that component's normalised residual
stays at round-off noise. The flow-rate files in `postProcessing/` show when
the rate has settled.

## Limitations

- Laminar, steady, single-phase flow driven by a pressure difference. The case
  is a starting point: turbulence, heat transfer or other boundary conditions
  are set in OpenFOAM.
- Mesh coordinates are read as given and multiplied by `length_scale`; check the
  units of the input surfaces.
- On Windows the case is written natively; it is run in WSL, Docker or another
  OpenFOAM installation.
