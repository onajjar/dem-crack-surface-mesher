# Structured surface generation

The enhanced workflow supports imported CSV data, self-affine spectral
synthesis, and constant planes. All three modes produce the same four numeric
matrices consumed by the preserved Cast3M readers, so hole construction,
volume extrusion, named-boundary export, BDF merge, Gmsh opening, and optional
FISS execution follow one downstream path.

## Self-affine model

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

The isotropic two-dimensional power spectral density follows

```text
S(k) ∝ k^-(2H+2)
```

Therefore white-noise Fourier coefficients are multiplied by
`k^-(H+1)`. The zero-frequency coefficient is removed, the inverse transform
is centered at zero, and the field is normalized to the requested RMS height.
An integer seed initializes NumPy's random generator and makes every matrix
reproducible on the supported NumPy path.

## Wall construction

The synthesized field represents the mean surface `zm`. The crack walls are

```text
zmin = zm - mean_aperture / 2
zmax = zm + mean_aperture / 2
```

This creates parallel rough walls with constant positive aperture. It avoids
wall intersections and makes the existing Cast3M extrusion well defined.
`rms_height` is essential: `H` or `D` controls scale dependence but contains no
absolute vertical magnitude.

The current model deliberately does not generate two statistically independent
walls or a spatially varying aperture. It also has no anisotropy, spectral
roll-off/cut-off controls, or non-Gaussian height distribution.

## Constant planes

Constant mode creates regular X/Y coordinate grids and fills each Z matrix with
one value. A lower surface of `z = 0` everywhere is supported. For volume
meshing, `constant_zmax` must be strictly greater than `constant_zmin`; identical
walls would create collapsed elements and are rejected before Cast3M starts.

## Grid convention and units

- `points_x` and `points_y` are point counts, not cell counts.
- The base structured grid contains `(points_x - 1) × (points_y - 1)` cells.
- X and Y span `center ± size / 2`, including both endpoints.
- Z, RMS height, and aperture use the same length unit as X and Y.
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
