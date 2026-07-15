# Bulk inflated hole meshing

The scientific launcher uses a Python-generated surface mesh for circle, rectangle, equilateral-triangle, and regular-polygon fills. The immutable T13 GUI and every file under `source_codes/` remain unchanged.

## Why this path exists

The reference DGIBI constructs each fill at `z = 0`, creates graded radial lines with Cast3M, and then evaluates and displaces nodes on the lower, upper, and mean crack surfaces. On the documented two-hole input, those whole-mesh `INT_COMP` and `DISPLACE` operations dominate runtime as the background refinement increases.

The accelerated path moves the bounded fill construction to Python and gives Cast3M each complete surface in one file. It does not emit one DGIBI `POIN` or `DROI` statement per node.

## Algorithm

For every configured hole, the implementation:

1. Reproduces the T13 outer-corner selection and angular ordering using a conservative bounding square.
2. Subdivides every ordered outer edge with the same `nelem_x` or `nelem_y` count that Cast3M uses on the adjacent background cell.
3. Projects every subdivided outer node along its center ray onto the requested circle or convex polygonal boundary, giving the hole wall and square interface identical counts.
4. Constructs all radial rings at once with NumPy broadcasting.
5. Evaluates `zmin`, `zmax`, and their mean at all ring nodes. The common rectilinear-grid path uses vectorized cell lookup and bilinear interpolation; structured curvilinear grids use the more conservative cell-search fallback.
6. Builds all `CQUAD4` connectivity and validates finite coordinates, connectivity bounds, non-zero area, and consistent orientation.
7. Writes complete `python_hole_fill_min.bdf`, `python_hole_fill_max.bdf`, and `python_hole_fill_mean.bdf` files.
8. Replaces only the derived run program's expensive hole-correction block with three `LIRE 'NAS'` imports and merges the imported meshes into the corresponding Cast3M surfaces.
9. Archives fixed-name artifacts from a prior run before launching Cast3M, then verifies the complete expected output manifest before the GUI reports success.

The source template on disk is never edited.

## Conformal angular subdivision

The original fast path projected only the coarse outer contour. With `nelem_x=nelem_y=2`, Cast3M could place twice as many edges on the surrounding background boundary as the fill, producing hanging nodes. The corrected path inserts the background subdivisions first and then projects them onto the selected wall. The final four-shape verification reported exact pairs of `44=44`, `56=56`, `56=56`, and `56=56`, with no residual square/fill boundary edges.

## Supported geometry

- Circle: radius.
- Rectangle: width, height, and in-plane rotation.
- Equilateral triangle: side length and in-plane rotation.
- Regular polygon: integer side count ≥ 3, circumradius, and in-plane rotation.

All shapes use a center point and must be fully contained in the source grid. The projection requires a convex, center-star-shaped boundary; arbitrary concave or free-form geometry is outside the current implementation.

Positive rotations are counter-clockwise. Rectangle rotation is measured from the +X width axis; triangle and regular-polygon rotation is the angular position of their first vertex from +X.

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

For all supported shapes together:

```powershell
python castem_pipeline_gui_scientific.py --headless examples\shaped-holes\all-shapes.ini
python scripts\verify_shape_interfaces.py
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
