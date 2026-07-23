# Advanced crack characterization implementation report

## Architecture

The feature is additive and operates on `surface_generation.SurfaceGrid`, the
same object used by DEAP fitting, CSV loading, generated surfaces, CSV
materialization, and Cast3M meshing.

```text
SurfaceSource
  -> SurfaceGrid
  -> optional crack_characterization package
  -> unchanged write_surface_grid / Cast3M path
```

Scientific calculations live in `crack_characterization/`; the GUI only
collects settings and launches a background worker. The headless runner accepts
`characterize` and `characterize_and_mesh` operations and an optional
`[characterization]` section. Existing files with no section retain direct
meshing behavior.

The interactive workflow has one launcher and one application window:

```powershell
python.exe .\castem_pipeline_gui_scientific.py
```

No second Python program, MATLAB process, or characterization window is
required. Cast3M and Gmsh remain external tools only for mesh generation and
mesh viewing.

## Package responsibilities

| Module | Responsibility |
|---|---|
| `model.py` | typed settings, prepared data, Hurst diagnostics, result model |
| `validation.py` | coordinate/grid/wall/NaN/negative-opening checks |
| `geometry.py` | normals, areas, plane orientation, connectivity |
| `aperture.py` | global-Z and local-normal aperture definitions |
| `statistics.py` | descriptive, robust, spatial, and area-weighted statistics |
| `flow_metrics.py` | global-vector projection, profiles, series/parallel cubic law, tortuosity |
| `roughness.py` | roughness, slopes, correlation, structure-function and PSD Hurst fits |
| `synthetic_surface.py` | seeded anisotropic spectral synthesis |
| `visualization.py` | physical-unit publication figures |
| `export.py` | required JSON/CSV files and Markdown report |
| `pipeline.py` | cancellable orchestration and post-generation verification |

## File inventory

Created:

- `characterization_gui.py`;
- the 12 modules in `crack_characterization/`;
- `docs/crack_characterization.md`,
  `docs/synthetic_crack_generation.md`, and this report;
- `docs/assets/advanced-crack-characterization.png`;
- `docs/validation/matlab-characterization-reference.json`;
- `examples/characterization/` with four reference examples, a headless INI,
  and a deterministic runner;
- `legacy/matlab/validation_cases/characterization_reference.m`;
- `scripts/capture_characterization_ui.py`;
- `tests/test_crack_characterization.py` and
  `tests/test_matlab_characterization_reference.py`; and
- `legacy/matlab/Crack_Analysis_MATLAB/README.md`.

Modified:

- the Scientific Workbench and headless runner;
- README, changelog, workflow, Workbench/headless guides, and example index;
- `examples/scientific-run.ini`, `.gitignore`, and `pyproject.toml`; and
- headless integration tests.

The large reviewed MATLAB archive is ignored except for its audit README. It
remains present locally and was not rewritten.

## GUI workflow

The **Run & results** tab contains an explicit
**Perform advanced crack characterization before meshing** switch and a
single embedded **Characterization** tab. Its internal tabs separate input
definitions, synthesis, and results. It provides tooltips, validation, unit
metadata, settings save/load, progress, cancellation, characterize-only, and
characterize-then-mesh actions. Work runs on a background thread and communicates
with Tk through a queue, so the main interface remains responsive.

## Scientific definitions

- Global-Z aperture is `z_upper - z_lower` at matching structured samples.
- Preferred local-normal aperture projects the paired wall separation onto
  finite-difference mid-surface normals, optionally estimated after Gaussian
  smoothing in grid-point units.
- Arithmetic, harmonic, geometric, RMS, cubic, projected-area cubic, robust,
  percentile, line-profile, and surface-area-weighted statistics retain the
  physical input unit.
- Path-equivalent aperture integrates trapezoidal `1 / b^3` resistance in
  series and combines path conductances in parallel with transverse control
  widths.
- Geometrical tortuosity is profile arc length divided by projected length. It
  is evaluated for lower, upper, and mid surfaces along flow, transverse, X,
  Y, and a selected projected Z/custom direction.
- Roughness is evaluated after least-squares plane removal. Directional Hurst
  fits use a second-order structure function and a one-dimensional profile
  PSD, each with scale range, point count, R², bootstrap interval, and a
  reliability flag.
- Area, void volume, contact, connectivity, gradients, orientation, normal
  dispersion, autocorrelation, bottleneck, and cubic-conductance quantities
  are geometrical metrics or explicitly labeled hydraulic proxies.

Complete formulas, weighting rules, units, and caveats are in
`docs/crack_characterization.md`.

## Validation

Automated analytical cases cover:

1. parallel planar constant aperture;
2. inclined planar local-normal aperture;
3. sinusoidal mid-surface;
4. varying-aperture series resistance;
5. a strong bottleneck;
6. zero-aperture closure;
7. nonuniform sampling;
8. X and Y flow;
9. custom oblique flow;
10. invalid normal Z flow; and
11. deterministic anisotropic synthesis;
12. multi-realization synthesis and distinct seeds; and
13. embedded-panel and headless compatibility.

MATLAB R2025b independently evaluated the planar and varying-aperture formulas
in `legacy/matlab/validation_cases/characterization_reference.m`. Its committed
JSON result is regression-tested against Python. The comparison validates the
definitions and numerical integration, not the ambiguous legacy PSD workflow.

The MATLAB reference reports a planar aperture, cubic mean, and equivalent
aperture of approximately `2.0e-4`, with tortuosity `1`. For the independent
varying-aperture channel it reports an equivalent aperture of
`1.6496090588974822e-4` and a global cubic mean of
`2.1639677110463963e-4`. Python regression tests reproduce these reference
values.

Final verification on Windows/Python 3.13:

```text
Ruff:  passed
Pytest: 72 passed
Protected baseline: 6/6 hashes match
Four characterization examples: passed
Single-launcher headless characterize-only run: passed
Embedded Workbench tab capture: passed at 1440 x 900
```

## Legacy MATLAB disposition

The review is documented in
`legacy/matlab/Crack_Analysis_MATLAB/README.md`. Useful formula concepts were
rewritten and tested rather than copied. In particular:

- geometrical profile tortuosity was retained with physical coordinate
  differences and corrected point-count handling;
- roughness amplitudes were retained after explicit plane detrending;
- the self-affine spectral concept was retained with deterministic seeds;
- Hurst estimation was replaced by two directional methods with scale, R²,
  sample-count, confidence, and reliability diagnostics;
- the legacy inverse-gradient “autocorrelation length” was rejected;
- the legacy automatic maximum-R² q-range search was rejected because it can
  select a spuriously short fit;
- the equal-pixel and fixed-bin radial PSD implementation remains an archived
  reference, not active runtime code.

Only two generated Python bytecode directories and four MATLAB autosave files
were removed. Large raw measurement data, figures, MAT files, and scientifically
useful scripts are retained locally and are not added to Git merely to satisfy
repository layout aesthetics.

Removed files were regenerable caches or editor autosaves:
`artificial_surf/main1.asv`, `Tailhan_2023/Tailhan_crack.asv`,
`user_function/calculateRoughnessAndTortuosity.asv`,
`user_function/correctDEAPMatrices.asv`, and two `__pycache__` directories.
No scientific source, measured data, figure, MAT file, presentation, or
license was removed.

## Examples and outputs

Four complete deterministic examples are under
`examples/characterization/`. Each includes configuration, expected results,
and a compact summary figure; the runner regenerates full CSV inputs, reports,
tables, and PNG/PDF figures in ignored `generated_output/` directories.

The machine-readable output contract includes
`characterization_summary.json`, `characterization_summary.csv`,
`aperture_statistics.csv`, `directional_tortuosity.csv`,
`flow_path_equivalent_aperture.csv`, `hurst_analysis.csv`,
`roughness_statistics.csv`, `surface_orientation_statistics.csv`, and
`synthetic_surface_validation.csv`, plus a Markdown report and publication
figures. Synthetic ensembles use
`synthetic/realization_001/`, `realization_002/`, and so on.

## Backward compatibility

- Characterization defaults to disabled.
- The immutable T13 and `source_codes` hashes are not changed.
- Existing GUI reconstruction, direct mesh, FISS, hole, STL, CSV, DEAP,
  fractal, and planar paths remain available.
- Existing INI files without characterization sections continue to parse.
- Synthetic CSV output uses the same four-grid contract as all mesh inputs.
- The complete optional stage is contained in the existing Workbench window;
  direct reconstruction-to-mesh behavior remains the default.

## Known limitations and future work

- General unstructured/overhanging wall-to-wall aperture requires a surface
  intersection or closest-point algorithm.
- Exact arbitrary marginal-distribution synthesis would benefit from iterative
  amplitude-adjusted Fourier synthesis.
- Three-dimensional open-region percolation and flow tortuosity require CFD or
  pore-network solutions.
- Scaling fits on short or BPM-smoothed grids frequently remain unreliable;
  the software reports this rather than forcing a physical H.
- A future validated comparison can add measured optical surfaces without
  placing the supplied ~1.1 GiB MATLAB analysis bundle in Git.

Recommended future work is a closest-surface local-normal intersection method
for overhanging walls, iterative amplitude-adjusted Fourier synthesis for
non-Gaussian target distributions, measured-surface validation, and
CFD/pore-network comparison of the reported cubic-law proxies.
