# Changelog

All notable repository-level changes are documented here. This project follows the structure of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) without claiming semantic-versioning compatibility for the preserved computational code.

## [Unreleased]

No changes yet.

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
