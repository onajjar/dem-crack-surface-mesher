# Structured surface generation

The enhanced workflow supports imported CSV data, self-affine spectral
synthesis, and constant planes. All three modes produce the same four numeric
matrices consumed by the preserved Cast3M readers, so hole construction,
volume extrusion, named-boundary export, BDF merge, Gmsh opening, and optional
FISS execution follow one downstream path.

## Directional self-affine model

A self-affine height field has the statistical scaling relation

```text
z(λx, λy) ~ λ^H z(x, y)
```

where `H` is the Hurst exponent. For a two-dimensional graph embedded in three
dimensions, this implementation uses

```text
D = 3 - H
```

with `0 < H < 1` and `2 < D < 3`. The user may enter either value. If an INI
supplies both, they must satisfy the relation to numerical tolerance.

The legacy isotropic two-dimensional power spectral density follows

```text
S(k) ∝ k^-(2H+2)
```

Therefore white-noise Fourier coefficients are multiplied by `k^-(H+1)`.
Leaving the directional and roll-off controls at their defaults retains this
path byte-for-byte for a given seed.

The extended model accepts `hurst_exponent_x` and `hurst_exponent_y`. In
directional Fourier coordinates, it interpolates the local exponent by squared
direction cosines:

```text
wx = qx^2 / (qx^2 + qy^2)
H(qx, qy) = Hx wx + Hy (1 - wx)
```

Optional `rolloff_wavelength_x` and `rolloff_wavelength_y` define
`k0x = 2 pi / lambda0x` and `k0y = 2 pi / lambda0y`. Both must be supplied
together. With

```text
q = sqrt((kx / k0x)^2 + (ky / k0y)^2)
```

the amplitude filter uses `max(q, 1)^-(H(q)+1)`. It is therefore flat below
the directional roll-off and self-affine above it. Blank roll-off values use
the unmodified power law. The zero-frequency coefficient is always removed.

## Height distribution

`height_distribution` accepts `gaussian`, `uniform`, `laplace`, or
`lognormal`. Gaussian synthesis uses the filtered field directly. The three
non-Gaussian options rank-map the field to deterministic target quantiles and
then recenter and normalize it. `lognormal_shape` controls the lognormal shape
parameter and must be in `(0, 3]`.

Rank mapping gives the requested discrete marginal distribution while retaining
the spatial rank structure. It does not preserve every Fourier amplitude
exactly, so generated metadata records achieved wall skewness, RMS values, wall
correlation, and aperture statistics.

## Wall construction

Two seeded spectral fields are generated for the opposing walls. Their Gaussian
precursors are coupled using the requested `wall_correlation`:

```text
gu = rho gl + sqrt(1 - rho^2) gi
```

where `gi` is an independent realization. `lower_wall_rms` and
`upper_wall_rms` set the two roughness magnitudes. The physical walls are

```text
zmin = rl - mean_aperture / 2
zmax = ru + mean_aperture / 2
opening = mean_aperture + ru - rl
```

Thus `wall_correlation = 0` produces independently rough opposing walls and a
spatially varying aperture. The legacy parallel-wall result is recovered with
correlation `1`, equal wall RMS values, a Gaussian distribution, equal
directional exponents, and blank roll-off wavelengths. `rms_height` remains as
the backward-compatible fallback for both wall RMS values.

`minimum_aperture` must be positive and below the requested mean. If an
unconstrained realization would cross that value, only the opening fluctuation
about the unchanged mid-surface is reduced. This preserves the mean aperture
and prevents intersecting or collapsed walls. The applied scale and all
achieved statistics are included in the validation/headless report.

## Constant planes

Constant mode creates regular X/Y coordinate grids and fills each Z matrix with
one value. A lower surface of `z = 0` everywhere is supported. For volume
meshing, `constant_zmax` must be strictly greater than `constant_zmin`; identical
walls would create collapsed elements and are rejected before Cast3M starts.

## Grid convention and units

- `points_x` and `points_y` are point counts, not cell counts.
- The base structured grid contains `(points_x - 1) × (points_y - 1)` cells.
- X and Y span `center ± size / 2`, including both endpoints.
- Z, wall RMS heights, roll-off wavelengths, and apertures use the same length
  unit as X and Y.
- Existing post-processing implicitly treats coordinates as metres.

## Runtime contract

Generated matrices are written to `_generated_surface_inputs` below the run
directory as headerless comma-delimited files. They are then copied to the
canonical dataset-dependent filenames required by the immutable DGIBI reader.
`--validate-only` builds and checks generated arrays in memory without writing
these files.

## Reproduction and verification

```powershell
python -B castem_pipeline_gui_scientific.py --headless examples\surfaces\fractal-hurst.ini --validate-only
python -B castem_pipeline_gui_scientific.py --headless examples\surfaces\fractal-advanced.ini --validate-only
python -B castem_pipeline_gui_scientific.py --headless examples\surfaces\fractal-hurst.ini

python -B scripts\verify_shape_interfaces.py `
  --config examples\surfaces\fractal-hurst.ini `
  --bdf _runtime\fractal-hurst-example\castem_mesh_surf_max.bdf `
  --volume _runtime\fractal-hurst-example\castem_mesh_v.bdf
```

The committed real-run evidence is summarized in
[Provisional verification](provisional-verification.md). Center/corner Jacobian
and interface checks do not replace full element-quality evaluation or validation
in the target CFD solver.

## Remaining statistical limitations

Directional exponents are blended continuously in Fourier space rather than
fitted to a measured two-dimensional PSD. Non-Gaussian rank mapping and
minimum-aperture enforcement can change the achieved spectrum, RMS values, and
Pearson wall correlation. The report exposes those achieved quantities; a
single finite realization should not be treated as an exact simultaneous match
to every target statistic.
