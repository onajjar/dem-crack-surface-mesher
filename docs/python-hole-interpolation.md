# Bulk inflated hole meshing

The scientific launcher uses a Python-generated surface mesh for the circular-hole fill only. The immutable T13 GUI and every file under `source_codes/` remain unchanged.

## Why this path exists

The reference DGIBI constructs each fill at `z = 0`, creates graded radial lines with Cast3M, and then evaluates and displaces nodes on the lower, upper, and mean crack surfaces. On the documented two-hole input, those whole-mesh `INT_COMP` and `DISPLACE` operations dominate runtime as the background refinement increases.

The accelerated path moves the bounded fill construction to Python and gives Cast3M each complete surface in one file. It does not emit one DGIBI `POIN` or `DROI` statement per node.

## Algorithm

For every configured hole, the implementation:

1. Reproduces the T13 `CR_SURF`/`CIRC_INT` outer-corner selection and angular ordering.
2. Projects that ordered contour radially onto the requested circle.
3. Constructs all radial rings at once with NumPy broadcasting.
4. Evaluates `zmin`, `zmax`, and their mean at all ring nodes. The common rectilinear-grid path uses vectorized cell lookup and bilinear interpolation; structured curvilinear grids use the more conservative cell-search fallback.
5. Builds all `CQUAD4` connectivity and validates finite coordinates, connectivity bounds, non-zero area, and consistent orientation.
6. Writes complete `python_hole_fill_min.bdf`, `python_hole_fill_max.bdf`, and `python_hole_fill_mean.bdf` files.
7. Replaces only the derived run program's expensive hole-correction block with three `LIRE 'NAS'` imports and merges the imported meshes into the corresponding Cast3M surfaces.
8. Archives fixed-name artifacts from a prior run before launching Cast3M, then verifies the complete expected output manifest before the GUI reports success.

The source template on disk is never edited.

## Radial inflation

`num_el_fill = N` is the number of radial cells. `re_fact_hole = F` is the requested ratio between the outermost cell width and the hole-adjacent cell width.

For `N > 1`, outer-to-hole cell widths form a geometric sequence with ratio

```text
q = F^(-1 / (N - 1))
```

and the cumulative ring fractions are the normalized cumulative sum of `1, q, q^2, ..., q^(N-1)`. Thus the first width divided by the last width is exactly `F`. `N = 1` produces a single ungraded radial cell.

For the documented settings `N = 5` and `F = 5`, the outer-to-hole ring fractions are:

```text
0.000000000
0.382405718
0.638135835
0.809152871
0.923518856
1.000000000
```

The resulting cells become smaller toward the hole. This is the intended near-hole inflation and is visible in the final comparison image.

## Run it

Use the scientific launcher for interactive work:

```powershell
python castem_pipeline_gui_scientific.py
```

Select **Bulk Python hole mesh — fast + inflated** in the mesh mode control. For the documented two-hole case, the non-interactive equivalent is:

```powershell
python scripts\run_python_holes_example.py --clean
```

Benchmark the reference and scientific modes with:

```powershell
python scripts\benchmark_hole_optimization.py --clean
```

After one complete verified benchmark, refresh only the accelerated cases while retaining the reference measurements with:

```powershell
python scripts\benchmark_hole_optimization.py --reuse-baseline
```

## Scope and limitations

- The generated fill is not byte-for-byte or node-for-node equivalent to the reference Cast3M construction.
- The common rectilinear path is vectorized. The fallback for general structured curvilinear grids performs a per-query cell search and should be benchmarked on unusually large contours.
- A successful Cast3M run and positive element-orientation checks do not establish numerical accuracy, CFD suitability, or solver-independent mesh quality.
- Hole overlap, a hole intersecting the exterior boundary, or a highly distorted source grid remains outside the validated example envelope.
- Previous mesh artifacts are retained under `_previous_mesh_runs`; long-lived working directories should be reviewed periodically for storage use.

Measured execution and geometry checks are recorded in [provisional-verification.md](provisional-verification.md).
