# Provisional verification — scientific bulk-hole path

Verification date: 2026-07-13. Host: Windows, Python 3.13.5, Cast3M annual version 2025 (launcher version `25`). These measurements apply to the documented 50 × 50 CSV quartet and two holes `(-0.20, 0.20, 0.07)` and `(0.20, -0.20, 0.07)`.

This is implementation evidence, not scientific validation.

## Preservation and static checks

- `python -B scripts\verify_baseline.py`: all 6 immutable files matched their committed SHA-256 values.
- `python -B -m compileall -q .`: passed.
- `python -B -m pytest -q -p no:cacheprovider tests`: 39 tests passed.
- `python -B castem_pipeline_gui_scientific.py --headless examples\scientific-run.ini --validate-only`: passed and reported 64 angular points for each of the two refinement-2 holes without starting a GUI or Cast3M.
- The derived optimized DGIBI contains three `LIRE 'NAS'` mesh imports and no generated per-node `POIN` statements.
- Its hole-fill replacement contains no `REGL (-1*num_el_fill)`, `INT_COMP surf_zmin_comp`, or `DISPLACE surf_zmin` call.

## Conformal interface verification

The reported mismatch was reproduced from `work1111`: the Python fill used 32 angular edges per hole, while `nelem_x = nelem_y = 2` split the matching Cast3M square contour into 64 edges. The former implementation projected only the 32 coarse contour corners and did not apply the background-edge subdivision.

The corrected implementation subdivides every contour segment by the same structured-grid refinement before projecting it onto the circle. For the same two-hole case:

| Topology check, per hole | Previous file | Corrected refinement 2 |
|---|---:|---:|
| Hole-wall edges | 32 | 64 |
| Matching square-contour edges | 64 | 64 |
| Boundary edges near the hole | 128 | 64 |
| Unmatched interface edges | 96 | 0 |

In the previous final surface, the 96 extra boundary edges per hole exposed the non-conformal square/fill interface. In the corrected final surface, all 64 boundary edges near each hole are the physical hole wall; no square/fill interface remains in the boundary-edge set.

With the user's exact `nelem_x = nelem_y = 2` and `num_el_fill = 20` settings, each generated fill surface has 64 angular points per hole, 2,688 nodes, and 2,560 `CQUAD4` cells across the two holes.

## Real Cast3M integration

The corrected run,

```powershell
python -B scripts\run_python_holes_example.py --clean --refinement 2 --output _runtime\conformal-hole-r2
```

completed with process return code `0`, Cast3M error level `0`, and a generated volume BDF.

| Quantity | Value |
|---|---:|
| Detected contour nodes per hole | 64 |
| Rings per hole | 6 |
| Radial cells per hole | 5 |
| Nodes per fill surface | 768 |
| `CQUAD4` cells per fill surface | 640 |
| Python preparation time | 0.026474 s |
| Cast3M time | 13.488335 s |
| Final surface quads | 9,740 |
| Final volume hexes | 19,480 |

The complete committed INI was also executed through the no-interface launcher:

```powershell
python -B castem_pipeline_gui_scientific.py --headless examples\scientific-run.ini
```

It returned `0`, reported Cast3M error level `0`, detected `[64, 64]` angular points, found no missing expected outputs, and created the named combined BDF. The headless process measured 15.231634 s on this run; timing variation relative to the controlled benchmark is expected.

## Generalized shape verification

The runnable gallery contains a circle, rotated rectangle, rotated equilateral triangle, and regular hexagon. The command

```powershell
python -B castem_pipeline_gui_scientific.py --headless examples\shaped-holes\all-shapes.ini
```

returned `0`, stopped at Cast3M error level `0`, created all four requested hole-surface BDFs, found no missing outputs, and produced a combined BDF. The headless process measured 17.823067 s. The real volume BDF contains 40,920 points and 19,936 `HEXA8` cells; the maximum surface contains 9,968 `CQUAD4` cells.

Final-surface topology was checked with `python -B scripts\verify_shape_interfaces.py`:

| Shape | Square-interface edges | Final hole-wall edges | Residual square/fill boundary edges |
|---|---:|---:|---:|
| Circle | 44 | 44 | 0 |
| Rectangle | 56 | 56 | 0 |
| Equilateral triangle | 56 | 56 | 0 |
| Regular hexagon | 56 | 56 | 0 |

Thus every generated fill is conformal at the interface in this real mixed-shape run. This topology check does not replace solver-specific CFD mesh-quality validation.

All 19,936 volume elements also had positive, non-zero center Jacobians in this run; no mixed or zero center orientation was detected.

## Generated surface verification

The self-affine Hurst example and constant-plane example were executed through the same headless hole/Cast3M path:

```powershell
python -B castem_pipeline_gui_scientific.py --headless examples\surfaces\fractal-hurst.ini
python -B castem_pipeline_gui_scientific.py --headless examples\surfaces\constant-planes.ini
```

Both returned process code `0`, stopped at Cast3M error level `0`, produced every expected surface and volume BDF, and created the merged output. The equivalent `D = 2.2` configuration was validated against `H = 0.8`; tests confirm the same seed produces numerically equivalent surfaces under `D = 3 - H`.

| Quantity | Self-affine fractal | Constant planes |
|---|---:|---:|
| Grid points | 50 × 50 | 50 × 50 |
| Cast3M elapsed | 15.074886 s | 10.364480 s |
| Final surface quads | 2,590 | 2,590 |
| Volume HEXA8 | 5,180 | 5,180 |
| Circle wall/interface edges | 28 / 28 | 28 / 28 |
| Rectangle wall/interface edges | 32 / 32 | 32 / 32 |
| Residual square/fill seams | 0 | 0 |
| Positive center Jacobians | 5,180 | 5,180 |
| Negative or zero center Jacobians | 0 | 0 |
| Positive corner Jacobians | 41,440 | 41,440 |
| Negative or zero corner Jacobians | 0 | 0 |

The fractal field had requested `H = 0.8`, derived `D = 2.2`, RMS height `5e-5`, aperture `2e-4`, and seed `20260721`. The constant case used `zmin = 0` and `zmax = 2e-4`. The fractal walls are parallel realizations around one rough mean surface, not independent opposing-wall fields.

## Inflation evidence

The radial inflation check was retained at refinement 1. With `num_el_fill = 5` and `re_fact_hole = 5`, the mean hole-outward radii measured from the final Cast3M maximum surface were:

```text
0.0700000000
0.0720742468
0.0751759692
0.0798141260
0.0867497880
0.0971210218
```

The corresponding mean radial widths were:

```text
0.00207424678
0.00310172241
0.00463815677
0.00693566200
0.01037123383
```

- Measured outermost/hole-adjacent width ratio: `4.99999988`.
- Maximum pointwise error from the requested ring fractions: `6.37e-8`.
- Maximum hole-radius error: `6.32e-10`.

## Element-orientation checks

The retained refinement-1 integration check found:

- All 320 generated fill quads had positive signed XY area; minimum signed area was `1.4567e-5`.
- All 1,280 annular corner Jacobians were positive.
- All 2,595 quads on the final maximum surface were positive and non-zero.
- All 5,190 volume `HEXA8` center Jacobians were positive.
- All 41,520 volume corner Jacobians were positive; none had mixed or zero signs.

These orientation checks detect inverted or collapsed elements in that run. They do not replace a full mesh-quality study.

## Run isolation checks

- Before either scientific mesh mode starts, fixed-name BDF/MED/STL and prior generated fill files are moved—not deleted—to a timestamped `_previous_mesh_runs` subdirectory.
- The expected output manifest includes the volume, lower/upper/mean surfaces, four side surfaces, and exactly one hole surface per configured hole.
- When chambers are enabled, the manifest additionally requires the combined
  exterior, separate inlet/outlet volumes, and all named chamber boundaries.
- The workbench reports success only after process return code `0`, every expected fresh BDF exists, and the requested combined BDF was created.
- Focused tests verify that a stale third-hole surface is archived and is not part of the next two-hole output manifest.

## Controlled timing comparison

Reference measurements were retained from the complete verified benchmark; the scientific cases were rerun after conformal angular subdivision was added.

| `nelem_x = nelem_y` | Reference Cast3M | Scientific conformal path | Speed-up | Angular edges per hole | Scientific surface quads | Scientific volume hexes |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 17.900062 s | 9.729355 s | 1.840× | 32 | 2,595 | 5,190 |
| 2 | 63.403486 s | 14.037808 s | 4.517× | 64 | 9,740 | 19,480 |
| 4 | 247.457748 s | 40.639917 s | 6.089× | 128 | 37,680 | 75,360 |

At refinement 1, the reference and scientific exports retain the same element counts. At refinements 2 and 4, the scientific path intentionally adds the angular subdivisions required to make the hole-fill interface conformal; therefore its counts are higher than the old non-conformal reference. Python preparation took at most 0.053138 s in the controlled benchmark.

## Chamber integration verification

The embedded GUI preset and
[`examples/chambers/run.ini`](../examples/chambers/run.ini) use the same
validated `2 x 2 x 30` crack refinement, 15 radial hole cells, shared chamber
height `0.20`, inlet/outlet lengths `0.20`, ten height and length cells at each
end, and four grading ratios of five.

The full single-launcher headless run returned process code `0` and Cast3M
error level `0`. It found no missing outputs, preserved both 64-to-64 circular
hole interfaces, and wrote a 198,524,672-byte merged BDF. The safe Python STL
path converted 24 crack, hole, and chamber boundaries into 392,920 triangles;
no exactly degenerate triangle was omitted. The native Cast3M STL block was
present only as comments.

The resulting 177,009,121-byte volume BDF has SHA-256
`47c880db1517e8472c2d4dc791aa0e20681db0a0947c1439ac16ad3eb70fb580`,
identical to the reviewed chamber mesh used for the 798,400-HEXA8 topology,
six-surface partition, monotonic grading, and center/corner Jacobian checks.
Complete machine-readable evidence is in
[`validation-summary.json`](../examples/chambers/validation-summary.json).

## Source-free equivalence verification

The same chamber configuration was generated independently with
`mode = python_only`, without a DGIBI path and without resolving Cast3M or
Gmsh. A numbering-independent one-to-one coordinate mapping matched all
830,579 referenced nodes within an absolute tolerance of $10^{-9}$; the
maximum absolute coordinate difference was $5.0000004\times10^{-10}$.

Orientation-independent connectivity comparison matched all 798,400 HEXA8,
both 68,600-element chamber volumes, and all 24 named `CQUAD4` boundary sets.
An additional winding check matched every boundary quad while allowing only
cyclic node rotations, not reversed normals.
All eight Gauss-point Jacobians of every Python HEXA8 were positive; the
minimum scaled Jacobian was 0.4115766.

On the same host and example, the Cast3M mesh phase took 147.958791 seconds
and the final source-free mesh phase took 12.002355 seconds, a measured 12.33×
mesh-phase speed-up. The Python-only complete post-processing run took
27.527274 seconds. The older Cast3M report did not capture an equivalent
end-to-end time, so only mesh phases are compared; wall-clock results remain
host-, load-, and filesystem-cache-dependent.

The reproducible configuration, validator, methodology, and machine-readable
results are documented in
[`python-only-meshing.md`](python-only-meshing.md) and
[`validation-summary.json`](../examples/python-only-chambers/validation-summary.json).

## Known signal and validation boundary

The optimized Cast3M log contains `IEEE_INVALID_FLAG`; the unchanged reference run contains the same signal, so it is not attributed to the bulk import. This comparison does not prove numerical accuracy, FISS equivalence, mesh-quality equivalence, or suitability for a particular downstream CFD solver. A solver-specific mesh check remains required before production CFD use.
