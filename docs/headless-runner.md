# Headless INI runner

`castem_pipeline_gui_scientific.py --headless` executes the scientific pipeline without creating a Tk window. The scientific Python file is the single primary launcher for both interactive and unattended use. It reads all settings from a plain UTF-8 INI text file and uses the same preserved Cast3M templates, parameter patcher, conformal Python-hole generator, BDF merge, and executable discovery as the GUI. The older `castem_pipeline_headless.py` command remains available as a compatibility entry point.

## Use

Copy [the complete example configuration](../examples/scientific-run.ini), edit it, then validate it without starting Cast3M:

```powershell
python castem_pipeline_gui_scientific.py --headless path\to\run.ini --validate-only
```

Validation checks the INI schema, referenced files, numeric bounds, FISS setup, loaded or generated surface matrices, shape projection, and refined angular counts. It does not require or start Cast3M, and generated surfaces remain in memory during `--validate-only`.

Run the configured operation:

```powershell
python castem_pipeline_gui_scientific.py --headless path\to\run.ini
```

The process streams Cast3M output to the terminal, writes `castem-console.log`, and records `headless-run-report.json` in the configured working directory. A nonzero process or incomplete expected mesh manifest returns a nonzero command exit status.

## Surface sources

`[surface] mode` accepts `csv`, `fractal`, or `constant`. CSV mode reads the four paths from `[files]`. Generated modes write the same four-matrix contract below `_generated_surface_inputs` in the isolated working directory before the preserved Cast3M reader starts.

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
- `mode = python` uses the accelerated conformal inflated-hole fill.
- `mode = reference` uses the preserved Cast3M hole construction.

Any number of consecutively or non-consecutively numbered holes can be listed:

```ini
hole1 = circle, cx, cy, radius
hole2 = rectangle, cx, cy, width, height, rotation_degrees
hole3 = triangle, cx, cy, side_length, rotation_degrees
hole4 = regular_polygon, cx, cy, sides, circumradius, rotation_degrees
```

The legacy three-number circle shorthand remains valid. Non-circular shapes require `mode = python`; the preserved reference and FISS paths remain circle-only. See the [runnable all-shapes example](../examples/shaped-holes/all-shapes.ini).

## Output safety

With `archive_existing_outputs = true`, fixed-name prior mesh outputs are moved into a timestamped `_previous_mesh_runs` directory before a new mesh run. With it set to `false`, the runner refuses to start if such outputs exist. It never recursively cleans the configured directory.

`open_gmsh = true` opens the merged BDF, or the volume BDF when merging is disabled, after a successful mesh run. Keep it `false` for fully unattended execution.

Paths may be absolute or relative. Relative paths are resolved from the INI file location, making a configuration portable with the repository.
