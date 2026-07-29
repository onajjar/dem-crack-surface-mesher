# Headless INI runner

`castem_pipeline_gui_scientific.py --headless` executes the scientific
pipeline without creating a Tk window. The scientific Python file is the
single primary launcher for both interactive and unattended use. It reads all
settings from a plain UTF-8 INI text file and exposes both the preserved
Cast3M paths and the source-free Python HEXA8 backend used by the GUI. The
older `castem_pipeline_headless.py` command remains available as a
compatibility entry point.

## Use

Copy [the complete example configuration](../examples/scientific-run.ini), edit it, then validate it without starting Cast3M:

```powershell
python castem_pipeline_gui_scientific.py --headless path\to\run.ini --validate-only
```

Validation checks the INI schema, referenced files, numeric bounds, FISS
setup when applicable, loaded or generated surface matrices, shape projection,
and refined angular counts. It does not start Cast3M. In `python_only` mode it
does not resolve Cast3M and does not require a mesh template.

Run the configured operation:

```powershell
python castem_pipeline_gui_scientific.py --headless path\to\run.ini
```

Override only the surface decision for an individual run with
`--surface-mode deap` (fit raw HDF5 in Python) or `--surface-mode csv` (use the
four existing files). `fit` and `python_fit` are aliases for `deap`.

The process streams Cast3M output to the terminal, writes `castem-console.log`, and records `headless-run-report.json` in the configured working directory. A nonzero process or incomplete expected mesh manifest returns a nonzero command exit status.

## Surface sources

`[surface] mode` accepts `csv`, `deap`, `fractal`, or `constant`. CSV mode reads the four paths from `[files]`. DEAP mode reads `deap_post.h5`, `deap_output.h5`, and normally `input.boundary` from `[run] working_directory`, then fits both crack faces with the Python quadratic LOESS implementation. Generated modes write the same four-matrix contract below `_generated_surface_inputs` in the isolated working directory before the preserved Cast3M reader starts.

```ini
[run]
working_directory = results

[surface]
mode = deap
orientation = YZ
magnification = 1.0
# Required only when results/input.boundary is absent:
bounding_box = -0.055 0.055 -0.055 0.055 0.0 0.05

[naming]
ti = 85
crpa = 1
smfa = 0.05
numspa = 50
opmin = 1e-6
```

The five `[naming]` values are required manual inputs only in DEAP mode: they
are the fitter's time step, MATLAB-style component number, span, grid
resolution, and opening threshold. CSV mode ignores entered `[naming]` values
and derives all five from the canonical suffix shared by its four filenames.
It rejects a noncanonical filename or inconsistent suffixes. Fractal and
constant modes retain the established `60/1/0.05/50/1e-6` metadata defaults.
Legacy CSV names ending at `_numspN.csv` remain accepted with the established
`opmin = 1e-6` default.
Each fit writes `_generated_surface_inputs/deap-fit-report.json`; the final
headless report embeds the same metadata. Complete DEAP/CSV dual-mode examples
are in [`examples/deap`](../examples/deap/README.md).

```ini
[surface]
mode = fractal
points_x = 50
points_y = 50
size_x = 1.2
size_y = 0.9
center_x = 0.0
center_y = 0.0
hurst_exponent = 0.8
fractal_dimension =
rms_height = 5e-5
mean_aperture = 2e-4
random_seed = 20260721
```

Specify either `hurst_exponent` or `fractal_dimension`; if both are present they must satisfy `D = 3 - H`. The accepted ranges are `0 < H < 1` and `2 < D < 3`. RMS height supplies the vertical roughness scale that an exponent alone cannot define. The seed makes the spectral synthesis reproducible.

```ini
[surface]
mode = constant
points_x = 50
points_y = 50
size_x = 1.2
size_y = 0.9
center_x = 0.0
center_y = 0.0
constant_zmin = 0.0
constant_zmax = 2e-4
```

`constant_zmax` must exceed `constant_zmin`; identical planes have zero volume. Runnable Hurst, fractal-dimension, and constant-plane configurations are in [`examples/surfaces`](../examples/surfaces/README.md). The complete [`scientific-run.ini`](../examples/scientific-run.ini) comments every accepted surface key.

## Operations and modes

- `operation = mesh` runs only mesh generation.
- `operation = fiss` runs only the configured FISS calculation.
- `operation = both` runs mesh first and starts FISS only after mesh success.
- `operation = characterize` calculates and exports crack characteristics
  without resolving or starting Cast3M.
- `operation = characterize_and_mesh` characterizes the same reconstructed
  surface first and continues to the selected mesh backend only after success.
- `mode = python` uses the accelerated conformal inflated-hole fill.
- `mode = python_only` builds the complete HEXA8 volume, holes, and optional
  chambers in Python without a mesh template, Cast3M, or Gmsh.
- `mode = reference` uses the preserved Cast3M hole construction.

For `mode = python_only`, `[files] mesh_template` and `fiss_template` may be
omitted when the operation does not include FISS. `open_gmsh` must be false;
the backend always writes `python_mesh_preview.png` instead. See
[`python-only-meshing.md`](python-only-meshing.md) and the runnable
[`python-only-chambers`](../examples/python-only-chambers/README.md) case.

Setting `[characterization] enabled = true` also inserts the optional stage
before a normal mesh operation. Existing INI files with no section retain their
previous direct-to-mesh behavior. The complete section in
[`examples/scientific-run.ini`](../examples/scientific-run.ini) documents
aperture definition, global/custom flow vector, cutoff, units, normal
smoothing, Hurst fit range/bootstrap, figures, and output location.

An optional `[synthetic]` section generates a seeded anisotropic surface,
writes the same four canonical CSVs, reruns characterization, and exports
target-versus-achieved values. Characterization is Python-only; MATLAB is not a
runtime dependency.

Any number of consecutively or non-consecutively numbered holes can be listed:

```ini
hole1 = circle, cx, cy, radius
hole2 = rectangle, cx, cy, width, height, rotation_degrees
hole3 = triangle, cx, cy, side_length, rotation_degrees
hole4 = regular_polygon, cx, cy, sides, circumradius, rotation_degrees
```

The legacy three-number circle shorthand remains valid. Non-circular shapes
require `mode = python` or `mode = python_only`; the preserved reference and
FISS paths remain circle-only. See the
[runnable all-shapes example](../examples/shaped-holes/all-shapes.ini).

## Inlet and outlet chambers

The optional `[chambers]` section creates attached boxes at the crack's global
`Ymin` and `Ymax` faces. In Cast3M mode, the single maintained
`[files] mesh_template` owns the complete geometry behind `opti_chamb`; the
runner only patches its validated scalar values. In `python_only` mode, the
independent Python topology builder consumes the same values and creates the
equivalent conformal chamber volumes directly.

```ini
[chambers]
enabled = true
height = 0.20
inlet_length = 0.20
outlet_length = 0.20
inlet_height_elements = 10
outlet_height_elements = 10
inlet_length_elements = 10
outlet_length_elements = 10
inlet_height_ratio = 5
outlet_height_ratio = 5
inlet_length_ratio = 5
outlet_length_ratio = 5
```

`height` is shared by both chambers and split equally above and below the
crack. Each height-element count is therefore a total, positive, even number.
Length counts are positive integers. Every ratio must be at least one, placing
the smallest cells at the crack/chamber junction and increasing their size
toward the remote chamber wall. Chamber mode accepts `mesh mode = python` or
`mesh mode = python_only`.

The complete runnable example is
[`examples/chambers/run.ini`](../examples/chambers/run.ini):

```powershell
python.exe .\castem_pipeline_gui_scientific.py --headless .\examples\chambers\run.ini --validate-only
python.exe .\castem_pipeline_gui_scientific.py --headless .\examples\chambers\run.ini
```

The headless report records all chamber dimensions, counts, and ratios.
The source-free equivalent is:

```powershell
python.exe .\castem_pipeline_gui_scientific.py --headless .\examples\python-only-chambers\run.ini --validate-only
python.exe .\castem_pipeline_gui_scientific.py --headless .\examples\python-only-chambers\run.ini
```

## Output safety

With `archive_existing_outputs = true`, fixed-name prior mesh outputs are moved into a timestamped `_previous_mesh_runs` directory before a new mesh run. With it set to `false`, the runner refuses to start if such outputs exist. It never recursively cleans the configured directory.

With `export_stl = true`, the generated Cast3M source contains the native
`SORT 'STL'` block as comments, so Cast3M cannot abort on coincident vertices.
In either backend, Python writes the requested lower, upper, mean, side, and
hole surfaces as ASCII STL with 17-significant-digit coordinates after all
boundary BDFs are verified. Exactly zero-area BDF triangles are reported and
omitted. This also avoids the additional coordinate collapse that binary
STL's 32-bit vertices can introduce for micron-scale openings.
When chambers are enabled, the same safe converter also exports the complete
chamber exterior and every named inlet/outlet boundary BDF.

`open_gmsh = true` opens the merged BDF, or the volume BDF when merging is
disabled, after a successful Cast3M mesh run. It never enables Cast3M's
internal visualization: generated DGIBI files always contain `opti_visu=0`.
Python-only mode rejects this option and writes an automatic Matplotlib
preview instead. Keep it `false` for fully unattended execution.

Paths may be absolute or relative. Relative paths are resolved from the INI file location, making a configuration portable with the repository.
