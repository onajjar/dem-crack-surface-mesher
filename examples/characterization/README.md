# Advanced characterization examples

These four deterministic cases use the same `SurfaceGrid` contract as the
Scientific Workbench and Cast3M mesh path:

1. `1_planar_constant`: flat parallel walls with a constant aperture.
2. `2_anisotropic_rough`: anisotropic spectral mid-surface and aperture field.
3. `3_hydraulic_bottleneck`: variable opening with one narrow high-resistance band.
4. `4_synthetic_from_characteristics`: a new realization targeted from the
   measured descriptors of case 2.

Run all cases from the repository root:

```powershell
python examples\characterization\run_examples.py
```

Each `config.json` is the complete reproducibility input. Generated CSV surfaces,
tables, reports, and PNG/PDF figures are written below each case in
`generated_output/`; that directory is intentionally ignored by Git. The
committed `expected_results.json` and `reference_summary.png` are compact
reviewed references produced by the same script.

The planar analytical acceptance values are:

- geometrical tortuosity = 1;
- aperture standard deviation = 0;
- arithmetic, cubic-mean, and path-equivalent aperture = `2e-4 m`;
- flat-surface roughness = 0; and
- Hurst exponent not estimable, with an explicit warning.

No example labels a geometrical quantity as hydraulic tortuosity. Equivalent
hydraulic aperture remains a cubic-law proxy requiring comparison with CFD.
