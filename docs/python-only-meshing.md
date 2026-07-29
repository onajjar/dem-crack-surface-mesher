# Source-free Python HEXA8 meshing

## Purpose

The `python_only` backend generates the complete volume and named boundary
meshes directly from the reconstructed crack surfaces. It does not read a
DGIBI source and does not resolve, start, or require Cast3M or Gmsh. The same
option is available in the single Scientific Workbench window and in the
headless INI runner.

FISS remains a separate Cast3M calculation. This backend replaces Cast3M and
Gmsh for meshing only.

## Backend choice

| Mode | Hole and chamber geometry | Volume construction | External programs |
|---|---|---|---|
| `python_only` | Python | Python | None |
| `python` | Python hole fills; chamber branch in DGIBI | Cast3M | Cast3M; Gmsh only when requested |
| `reference` | Preserved DGIBI path | Cast3M | Cast3M; Gmsh only when requested |

Python-only is the GUI default. The workbench disables the Cast3M DGIBI entry,
its Browse button, the Cast3M launcher version, and the Gmsh checkbox because
none applies to this backend; selecting a Cast3M mode restores those controls.
Python-only creates `python_mesh_preview.png` automatically. The
**Python-only chamber example** button fills the complete validated example
without opening another window.

## Mesh construction

### Structured crack surface

Every quadrilateral of the input $x,y$ tables is subdivided bilinearly. The
implementation preserves the established `CR_SURF` control convention:

- `elements_x` subdivides the direction along table rows;
- `elements_y` subdivides between the ruled row lines; and
- shared coordinates are deduplicated within `geometric_tolerance`.

The lower, mean, and upper values at every refined point are obtained by
bilinear interpolation of `zfit_zmin`, their arithmetic mean, and
`zfit_zmax`. Supported circular and polygonal holes use the same conformal
inflated-ring algorithm as the scientific bulk-hole path.

### Through-opening grading

The crack is divided into two blocks around the mean surface. For each block,
the endpoint target sizes are those already defined by `elements_z` and
`z_inflation_factor`. The source-free backend reproduces Cast3M's fixed-count
`DECOUP`/`VOLUME` progression.

For interval length $L$, endpoint sizes $D_1,D_2$, and prescribed count
$N$, define

$$
d_1=\frac{D_1}{L},\qquad
d_2=\frac{D_2}{L},\qquad
a=\frac{(d_1-d_2)^2}{2}.
$$

The geometric progression factor is

$$
r=1+a+\operatorname{sign}(d_2-d_1)\sqrt{a(2+a)}.
$$

The $N$ unnormalised widths are proportional to
$r,r^2,\ldots,r^N$; dividing their cumulative sum by the total gives the
nodal fractions from zero to one. The uniform case uses $r=1$.

The upper and lower graded stacks share the mean layer exactly. Each surface
quadrilateral is then connected into ordered HEXA8 elements.

### Chambers

When enabled, the inlet is attached to global `Ymin` and extends in negative
Y; the outlet is attached to global `Ymax` and extends in positive Y. The
existing chamber controls are preserved:

- one common height and independent inlet/outlet lengths;
- independent total height and length element counts; and
- independent height and length grading ratios.

Each even height count is split equally above and below the local crack
interface. Length cells grow toward the remote boundary, while height cells
grow away from the local crack opening. Interface nodes are shared with the
crack, so the combined volume is conformal.

## Outputs

The backend writes the same names expected by downstream workflows:

- `castem_mesh_v.bdf` and optional inlet/outlet volume BDFs;
- lower, mean, upper, four crack sides, and one wall per hole;
- complete and individually named chamber boundaries;
- optional merged BDF and high-precision ASCII STL files;
- optional `castem_mesh_v.med` through `meshio`;
- `python_mesh_preview.png`; and
- `python-mesh-report.json` in GUI runs or `headless-run-report.json` in
  headless runs.

The automatic preview uses Matplotlib and is deliberately independent of
Gmsh. MED export requires the Python `meshio` package included in
`requirements.txt`.

## Reproduce the documented case

From the repository root:

```powershell
python.exe .\castem_pipeline_gui_scientific.py --headless `
  .\examples\python-only-chambers\run.ini --validate-only
python.exe .\castem_pipeline_gui_scientific.py --headless `
  .\examples\python-only-chambers\run.ini
```

The INI intentionally omits both `mesh_template` and `fiss_template`. Relative
paths are resolved from the INI directory.

## Equivalence verification

The documented two-hole chamber case was generated once with the reviewed
Cast3M backend and once with `python_only`. The validator performs a one-to-one
nearest-neighbour coordinate bijection, independent of node numbering, and
compares two orientation-independent connectivity fingerprints for every
volume and boundary element. It then compares each CQUAD4 winding separately:
cyclic rotations are equivalent, but a reversed normal is not accepted.

| Check | Result |
|---|---:|
| Referenced nodes | 830,579 vs 830,579 |
| Maximum absolute coordinate difference | $5.0000004\times10^{-10}$ |
| Maximum Euclidean coordinate difference | $8.6602544\times10^{-10}$ |
| Total HEXA8 topology | 798,400 / 798,400 matched |
| Inlet chamber | 68,600 / 68,600 matched |
| Outlet chamber | 68,600 / 68,600 matched |
| Named boundary topology and winding | 24 / 24 matched |
| Non-positive Jacobians | 0 |
| Minimum scaled Jacobian | 0.4115766 |

Jacobian determinants are evaluated at all eight $2\times2\times2$ Gauss
points of every HEXA8. The complete machine-readable evidence is
[`validation-summary.json`](../examples/python-only-chambers/validation-summary.json).

Re-run the independent comparison after producing both working directories:

```powershell
python.exe .\validation\validate_python_only_mesh.py `
  --reference-directory path\to\cast3m-run `
  --python-directory path\to\python-run `
  --output .\examples\python-only-chambers\validation-summary.json
```

## Runtime comparison

On the same documented case and host, the recorded Cast3M mesh phase took
147.958791 seconds and the final Python-only mesh phase took 12.002355 seconds.
The source-free mesh phase was therefore **12.33 times faster**. Its complete
mesh-plus-BDF/STL/merge/preview run took 27.527274 seconds.

The speedup deliberately compares mesh-generation phases. The older Cast3M
report did not record a complete post-processing wall time, so no unsupported
end-to-end Cast3M speedup is claimed. These are host-specific wall-clock
measurements and can vary with filesystem cache and system load.

## Algorithm provenance and limits

The fixed-count grading was derived from the official Cast3M
[`DECOUP`](https://www-cast3m.cea.fr/index.php?page=sources&source=decoup) and
[`VOLUME`](https://www-cast3m.cea.fr/index.php?page=sources&source=volume)
operator sources. The implementation is independent Python code and does not
ship or execute those sources.

The backend requires strictly positive crack opening at every refined mesh
point. Chambers are limited to global `Ymin` and `Ymax`, matching the
established model. Exact mesh equivalence does not by itself establish CFD
solution equivalence; retain the usual target-solver import and physical
verification.
