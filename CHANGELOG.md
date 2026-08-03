# Changelog

## Unreleased

- Made Linux setup discover `PYTHON_BIN`, `python3`, or Conda's `python`, reject
  unsupported Python versions, and remain repository-relative; removed the
  Windows README's dependency on the optional `py` launcher.
- Added Vassaux et al. (2016) as the methodological reference for the
  beam-particle/discrete-element model underlying the DEM microcracking data.
- Added native Linux/macOS Cast3M, Gmsh, desktop-opening, GUI, headless,
  benchmark, and example launch support while preserving Windows batch
  behavior and all immutable baseline files.
- Added Linux setup/launcher scripts, Linux-and-Windows CI coverage, portable
  command tests, and an end-to-end Linux validation guide.
- Normalized merged BDF output by omitting only zero-area `CQUAD4` records with
  fewer than three distinct nodes, allowing exactly closed DEAP crack fronts
  to pass native Gmsh/CFD importer checks without changing non-zero geometry.
- Made source-free Python-only HEXA8 the Workbench default and disabled the
  Cast3M DGIBI path/browser, launcher version, and Gmsh controls until a Cast3M
  backend is selected.
- Extended meshing-time fractal synthesis with directional Hurst exponents,
  paired X/Y roll-off wavelengths, Gaussian/uniform/Laplace/lognormal
  marginals, separate lower/upper wall RMS targets, configurable wall
  correlation, independent opposing walls, variable aperture, and positive
  minimum-aperture enforcement with target-versus-achieved reporting.
- Added and fully meshed the source-free `fractal-advanced.ini` example; its
  13,870 HEXA8 cells passed all Gauss-point checks with minimum scaled Jacobian
  `0.580399`, and an independent topology audit found 110,960 positive corner
  Jacobians with no residual hole-fill seams.
- Refreshed the current Workbench stills, characterization stills, generated
  surface comparison, workflow diagram, and animated walkthrough; the demo now
  includes the embedded Characterization tab.
- Integrated the complete inlet/outlet chamber construction and conditional
  BDF exports directly into the single `source_codes/castem_tool.dgibi` mesh
  source behind the native `opti_chamb = 0/1` option.
- Reduced Python chamber handling to validation and scalar parameter patching;
  Python no longer stores or injects Cast3M chamber geometry.
- Retained the embedded chamber preset, complete `[chambers]` example,
  parameter/output reporting, named BDF/STL boundaries, and bulk Python hole
  path while removing the redundant chamber template and example DGIBI.
- Made `castem_pipeline_gui_scientific.py` the single primary GUI/headless launcher via `--headless CONFIG`, while retaining the standalone headless command for compatibility.
- Added centralized pytest/Ruff configuration, CI linting, public contribution templates, and broader generated-file exclusions for release readiness.
- Removed a dead scientific-UI assignment without changing runtime behavior.
- Replaced the legacy T13 interface GIF with the current multi-tab Scientific
  Workbench walkthrough and removed the obsolete baseline screenshot.
- Added CSV, reproducible self-affine fractal, and constant-plane surface sources behind one canonical four-grid Cast3M contract.
- Replaced the MATLAB runtime dependency for DEAP crack fitting with a Python
  quadratic LOESS implementation, explicit DEAP-fit/CSV-bypass controls, four
  application datasets, fit reports, and archived MATLAB provenance sources.
- Made boundary-BDF-to-high-precision-ASCII-STL conversion the default whenever
  STL export is selected, with Cast3M's native STL block commented in generated
  DGIBI and exactly degenerate BDF triangles reported and omitted.
- Limited manual dataset naming inputs to DEAP fitting; CSV mode now derives
  and cross-checks them from filenames, while generated modes retain their
  established disabled defaults.
- Added publisher-verified article citation guidance, GitHub-native
  `CITATION.cff` metadata, and a reusable BibTeX record for the scientific
  crack-reconstruction methodology.
- Added a one-click Scientific Workbench DEAP fitting example backed by the
  bundled `1_simple` raw-HDF5 application and its validated fit configuration.
- Added a compact, clickable publisher DOI citation below the Scientific
  Workbench so the methodological reference remains visible without competing
  with the meshing controls.
- Added an optional Python-only advanced crack-characterization stage operating
  on the shared reconstructed `SurfaceGrid`, with global-Z/local-normal
  aperture, robust statistics, directional geometrical tortuosity, cubic-law
  flow-path proxies, roughness/Hurst diagnostics, orientation/connectivity,
  anisotropic synthetic generation, publication figures, and complete exports.
- Made measured-surface characterization parameter-free in the embedded tab:
  both aperture definitions, X/Y cubic-law paths, X/Y wall and mid-surface
  tortuosity, both X/Y Hurst estimators, and all other supported descriptors
  are calculated in one run. Editable scientific controls are now limited to
  optional synthetic-surface generation.
- Bound the read-only characterization results path dynamically to
  `<working directory>/characterization`, including direct tab access and
  working-directory changes, so a launch-time path cannot write results into
  the repository root.
- Added a versioned physical-equations report covering every implemented
  characteristic, estimator, unit, assumption, reliability rule, synthetic
  equation, and output mapping. Each characterization run copies the report to
  its working-directory results as `characterization_equations.md`.
- Converted all scientific Markdown equations to GitHub-compatible `$...$` and
  `$$...$$` delimiters so inline and displayed mathematics render instead of
  appearing as literal LaTeX text.
- Added automatic reconstruction-preserving 2D wavelet decomposition for both
  crack walls, the mid-surface, and both aperture definitions. Full-resolution
  coarse and dyadic horizontal/vertical/diagonal detail surfaces, wavelength
  metadata, figures, and reconstruction errors are isolated under
  `wavelet_decomposition/`.
- Added three documented synthetic presets, an all-options ensemble example,
  and bounded plotting bins that prevent pathological memory use for nearly
  discrete bottleneck distributions. Constant and numerically degenerate
  aperture distributions are rendered as single-value markers, avoiding
  NumPy divide-by-zero warnings from zero-width density bins.
- Added a dedicated non-blocking Workbench tab, characterize-only and
  characterize-then-mesh headless operations, five validated examples,
  independent MATLAB analytical reference data, and a documented legacy
  algorithm/cleanup audit.

All notable repository-level changes are documented here. This project follows the structure of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) without claiming semantic-versioning compatibility for the preserved computational code.

## [Unreleased]

### Added

- A single scientific launcher with preflight validation, XY geometry preview, reference/bulk solver modes, streamed status, and separated mesh/FISS workflows.
- Vectorized rectilinear interpolation and complete lower/upper/mean NASTRAN hole-fill meshes imported by Cast3M with `LIRE 'NAS'`.
- Explicit geometric hole inflation controlled by `num_el_fill` and `re_fact_hole`, plus topology and orientation checks.
- A reproducible Cast3M comparison benchmark, focused tests, provisional verification report, and real BDF-based mesh comparison assets.
- A compatibility redirect from the earlier Python-hole launcher to the scientific workbench.
- Mode-aware preflight, complete documented-example loading, dirty-state tracking, mutually exclusive mesh/FISS runs, stale-output archival, and fresh-output manifest verification.
- Conformal hole-fill angular subdivision that matches each surrounding `nelem_x`/`nelem_y` edge count and removes the 1-to-2 hanging-node interface.
- A one-click scientific-workbench action for opening the generated combined or volume BDF in Gmsh.
- A no-interface INI runner covering mesh, multiple holes, exports, merge/Gmsh controls, and optional FISS execution.
- Generalized conformal holes for circles, rotated rectangles, equilateral triangles, and regular polygons, with shape-dependent GUI/INI parameters and a real four-shape Cast3M example.
- Added dynamic surface-source controls, Hurst/fractal-dimension parameterization, deterministic seeds, RMS roughness/aperture controls, constant-Z examples, real Cast3M executions, and BDF topology/Jacobian verification.
- Integrated raw DEAP HDF5 fitting into the GUI and headless runner, including
  per-run `--surface-mode`, four MATLAB-reference validations at `1e-12 m`, Git
  LFS routing for large example inputs, and comparison/report artifacts.

## [0.1.0-baseline] - 2026-07-10

### Added

- Current T13 Tkinter GUI and supporting Cast3M source files as a byte-preserved baseline.
- Existing four-file 50 × 50 CSV example input, plus verified no-hole and two-hole Cast3M runs.
- Installation, input/output, FISS, limitations, troubleshooting, and contribution documentation.
- Authentic GUI/workflow visuals and reproducible visual-generation scripts.
- SHA-256 preservation manifest and verifier.
- Non-invasive tests and GitHub Actions CI.

### Notes

- Computational logic and baseline source behavior were not changed.
- Cast3M and Gmsh remain external system dependencies.
- Large historical meshes, solver results, traces, and temporary run directories were intentionally excluded.
- This is a pre-refactor preservation release, not a claim of numerical validation or production readiness.

[Unreleased]: https://github.com/onajjar/dem-crack-surface-mesher/compare/v0.1.0-baseline...HEAD
[0.1.0-baseline]: https://github.com/onajjar/dem-crack-surface-mesher/releases/tag/v0.1.0-baseline
