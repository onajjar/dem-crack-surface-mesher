# Changelog

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

[Unreleased]: https://github.com/onajjar/dem-cfd-crack-geometry-to-mesh-converter/compare/v0.1.0-baseline...HEAD
[0.1.0-baseline]: https://github.com/onajjar/dem-cfd-crack-geometry-to-mesh-converter/releases/tag/v0.1.0-baseline
