# Contributing

Thank you for helping make this scientific workflow more reliable and reproducible.

## Baseline policy

The `v0.1.0-baseline` release is a preservation point. Changes targeting that baseline must not alter the computational behavior or bytes of:

- `castem_pipeline_gui_t13.py`
- `bpm_cfx.ico`
- any file in `source_codes/`

Run `python scripts/verify_baseline.py` before submitting a change. Behavioral refactors, numerical changes, bug fixes, or file renames should be proposed separately and must include an explanation of the scientific impact and validation evidence.

## Before opening a pull request

1. Open or reference an issue that defines the intended change and its scope.
2. Create a focused branch from the current default branch.
3. Keep generated Cast3M/Gmsh outputs, virtual environments, caches, credentials, and machine-specific paths out of the commit.
4. Add or update documentation and non-invasive tests where appropriate.
5. Run:

   ```powershell
   python scripts\verify_baseline.py
   python -m ruff check .
   python -m compileall -q .
   python -m pytest -q
   ```

6. Inspect the complete diff and explicitly identify any checks that could not be executed.

## Scientific and test evidence

Do not invent numerical results, meshes, screenshots, or performance claims. When a change affects calculations, include enough information to reproduce the comparison: software versions, input data, parameters, commands, checksums, and acceptance criteria. Keep large artifacts outside Git and link to an approved archive if one exists.

## Code and documentation

- Support Python 3.10 or newer unless a compatibility change is discussed first.
- Prefer small, reviewable changes and preserve the current Windows/Cast3M behavior until a replacement is independently validated.
- Keep user-facing instructions free of credentials and machine-specific absolute paths.
- Document external requirements such as Cast3M and Gmsh; do not silently download them from application code.
- Use clear English for new public documentation. Existing baseline comments and identifiers are preserved as-is.

Participation in this project is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Licensing note

This repository currently has no `LICENSE` file. Confirm contribution and redistribution terms with the maintainer before submitting substantial code or third-party material, particularly changes involving `source_codes/fiss.eso`.
