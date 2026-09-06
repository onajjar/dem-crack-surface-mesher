# Python DEAP crack-surface fitting

The converter can now start from raw DEAP discrete-simulation results without
MATLAB. It retains the same four-matrix contract consumed by the preserved
Cast3M meshing backend:

- `xrange`: first surface coordinate;
- `yrange`: second surface coordinate;
- `zfit_zmin`: lower fitted crack face; and
- `zfit_zmax`: upper fitted crack face.

## Runtime selection

Use one of two modes for each run:

- `deap`: read `deap_post.h5` and `deap_output.h5` from the working directory,
  fit both crack faces in Python, write the four generated CSV matrices, and
  continue into Cast3M;
- `csv`: skip HDF5 extraction and fitting, read the four paths under `[files]`,
  and continue directly into Cast3M.

The headless override is explicit:

```powershell
python castem_pipeline_headless.py CASE\run.ini --surface-mode deap
python castem_pipeline_headless.py CASE\run.ini --surface-mode csv
```

`fit` and `python_fit` are aliases for `deap`. The `[surface] mode` value is used
when the command-line override is omitted. For a non-destructive preflight, add
`--validate-only`.

In the graphical workbench, select `Fit DEAP results (Python)` or `CSV files`.
The working-directory field is both the DEAP input location and the run-output
location. A six-value `Xmin Xmax Ymin Ymax Zmin Zmax` bounding box is needed
only when `input.boundary` is absent.

Each fitted run writes `_generated_surface_inputs/deap-fit-report.json`. The
headless run report also embeds the algorithm, selected component, number of
connected crack nodes, parameter values, grid shape, and raw input byte sizes.

The archived MATLAB CSV names encode the opening threshold with the legacy
`1e9` scale, while the preserved Cast3M template's canonical runtime names use
`1e6`. The converter therefore treats `[files]` names as arbitrary source paths
and copies either fitted or existing matrices to the Cast3M-compatible names;
the numeric threshold itself is not changed.

## Why generic LOWESS libraries did not match

The MATLAB code uses a two-predictor quadratic `loess` surface, rather than a
one-dimensional LOWESS curve. The Python port reproduces the observed MATLAB
behavior needed by the four applications:

- predictor centering and standard-deviation scaling;
- Euclidean nearest-neighbor neighborhoods with the span converted to a point
  count;
- a local quadratic basis (`1`, `x`, `y`, `x²`, `y²`, `xy`);
- tricube distance weights multiplied by normalized crack-opening weights;
- the legacy convex-hull duplication/order convention; and
- the legacy grid extension and nonnegative-opening rules.

The implementation is in `deap_crack_surface.py`; integration into the common
CSV/synthetic surface abstraction is in `surface_generation.py`.

## Verification

### Extended fitting and contact audit (September 2026)

Use `python scripts/validate_matlab_fitting.py` for the 216-case frozen MATLAB
R2025b oracle matrix. Use `--groups arbitrary contact` when the large DEAP LFS
inputs are not present. This validator fails on numerical or contact-mask
disagreement and records the operating system, backend and source hashes.

The port uses the reference-validated oneMKL LAPACK through `matlab_lapack.py`,
including when NumPy and SciPy were installed from standard pip wheels. Runtime
requirements install `mkl==2023.1.0` on Windows/Linux x86-64. A Conda installation
can provide the runtime from its own `Library/bin` or `lib` directory. Fitting
fails explicitly if the runtime is unavailable; CSV/synthetic surface modes
and meshing load without it. Run the frozen fixtures on a new CPU/runtime before
claiming equivalence: matching one MATLAB release is not a universal guarantee.

This backend choice is necessary: a standard OpenBLAS SciPy wheel changed
ill-conditioned wall fits and two synthetic contact decisions in the audit.
Using the same LAPACK backend restored the comparison on the tested Windows
environments. Native Linux evidence is produced by the CI jobs, including all
32 real DEAP scenarios; check the artifact for the commit you are using.

Contact follows the executable MATLAB code, including where a MATLAB comment
incorrectly says "clamp to opmin": negative fitted aperture is set to **zero**,
the lower wall is retained, and the upper wall is rebuilt from it. Outside the
data bounding rectangle the lower wall is extended and the aperture is zero.
No positive minimum aperture is inserted. Generated fit metadata records the
number of raw overlaps and closed points. Span zero uses eight neighbours and
is accepted by the headless pipeline.

The current Python-only HEXA8 volume mesher requires positive aperture at every
grid point. It cannot represent touching walls; `--validate-only` now reports
that limitation before execution. Fitting/exporting/characterizing a contact
surface remains valid. Do not open contact patches artificially to bypass the
restriction: that changes the geometry and its flow paths.

See [the fixture provenance and reproduction instructions](../tests/data/matlab_r2025b/README.md).

### Earlier four archived CSV comparisons

Run the complete four-case check with:

```powershell
python scripts\validate_deap_examples.py
```

The acceptance criterion is an absolute error no greater than `1e-12 m` for
every X, Y, lower-face, and upper-face value, with all values finite and every
opening nonnegative. All four integrated cases pass. The largest observed face
error is `4.55e-15 m` in `4_brazilian`; all other cases are below `1.67e-15 m`.
Both the DEAP-fit and existing-CSV configuration paths are validated.

The `1_simple` application was also run end to end in both modes with Cast3M
2025.0. Both processes returned `0`, stopped at Cast3M error level `0`, reported
no missing mesh outputs, and produced byte-identical 439,730-byte combined
BDFs (SHA-256
`97b5a46f850d9557ae9b4aae2053f10178af7fc6e852c16df8367e8802ea604c`).
The BDF contains 2,399 `GRID`, 722 `CHEXA`, and 874 `CQUAD4` cards. The complete
sanitized evidence is in
[`validation/deap-simple-castem-integration.json`](validation/deap-simple-castem-integration.json).
Gmsh 4.15.0 also accepted the combined BDF with `-check -nopopup` and returned
`0`.

The complete values, runtime versions, input/reference SHA-256 hashes, and
per-case physical checks are recorded in
[`validation/deap-surface-report.json`](validation/deap-surface-report.json).

![Python fit and MATLAB reference comparison](assets/deap-surface-comparison.png)

The exact comparison figure and report produced during the preceding standalone
phase are also preserved as
[`deap-surface-comparison-standalone.png`](assets/deap-surface-comparison-standalone.png)
and
[`deap-surface-standalone-report.json`](validation/deap-surface-standalone-report.json).
Their SHA-256 hashes match the files in the original
`python_surface_reconstruction/validation` folder.

The references are archived MATLAB-generated CSVs. The validator does not call
MATLAB. The original `.m` files remain available under `legacy/matlab` solely
for provenance.
