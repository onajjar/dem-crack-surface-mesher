# Generated surface examples

These configurations generate the four matrices expected by the preserved
Cast3M programs, then use the same conformal hole and volume-meshing pipeline
as CSV input.

| Example | Surface definition |
|---|---|
| [`fractal-hurst.ini`](fractal-hurst.ini) | Self-affine surface with `H = 0.8` |
| [`fractal-dimension.ini`](fractal-dimension.ini) | Equivalent graph dimension `D = 2.2` |
| [`constant-planes.ini`](constant-planes.ini) | Lower wall `z = 0`; upper wall `z = 2e-4` |

For a two-dimensional surface graph embedded in three dimensions, this model
uses `D = 3 - H`. Its isotropic power spectral density scales as
`S(k) ∝ k^-(2H+2)`. The random field is normalized to the requested RMS height.
The upper and lower self-affine walls are parallel and separated by the mean
aperture, preventing accidental wall intersections.

The exponent determines scale dependence but not height magnitude. Therefore
`rms_height`, `mean_aperture`, and `random_seed` are explicit inputs.

Validate without launching Cast3M:

```powershell
python -B castem_pipeline_headless.py examples\surfaces\fractal-hurst.ini --validate-only
python -B castem_pipeline_headless.py examples\surfaces\fractal-dimension.ini --validate-only
python -B castem_pipeline_headless.py examples\surfaces\constant-planes.ini --validate-only
```

Remove `--validate-only` to run the complete mesh workflow. Generated CSV files
are written below each example's isolated `_runtime` directory. A planar volume
requires `constant_zmax > constant_zmin`; two identical Z values would have zero
volume and are rejected before Cast3M starts.

## Recorded real-run checks

The Hurst and constant examples were run with Cast3M 25. Both returned `0` at
error level `0`, created the combined BDF, and produced 5,180 HEXA8 cells. The
circle and rectangle interfaces were respectively `28=28` and `32=32`, with no
residual square/fill seams. All 5,180 center and 41,440 corner Jacobians were
positive and non-zero in each volume BDF.

Recheck the generated artifacts with:

```powershell
python -B scripts\verify_shape_interfaces.py --config examples\surfaces\fractal-hurst.ini --bdf _runtime\fractal-hurst-example\castem_mesh_surf_max.bdf --volume _runtime\fractal-hurst-example\castem_mesh_v.bdf
python -B scripts\verify_shape_interfaces.py --config examples\surfaces\constant-planes.ini --bdf _runtime\constant-planes-example\castem_mesh_surf_max.bdf --volume _runtime\constant-planes-example\castem_mesh_v.bdf
```

Cast3M also printed its existing signalling `IEEE_INVALID_FLAG` notice after
normal completion. The recorded topology and Jacobian checks do not establish
full mesh quality or suitability for a specific CFD solver.
