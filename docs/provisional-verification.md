# Provisional verification — scientific bulk-hole path

Verification date: 2026-07-11. Host: Windows, Python 3.13.5, Cast3M annual version 2025 (launcher version `25`). These measurements apply to the documented 50 × 50 CSV quartet and two holes `(-0.20, 0.20, 0.07)` and `(0.20, -0.20, 0.07)`.

This is implementation evidence, not scientific validation.

## Preservation and static checks

- `python -B scripts\verify_baseline.py`: all 6 immutable files matched their committed SHA-256 values.
- `python -B -m compileall -q .`: passed.
- `python -B -m pytest -q -p no:cacheprovider tests`: 15 tests passed.
- The derived optimized DGIBI contains three `LIRE 'NAS'` mesh imports and no generated per-node `POIN` statements.
- Its hole-fill replacement contains no `REGL (-1*num_el_fill)`, `INT_COMP surf_zmin_comp`, or `DISPLACE surf_zmin` call.

## Real Cast3M integration

The final hardened-code rerun, `python -B scripts\run_python_holes_example.py --clean --output _runtime\final-bulk-hole-integration`, completed with process return code `0`, Cast3M error level `0`, and a generated volume BDF.

For each of the lower, upper, and mean fill surfaces, Python wrote:

| Quantity | Value |
|---|---:|
| Detected contour nodes per hole | 32 |
| Rings per hole | 6 |
| Radial cells per hole | 5 |
| Nodes across two holes | 384 |
| `CQUAD4` cells across two holes | 320 |
| Python preparation time | 0.019746 s |
| Cast3M time | 8.982857 s |

Cast3M preserved all 32 radial edges in every transition and all 160 annular quads per hole.

## Inflation evidence

With `num_el_fill=5` and `re_fact_hole=5`, the mean hole-outward radii measured from the final Cast3M maximum surface were:

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

- All 320 generated fill quads had positive signed XY area; minimum signed area was `1.4567e-5`.
- All 1,280 annular corner Jacobians were positive.
- All 2,595 quads on the final maximum surface were positive and non-zero.
- All 5,190 volume `HEXA8` center Jacobians were positive.
- All 41,520 volume corner Jacobians were positive; none had mixed or zero signs.

These orientation checks detect inverted or collapsed elements in this run. They do not replace a full mesh-quality study.

## Run isolation checks

- Before either scientific mesh mode starts, fixed-name BDF/MED/STL and prior generated fill files are moved—not deleted—to a timestamped `_previous_mesh_runs` subdirectory.
- The expected output manifest includes the volume, lower/upper/mean surfaces, four side surfaces, and exactly one hole surface per configured hole.
- The workbench reports success only after process return code `0`, every expected fresh BDF exists, and the requested combined BDF was created.
- Focused tests verify that a stale third-hole surface is archived and is not part of the next two-hole output manifest.

## Controlled timing comparison

Reference measurements were retained from the complete verified benchmark; the scientific cases were then rerun with `--reuse-baseline` after the bulk-import change.

| `nelem_x = nelem_y` | Reference Cast3M | Scientific bulk path | Speed-up | Surface quads | Volume hexes |
|---:|---:|---:|---:|---:|---:|
| 1 | 17.900062 s | 9.645498 s | 1.856× | 2,595 | 5,190 |
| 2 | 63.403486 s | 15.721796 s | 4.033× | 9,420 | 18,840 |
| 4 | 247.457748 s | 36.806058 s | 6.723× | 36,720 | 73,440 |

At every refinement, the reference and scientific exports had identical surface-quad and volume-hex counts. Python preparation took at most 0.021470 s in the controlled benchmark.

## Known signal and validation boundary

The optimized Cast3M log contains `IEEE_INVALID_FLAG`; the unchanged reference run contains the same signal, so it is not attributed to the bulk import. Neither this comparison nor matching cell counts proves coordinate equivalence, mesh-quality equivalence, numerical accuracy, FISS equivalence, or downstream CFD compatibility.
