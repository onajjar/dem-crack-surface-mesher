# DEAP application examples

These four application packages reproduce the parameter sets used to validate
the Python replacement for the MATLAB crack-surface fit:

| Case | Crack plane | Time step | LOESS span | Grid | Opening threshold |
|---|---:|---:|---:|---:|---:|
| `1_simple` | XY | 10 | 0.60 | 20 | 1e-5 m |
| `2_large` | ZX | 100 | 0.10 | 20 | 1e-5 m |
| `3_rebar` | YZ | 50 | 0.05 | 20 | 2e-5 m |
| `4_brazilian` | YZ | 85 | 0.05 | 50 | 1e-6 m |

Each case contains:

- `results/deap_post.h5` and `results/deap_output.h5`: raw discrete-simulation
  results read by the Python fitter;
- `results/input.boundary` when the DEAP case supplied it (the Brazilian case
  records its bounding box in `run.ini` instead);
- `reference/*.csv`: archived MATLAB-generated matrices used only for
  comparison and for the CSV-bypass mode; and
- `run.ini`: a complete headless mesh configuration whose working directory is
  the `results` folder.

The large HDF5 files for cases 2–4 are stored with Git LFS. After cloning, run
`git lfs install` and `git lfs pull` before fitting those cases.

## Choose fitting or existing CSVs

The selection is explicit and can be made without editing the case file:

```powershell
# Fit raw DEAP results in Python, then validate the mesh configuration.
python castem_pipeline_headless.py examples\deap\1_simple\run.ini `
  --surface-mode deap --validate-only

# Bypass fitting and use the archived CSVs, then validate the same configuration.
python castem_pipeline_headless.py examples\deap\1_simple\run.ini `
  --surface-mode csv --validate-only
```

Omit `--validate-only` to run Cast3M and generate the mesh. Alternatively,
change `mode = deap` to `mode = csv` in that case's `[surface]` section. The
graphical workbench offers the equivalent `Fit DEAP results (Python)` and
`CSV files` choices.

Generated CSVs, fit reports, Cast3M programs, logs, and meshes stay in the case
working directory and are ignored by Git.
