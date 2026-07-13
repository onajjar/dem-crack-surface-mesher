# Headless INI runner

`castem_pipeline_headless.py` executes the scientific pipeline without creating a Tk window. It reads all settings from a plain UTF-8 INI text file and uses the same preserved Cast3M templates, parameter patcher, conformal Python-hole generator, BDF merge, and executable discovery as the GUI.

## Use

Copy [the complete example configuration](../examples/scientific-run.ini), edit it, then validate it without starting Cast3M:

```powershell
python castem_pipeline_headless.py path\to\run.ini --validate-only
```

Validation checks the INI schema, referenced files, numeric bounds, FISS setup, CSV matrices, circle detection, and refined angular counts. It does not require or start Cast3M.

Run the configured operation:

```powershell
python castem_pipeline_headless.py path\to\run.ini
```

The process streams Cast3M output to the terminal, writes `castem-console.log`, and records `headless-run-report.json` in the configured working directory. A nonzero process or incomplete expected mesh manifest returns a nonzero command exit status.

## Operations and modes

- `operation = mesh` runs only mesh generation.
- `operation = fiss` runs only the configured FISS calculation.
- `operation = both` runs mesh first and starts FISS only after mesh success.
- `mode = python` uses the accelerated conformal inflated-hole fill.
- `mode = reference` uses the preserved Cast3M hole construction.

Each `holeN` entry is `center_x, center_y, radius`; any number of consecutively or non-consecutively numbered holes can be listed. At refinement 2, the documented configuration validates as 64 angular points per hole.

## Output safety

With `archive_existing_outputs = true`, fixed-name prior mesh outputs are moved into a timestamped `_previous_mesh_runs` directory before a new mesh run. With it set to `false`, the runner refuses to start if such outputs exist. It never recursively cleans the configured directory.

`open_gmsh = true` opens the merged BDF, or the volume BDF when merging is disabled, after a successful mesh run. Keep it `false` for fully unattended execution.

Paths may be absolute or relative. Relative paths are resolved from the INI file location, making a configuration portable with the repository.
