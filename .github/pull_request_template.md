## Summary

Describe what changed and why.

## Validation

- [ ] `python scripts/verify_baseline.py`
- [ ] `python -m ruff check .`
- [ ] `python -m compileall -q .`
- [ ] `python -m pytest -q`
- [ ] Relevant Cast3M/Gmsh checks were run, or the limitation is documented below.

## Scientific and compatibility impact

- [ ] The immutable baseline files are unchanged.
- [ ] Generated artifacts and machine-specific paths are excluded.
- [ ] Numerical, mesh, dependency, and user-facing changes are documented.

## Additional notes

List checks that could not be run, known limitations, and any review guidance.
