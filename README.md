# DEM/CFD Crack Geometry to Mesh Converter

[![CI](https://github.com/onajjar/dem-cfd-crack-geometry-to-mesh-converter/actions/workflows/ci.yml/badge.svg)](https://github.com/onajjar/dem-cfd-crack-geometry-to-mesh-converter/actions/workflows/ci.yml)

A Windows desktop pipeline that turns four structured crack-surface CSV grids into Cast3M meshes, prepares a combined NASTRAN BDF for downstream CFD import, and optionally evaluates crack flow with Cast3M's `FISS` operator.

> **Baseline status:** `v0.1.0-baseline` is a pre-refactor publication of the current T13 program. The GUI and every file in `source_codes/` are preserved byte-for-byte. Documentation, examples, verification, and CI are additive; computational behavior is intentionally unchanged.

![Scientific workbench showing dynamic circle, rectangle, triangle, and regular-polygon controls](docs/assets/scientific-workbench.png)

## What it does

- Selects four comma-delimited surface grids: `xrange`, `yrange`, `zfit_zmax`, and `zfit_zmin`.
- Copies them to a working directory under the filenames expected by the Cast3M templates.
- Patches parameters only inside the marked `Main Program` section of a `.dgibi` template.
- Invokes Cast3M through its Windows batch launcher and streams solver output into the GUI.
- Creates a crack volume mesh and named boundary-surface meshes in NASTRAN BDF format.
- Supports zero, one, or multiple through-holes. The scientific mode accepts circles, rotated rectangles, rotated equilateral triangles, and regular polygons with any integer side count ≥ 3.
- Optionally exports MED/STL, combines volume and boundary BDF cards, and opens the selected mesh in Gmsh.
- Runs a separate, optional `FISS` flow calculation from the same four surface grids and post-processes solver text results into plots or HDF5.

## Workflow

```mermaid
flowchart LR
    A[Four numeric CSV grids] --> B[Tkinter GUI]
    B --> C[Canonical CSV copies]
    B --> D[Patch DGIBI Main Program]
    C --> E[Cast3M mesh run]
    D --> E
    E --> F[Volume and boundary BDFs]
    F --> G{Optional outputs}
    G --> H[Combined BDF]
    G --> I[MED / STL]
    F --> J[Gmsh preview]
    B --> K[Optional FISS setup]
    C --> K
    K --> L[Cast3M FISS run]
    L --> M[TXT results]
    M --> N[Plots / HDF5]
```

The same diagram is available as a [PNG](docs/assets/workflow.png) and editable [Mermaid source](docs/workflow.mmd).

## Verified baseline executions

### No-hole example

The example was run on 2026-07-10 by driving the unchanged GUI path with Cast3M annual version 2025.0 (launcher version `25`), `nelem_x=1`, `nelem_y=1`, `nelem_z=1`, no holes, no MED/STL export, Gmsh launch disabled, and BDF merge enabled.

| Result | Recorded value |
|---|---:|
| Process return code | `0` |
| Cast3M error level | `0` |
| GUI-observed elapsed time | 10.774 s |
| Combined BDF size | 2,742,398 bytes |
| Combined BDF cards | 15,000 `GRID`; 4,802 `CHEXA`; 5,194 `CQUAD4`; 6 `PSHELL` |

Cast3M also emitted a signalling `IEEE_INVALID_FLAG` after its normal stop. The run proves that this host executed the pipeline and produced the recorded files; it does not establish numerical accuracy, mesh quality, or downstream CFD compatibility. The sanitized [run report](examples/output/run-report.json), generated DGIBI, and combined BDF are committed with checksums.

![Exterior rendering of the real Cast3M volume BDF from the verified run](docs/assets/mesh-preview.png)

### Multiple-hole example

The same CSV quartet was also run through the unchanged GUI with two circular holes: `(-0.20, 0.20, 0.07)` and `(0.20, -0.20, 0.07)` as `(cx, cy, r)`. Cast3M returned `0`, stopped at error level `0`, exported two hole-surface BDFs, and the integrated merge produced a 2,917,106-byte combined BDF with 15,672 `GRID`, 5,190 `CHEXA`, 5,710 `CQUAD4`, and 8 `PSHELL` cards.

![Top view of the real Cast3M two-hole volume mesh](docs/assets/multiple-holes-mesh-preview.png)

The two-hole run carried the same `IEEE_INVALID_FLAG` notice and the same validation boundary as the no-hole run. See the [multiple-hole guide](examples/multiple-holes/README.md) for exact GUI values, a machine-readable configuration, reproduction commands, published output checksums, and the sanitized run report.

### Scientific launcher and accelerated hole path

`castem_pipeline_gui_scientific.py` is the single launcher for the enhanced workflow. It keeps the immutable T13 GUI and every file in `source_codes/` unchanged, while offering both the original reference mode and the fast bulk Python hole mode from one interface.

```powershell
python castem_pipeline_gui_scientific.py
```

For enabled holes, Python detects each outer contour, subdivides every fill-boundary edge with the matching `nelem_x`/`nelem_y` background count, projects the refined rays onto the selected circle or polygonal wall, constructs all radial layers with vectorized interpolation, and writes complete lower/upper/mean `CQUAD4` fill meshes to three small NASTRAN BDF files. Cast3M bulk-loads them with `LIRE 'NAS'`; the generated DGIBI contains no per-point `POIN` statements and does not call the expensive `REGL`, `INT_COMP`, or `DISPLACE` hole path. Reused working directories are isolated by archiving prior fixed-name mesh artifacts, and the GUI verifies the complete expected output manifest before reporting success.

`num_el_fill` sets the radial layer count. `re_fact_hole` is enforced as the outermost-to-hole-adjacent cell-width ratio using a geometric progression. With the documented `num_el_fill=5` and `re_fact_hole=5`, the outer-to-hole layer fractions are `0, 0.382406, 0.638136, 0.809153, 0.923519, 1`, giving an exact outer/inner width ratio of 5.

A standalone two-hole reproduction remains available for automated verification:

```powershell
python scripts\run_python_holes_example.py --clean
```

On the documented 50 × 50 CSV input with two holes and Cast3M 25, the conformal bulk-hole benchmark produced:

| `nelem_x = nelem_y` | Reference | Scientific bulk | Speed-up | Angular edges/hole |
|---:|---:|---:|---:|---:|
| 1 | 17.900 s | 9.729 s | 1.84× | 32 |
| 2 | 63.403 s | 14.038 s | 4.52× | 64 |
| 4 | 247.458 s | 40.640 s | 6.09× | 128 |

Python preparation took at most 0.054 s. The angular count now scales with the background edge refinement, deliberately adding cells for `r>1`: the scientific r=2 export has 9,740 surface quads and 19,480 volume hexes, versus 9,420 and 18,840 in the nonconformal reference construction. Recreate all six measurements with `--clean`, or retain the verified baseline cases and refresh only the scientific cases with `--reuse-baseline`:

```powershell
python scripts\benchmark_hole_optimization.py --clean
python scripts\benchmark_hole_optimization.py --reuse-baseline
```

This is an optimization, not a claim of byte-identical output: the non-planar 3D hole fill is a Python-generated `CQUAD4` mesh rather than Cast3M's planar `CERC`/`REGL` construction followed by displacement. Validate mesh quality and downstream CFD behavior for your geometry before production use. See the [method](docs/python-hole-interpolation.md) and [provisional verification](docs/provisional-verification.md).

### Real mesh comparison

The following image is rendered directly from the independently generated r=1 benchmark BDFs—not synthetic geometry. It uses matched cameras for the reference and optimized cases, with overall top views, enlarged first-hole inflation details, and isometric views.

![Actual Cast3M BDF comparison: baseline reference on the left and scientific bulk-hole run on the right](docs/assets/mesh-comparison-baseline-vs-python-holes.png)

At this r=1 refinement, both exports contain 5,190 `HEXA8` volume cells and 2,595 maximum-surface `CQUAD4` cells. The scientific export contains fewer BDF nodes (10,864 vs 15,672), retains all five inflated radial layers, and completed in 9.729 s rather than 17.900 s. At higher refinement, the scientific path intentionally adds angular hole cells to remain conformal. These comparisons do not prove numerical equivalence or general mesh quality.

The r=2 comparison below shows the corrected 64-edge circular interface. The additional scientific cells are intentional: they replace the former 32-to-64 hanging-node transition with equal edge counts.

![Actual refinement-2 comparison: former nonconformal reference on the left and corrected conformal scientific mesh on the right](docs/assets/mesh-comparison-r2-conformal.png)

Regenerate the image from the actual benchmark outputs:

```powershell
python -m pip install -r requirements-visuals.txt -c constraints-baseline.txt
python scripts\render_hole_mesh_comparison.py
python scripts\render_hole_mesh_comparison.py --refinement 2 --output docs\assets\mesh-comparison-r2-conformal.png
```

### Generalized hole shapes

The enhanced Python mode changes each row's active controls according to its shape:

| Shape | Per-hole controls |
|---|---|
| Circle | center, radius |
| Rectangle | center, width, height, rotation |
| Equilateral triangle | center, side length, rotation |
| Regular polygon | center, side count, circumradius, rotation |

![Real Cast3M mesh containing a circle, rotated rectangle, triangle, and regular hexagon](docs/assets/all-hole-shapes-mesh.png)

This image is rendered from the real four-shape Cast3M volume BDF. Its final maximum surface has matching square/hole-wall counts of `44=44`, `56=56`, `56=56`, and `56=56`, with zero residual square/fill boundary edges for every shape. Reproduce it with [the all-shapes INI](examples/shaped-holes/all-shapes.ini) or select **Load all shape examples** in the workbench.

### Scientific workbench

The scientific workbench is the single launcher for enhanced use. It separates geometry, mesh/holes, run/results, and FISS flow into focused tabs; supports a complete documented-configuration loader, mode-aware preflight, real XY-grid/hole and inflation-profile previews, explicit reference and bulk-inflated hole modes, mutually exclusive solver runs, verified fresh outputs, streamed solver status, a one-click **Open generated mesh in Gmsh** action, and access to the BDF comparison image.

```powershell
python castem_pipeline_gui_scientific.py
```

![Current scientific workbench walkthrough covering geometry, mesh controls, run results, and FISS setup](docs/assets/demo.gif)

![Scientific workbench: mesh and hole controls](docs/assets/scientific-workbench.png)

![Scientific workbench: run controls including one-click Gmsh opening](docs/assets/scientific-workbench-run-results.png)

See [docs/scientific-workbench.md](docs/scientific-workbench.md) for use, scope, and safety notes.

### Headless text-file runner

The same scientific mesh and FISS settings can be supplied in a plain INI file, with no Tk window:

```powershell
python castem_pipeline_gui_scientific.py --headless examples\scientific-run.ini --validate-only
python castem_pipeline_gui_scientific.py --headless examples\scientific-run.ini
```

The committed configuration lists every path, naming, mesh, hole, export, merge, Gmsh, and FISS option. Paths are resolved relative to the INI file. Set `operation` to `mesh`, `fiss`, or `both`; set `open_gmsh = true` only when a Gmsh window is wanted. See the [headless runner guide](docs/headless-runner.md).

## Requirements

| Component | Requirement | Purpose |
|---|---|---|
| Operating system | Windows | The baseline invokes `cmd.exe` and a Cast3M `.bat` launcher. |
| Python | 3.10 or newer, with Tkinter | The source uses Python 3.10 type syntax and a Tk desktop GUI. |
| Python packages | NumPy, Matplotlib | Required when the GUI module is imported. |
| HDF5 support | h5py | Needed for TXT-to-HDF5 FISS post-processing; the GUI otherwise treats it as optional. |
| Visual recreation | Pillow, meshio, PyVista/VTK | Optional; needed only to recapture documentation assets. |
| Cast3M | A compatible local installation | Required for mesh generation and `FISS`; not bundled here. |
| Gmsh | Optional local installation | Used only when opening a generated mesh for visualization. |

The audited development host used Python 3.13.5, Tk 8.6, NumPy 2.1.3, Matplotlib 3.10.0, h5py 3.12.1, Cast3M 25, and Gmsh 4.15.2. These versions describe the validated host, not a claim of exclusive compatibility.

## Installation

```powershell
git clone https://github.com/onajjar/dem-cfd-crack-geometry-to-mesh-converter.git
cd dem-cfd-crack-geometry-to-mesh-converter

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

To recreate the recorded top-level Python package versions used for the baseline runs, install with the committed constraints:

```powershell
python -m pip install -r requirements.txt -c constraints-baseline.txt
```

Cast3M is resolved in this order:

1. `CASTEM_PATH`, pointing to either a `castem*.bat` file or a directory containing one.
2. The built-in Windows Cast3M installation layout derived from the version field (`25` and `2025` both select the version-25 launcher).

Gmsh is resolved from `GMSH_PATH`, standard Program Files locations, matching folders in the current user's home directory, or `PATH`.

Example environment overrides:

```powershell
$env:CASTEM_PATH = 'path\to\castem25.bat'
$env:GMSH_PATH = 'path\to\gmsh.exe'
```

## Quick start

Launch the scientific application from the repository root so the existing icon and documented examples are discoverable:

```powershell
python castem_pipeline_gui_scientific.py
```

The immutable `castem_pipeline_gui_t13.py` remains available when an exact historical-baseline run is required.

Then:

1. Choose **Load documented example**, or select `source_codes\castem_tool.dgibi` as the mesh template.
2. Choose a fresh working directory. Generated meshes can be large and existing names may be replaced.
3. Select the four files in `examples\input` in their matching `xrange`, `yrange`, `zfit_zmax`, and `zfit_zmin` fields.
4. Keep the example naming parameters at `re_ti=60`, `re_crpa=1`, `re_smfa=0.05`, `re_numspa=50`, and `re_opmin=1e-6`.
5. Review mesh density, holes, inflation, export, merge, and Gmsh options. For holes, choose the reference mode or **Bulk Python hole mesh — fast + inflated**.
6. Validate inputs, select **Run converter**, and monitor the streamed log.

See [examples/README.md](examples/README.md) for the shared input/output policy, and [examples/multiple-holes/README.md](examples/multiple-holes/README.md) for the two-hole walkthrough.

## CSV input contract

Each input is a headerless, comma-delimited numeric matrix. The four matrices must have the same rectangular shape and at least two rows and two columns.

| Input | Meaning at grid index `(i, j)` |
|---|---|
| `xrange` | x coordinate |
| `yrange` | y coordinate |
| `zfit_zmax` | upper crack-surface z coordinate |
| `zfit_zmin` | lower crack-surface z coordinate |

The Cast3M templates derive:

```text
mean surface = (zfit_zmax + zfit_zmin) / 2
opening      =  zfit_zmax - zfit_zmin
```

Use decimal points, finite values, compatible coordinate grids, and `zfit_zmax >= zfit_zmin`. The GUI checks that files exist but does not validate matrix shape, contents, or physical consistency before starting Cast3M.

The unchanged post-processing converts x/y/z coordinates to centimetres and opening to micrometres for plots, so it implicitly treats the CSV coordinate values as metres.

The selected source filenames may be arbitrary. Before execution, the GUI copies them to names of this form:

```text
xrange_ti{ti}_crpa{crpa}_smfa{smfa_int}_numsp{numspa}_opmin{opmin_int}.csv
yrange_ti{ti}_crpa{crpa}_smfa{smfa_int}_numsp{numspa}_opmin{opmin_int}.csv
zfit_zmax_ti{ti}_crpa{crpa}_smfa{smfa_int}_numsp{numspa}_opmin{opmin_int}.csv
zfit_zmin_ti{ti}_crpa{crpa}_smfa{smfa_int}_numsp{numspa}_opmin{opmin_int}.csv
```

Here `smfa_int = round(re_smfa * 100)` and `opmin_int = round(re_opmin * 1e6)` in Python. Use values whose scaled forms are exact integers; the unchanged Cast3M templates use `ENTI`, which can otherwise disagree with Python rounding.

## Mesh outputs

With the supplied mesh template, a successful run writes:

| Output | Description |
|---|---|
| `castem_mesh_v.bdf` | Volume mesh. |
| `castem_mesh_surf_min.bdf`, `castem_mesh_surf_max.bdf` | Lower and upper crack surfaces. |
| `castem_mesh_surf_mean.bdf` | Mean surface; intentionally excluded from the integrated merge. |
| `castem_mesh_surf_xmin.bdf`, `..._xmax.bdf`, `..._ymin.bdf`, `..._ymax.bdf` | Side boundaries. |
| `castem_mesh_surf_trou_{n}.bdf` | One boundary per configured hole. |
| `combined_ti...bdf` | Optional merged volume and boundary BDF. |
| `castem_mesh_v.med` | Optional MED volume mesh. |
| `castem_mesh_surf_*.stl` | Optional triangulated surface exports. |

The combined file is a NASTRAN BDF assembled by the GUI's `merge_bdfs()` function. It is intended to simplify downstream CFD import, but this baseline does not automate or validate import into Ansys CFX and does not perform mesh-quality checks.

## Optional FISS flow calculation

The **Calcul (FISS)** path is a separate Cast3M run over the same CSV geometry; it does not consume the merged BDF. Choose `source_codes\fuite_fissure.dgibi` as its template.

The unchanged GUI exposes:

- Flow/friction models `POISEU_BLASIUS`, `POISEU_COLEBROOK`, `POISEU_GELAIN_2008`, `POISEU_GELAIN_2012`, `POISEU_RIZKALLA`, and `FROTTEMENT1` through `FROTTEMENT4`.
- Perfect (`PARF`) or real (`REEL`) gas choices.
- Mass (`MASS`) or film (`FILM`) condensation choices.
- Single values or ranges for upstream total pressure and inlet temperature.
- Downstream pressure, upstream steam pressure, wall temperature, line subdivision, and model-dependent material inputs.

The template builds lines through the crack, derives local opening and extent, and calls the Cast3M `FISS` operator. It exports geometry series and the fields `P`, `PV`, `TF`, `X`, `U`, `H`, `Q`, `QA`, `QE`, `RE`, and `F`. The GUI can read the semicolon-delimited text results, create `results.h5` when h5py is installed, and export plots.

`source_codes/fiss.eso` is operator source; the GUI does not compile or install it. The active Cast3M installation must already provide a compatible `FISS` operator.

## Repository layout

```text
.
├── castem_pipeline_gui_scientific.py    # primary enhanced launcher
├── castem_pipeline_gui_python_holes.py  # compatibility redirect/backend
├── castem_pipeline_headless.py          # compatibility headless backend/entry point
├── python_hole_interpolation.py         # bulk inflated fill generation
├── castem_pipeline_gui_t13.py           # unchanged baseline GUI
├── bpm_cfx.ico                  # unchanged GUI icon
├── source_codes/                # unchanged Cast3M and helper sources
├── examples/
│   ├── input/                   # existing 50 × 50 CSV quartet
│   ├── output/                  # verified no-hole run artifacts
│   ├── scientific-run.ini       # complete headless configuration
│   ├── shaped-holes/            # circle/rectangle/triangle/polygon gallery
│   └── multiple-holes/          # verified two-hole configuration/output
├── docs/
│   ├── assets/                  # authentic screenshots and diagrams
│   ├── headless-runner.md
│   ├── provisional-verification.md
│   ├── python-hole-interpolation.md
│   ├── scientific-workbench.md
│   ├── source-audit.md
│   └── workflow.mmd
├── scripts/                     # baseline verification and visual tooling
├── tests/                       # non-invasive structural/hash tests
└── .github/workflows/ci.yml
```

## Reproducibility checks

Verify the immutable baseline files against the committed SHA-256 manifest:

```powershell
python scripts\verify_baseline.py
```

Run the non-invasive checks used by CI:

```powershell
python -m pip install -r requirements-dev.txt -c constraints-baseline.txt
python -m ruff check .
python -m compileall -q .
python -m pytest -q
```

These checks validate source preservation and Python syntax. They do not replace a licensed Cast3M execution or numerical validation.

With Cast3M installed, also run the optimized-hole integration example and the measured comparison:

```powershell
python scripts\run_python_holes_example.py --clean
python scripts\benchmark_hole_optimization.py --clean
```

### Rebuild documentation visuals

The visual tools are intentionally separate from the GUI runtime dependencies:

```powershell
python -m pip install -r requirements-visuals.txt -c constraints-baseline.txt
python scripts\render_workflow.py
```

On a Windows desktop, `python scripts\capture_scientific_ui.py` recreates the scientific-workbench screenshots and animated walkthrough with repository-relative paths. `python scripts\capture_demo.py` remains a compatibility alias for the same capture. After a successful Cast3M run, `python scripts\render_mesh.py` recreates the mesh preview from the real volume BDF. The multiple-hole guide provides its exact runner and render command.

## Limitations and known baseline behavior

- The immutable T13 implementation remains an intentionally unrefactored Windows baseline. The scientific workbench and INI runner are additive Windows launchers, not a cross-platform packaging layer.
- The scientific bulk-hole path is additive. Its common rectilinear interpolation is vectorized; the robust bilinear-inversion fallback for curvilinear structured grids still searches cells per query point. Its `CQUAD4` fill is not numerically or node-for-node equivalent to the preserved Cast3M planar-arc/displacement construction.
- Generalized shapes are convex and center-star-shaped: circles, rectangles, equilateral triangles, and regular polygons. Arbitrary concave polygons, free-form splines, and user-supplied vertex lists are not yet supported.
- Non-circular holes require the scientific Python mode. The preserved T13 reference mode and preserved FISS path remain circle-only.
- Cast3M and Gmsh are external applications and are not installed by `requirements.txt`.
- The scientific workbench validates matrix shape, finiteness, coordinate compatibility, and non-negative opening before execution; these structural checks do not establish physical consistency.
- The integrated BDF merger imports `CQUAD4` boundary cards, assigns one `PSHELL` per surface file, and excludes the mean surface. It is not a general-purpose BDF merger.
- **FISS model parameters:** the patcher replaces only the first matching assignment in the template's Main Program. Because the supplied FISS template repeats material variables in multiple model blocks, some entered overrides can affect an earlier inactive block while the selected model retains a hard-coded value. This behavior is preserved and must be verified in the generated `.dgibi` before relying on a study.
- Enabling **View mesh in Gmsh** also writes `opti_visu=1`; the supplied Cast3M template performs its own `TRAC` operation before the GUI opens Gmsh.
- FISS post-processing moves converted text files into a timestamped quarantine directory. Keep the original run directory if raw results matter.
- Solver meshes and flow results can grow from megabytes to many gigabytes. Generated outputs are ignored by default and should be archived outside Git unless deliberately reviewed.
- The standalone `source_codes/merge_surface_bdf.py` is retained for provenance but differs from the merger embedded in the GUI.

## Troubleshooting

**Cast3M executable not found**

Set `CASTEM_PATH` to the batch file or its containing directory, or enter a version matching the default Cast3M installation layout.

**Gmsh executable not found**

Uncheck **View mesh in Gmsh**, or set `GMSH_PATH` to the executable or its directory. Mesh generation does not require Gmsh.

**Tkinter import error**

Install a Python distribution that includes Tcl/Tk. Tkinter is normally included with the standard Windows Python installer.

**Cast3M cannot find a CSV**

Confirm all four naming parameters match the example and use exactly scaled `re_smfa`/`re_opmin` values. Inspect the copied filenames in the working directory.

**HDF5 conversion is unavailable**

Install the full runtime requirements with `python -m pip install -r requirements.txt`; h5py is needed for that post-processing path.

**Unexpectedly large output**

Use a fresh work directory and start with conservative `nelem_x`, `nelem_y`, and `nelem_z` values. Do not add generated BDF, MED, STL, HDF5, or solver text trees to Git by default.

## Project status, provenance, and licensing

This release is a preservation point for future testing and refactoring. See [CHANGELOG.md](CHANGELOG.md), [the source audit](docs/source-audit.md), [CONTRIBUTING.md](CONTRIBUTING.md), and the [Code of Conduct](CODE_OF_CONDUCT.md).

No `LICENSE` file was present in the supplied project, so none has been added. Public source visibility alone does not grant reuse, modification, or redistribution rights. If the maintainer confirms the right to license all distributed material, the MIT License is recommended for the Python project; the provenance and redistribution terms of `source_codes/fiss.eso` must still be confirmed before describing this repository as open source.

Please report security concerns through the process in [SECURITY.md](SECURITY.md).
