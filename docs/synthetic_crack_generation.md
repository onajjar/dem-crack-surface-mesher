# Synthetic crack generation

The synthetic generator creates a new statistically representative realization;
it does not annotate or copy the original crack.

## Model

Two deterministic Gaussian spectral fields are generated from independent
seeded white-noise realizations:

1. a mid-surface roughness field; and
2. an aperture-fluctuation field.

An anisotropic Fourier filter uses separate Hurst exponents and correlation
length scales in x and y. The zero-frequency component is removed, the field is
normalized to unit population standard deviation, and the requested RMS or
aperture standard deviation is applied.

The synthetic mid-surface can include a mean plane:

\[
z_m=z_r+a_xx+a_yy.
\]

The aperture is shifted to the requested mean, clipped to optional minimum and
maximum values, and can set the lowest ranked samples to zero to target a
contact-area fraction. With the positive-aperture constraint enabled,
negative values are clipped to zero.

The four mesh-compatible grids are reconstructed as

\[
z_{\min}=z_m-\frac{b}{2},
\qquad
z_{\max}=z_m+\frac{b}{2}.
\]

This reconstruction is symmetric in global Z to preserve the existing
rectilinear Cast3M CSV contract. The achieved local-normal aperture is measured
again during post-generation verification.

## Reproducibility and verification

The random seed plus realization index fully determines a realization.
`realizations` generates the deterministic sequence `seed + index`. After
each generation, the same characterization pipeline recalculates mean and standard
deviation of aperture, extrema, contact fraction, mid-surface RMS, Hurst fits,
correlation, tortuosity, and hydraulic proxies. Target-versus-achieved values
are written to `synthetic_surface_validation.csv`.

For one realization, the generated surface is written as:

```text
synthetic/surface_csv/xrange_generated.csv
synthetic/surface_csv/yrange_generated.csv
synthetic/surface_csv/zfit_zmin_generated.csv
synthetic/surface_csv/zfit_zmax_generated.csv
```

These files can be selected directly in CSV mode and passed through the
unchanged mesh-generation workflow.

For an ensemble, each member is isolated under
`synthetic/realization_001/`, `synthetic/realization_002/`, and so on. The
combined validation table includes a `realization` column, while the JSON
summary records every seed, CSV path, and target-versus-achieved comparison.

## GUI workflow

1. Open the embedded **3 Characterization** Workbench tab.
2. Select **Synthetic surface**.
3. Load **Planar opening**, **Anisotropic rough**, or **Bounded contact
   ensemble**, then edit only the desired generation targets.
4. Choose **Characterize only** or **Characterize and continue to mesh**.
5. Review `synthetic_surface_validation.csv` and the comparison figures before
   using the realization.

The measured-crack analysis has no editable parameters. Synthetic controls
cover resolution, size, aperture mean/deviation/bounds, roughness, X/Y Hurst,
X/Y correlation lengths, contact fraction, X/Y mean-plane slopes, positivity,
seed, and realization count. The complete option-by-option example is
[`5_synthetic_all_options`](../examples/characterization/5_synthetic_all_options/README.md).

## Limitations

The present spectral model targets second-order statistics rather than an exact
arbitrary probability distribution. Clipping changes the achieved mean,
standard deviation, spectrum, and correlation. The automatic verification is
therefore part of the method, not an optional cosmetic step. A future extension
could use iterative amplitude-adjusted Fourier transforms for simultaneous
control of a non-Gaussian marginal distribution and target spectrum.
