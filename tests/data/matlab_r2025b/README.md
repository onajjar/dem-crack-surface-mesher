# Frozen MATLAB fitting oracle

The `expected` arrays were produced by MATLAB R2025b Update 1 and Curve Fitting
Toolbox 25.2 on Windows x86-64 on 6 September 2026. They reproduce the archived
25 August numerical arrays exactly. Python has not generated these reference
values. `provenance.json` records source, input and reference SHA-256 hashes.

The matrix contains 32 DEAP scenarios (26 surfaces and six no-surface outcomes),
160 arbitrary-point fits, and 24 paired-wall/contact cases. It includes multiple
times/components/orientations, narrow spans, duplicates, tied distances,
rank-deficient and nearly collinear points, constant predictors, extrapolation,
and contact patches. The original DEAP inputs are under `examples/deap`; three
cases use Git LFS. The fixture files total approximately 1.4 MB.

Run `python scripts/validate_matlab_fitting.py`. It verifies fixture/input
checksums, array shapes, non-finite masks, values to absolute tolerance 1e-12,
and exact final contact masks. It exits nonzero on disagreement. Real DEAP
coordinates are in metres; arbitrary synthetic fits retain their supplied
coordinate units. Do not interpret a large ill-conditioned fit as a physical
crack dimension merely because it matches MATLAB.

The synthetic contact check combines independent fits with the literal MATLAB
clamp rule. `tests/test_surface_contact_contract.py` separately exercises the
production reconstruction's overlap and outside-domain extension. DEAP cases
exercise the complete extraction, fitting, extension and contact path.

`scripts/generate_matlab_reference.m` can regenerate oracle outputs into a new
directory using the unchanged legacy functions. It does not overwrite fixtures.
Review reference changes independently before replacing any frozen array.
