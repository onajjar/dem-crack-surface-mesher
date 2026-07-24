# Advanced characterization examples

These five deterministic cases use the same `SurfaceGrid` contract as the
Scientific Workbench and Cast3M mesh path:

1. `1_planar_constant`: flat parallel walls with a constant aperture.
2. `2_anisotropic_rough`: anisotropic spectral mid-surface and aperture field.
3. `3_hydraulic_bottleneck`: variable opening with one narrow high-resistance band.
4. `4_synthetic_from_characteristics`: a new realization targeted from the
   measured descriptors of case 2.
5. `5_synthetic_all_options`: bounds, contacts, anisotropy, mean-plane slopes,
   positivity, reproducible seed, and a three-member ensemble.

Read [`AUTOMATIC_ANALYSIS_GUIDE.md`](AUTOMATIC_ANALYSIS_GUIDE.md) first. It
explains why ordinary characterization has no scientific input fields, lists
everything calculated automatically, maps every output, and documents every
synthetic-only input.

Run all cases from the repository root:

```powershell
python.exe .\examples\characterization\run_examples.py
```

The first three `config.json` files describe only the known test geometry; they
do not select an aperture, direction, tortuosity, or Hurst method. Analysis is
automatic. Synthetic cases contain generation targets. Generated CSV surfaces,
tables, reports, and PNG figures are written below each case in
`generated_output/`; that directory is intentionally ignored by Git. The
committed `expected_results.json` and `reference_summary.png` are compact
reviewed references produced by the same script. Every primary case also
exports the five-field additive decomposition under
`generated_output/wavelet_decomposition/`.

The planar analytical acceptance values are:

- geometrical tortuosity = 1;
- aperture standard deviation = 0;
- arithmetic, cubic-mean, and path-equivalent aperture = `2e-4 m`;
- flat-surface roughness = 0; and
- Hurst exponent not estimable, with an explicit warning; and
- the wavelet coarse-plus-detail sum reconstructs every input field to
  floating-point precision.

No example labels a geometrical quantity as hydraulic tortuosity. Equivalent
hydraulic aperture remains a cubic-law proxy requiring comparison with CFD.
