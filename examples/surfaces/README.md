# Generated surface examples

These configurations generate the four matrices expected by the preserved
Cast3M programs, then use the same conformal hole and volume-meshing pipeline
as CSV input.

| Example | Surface definition |
|---|---|
| [`fractal-hurst.ini`](fractal-hurst.ini) | Self-affine surface with `H = 0.8` |
| [`fractal-dimension.ini`](fractal-dimension.ini) | Equivalent graph dimension `D = 2.2` |
| [`fractal-advanced.ini`](fractal-advanced.ini) | Directional roll-off, lognormal, independently rough walls |
| [`constant-planes.ini`](constant-planes.ini) | Lower wall `z = 0`; upper wall `z = 2e-4` |

For a two-dimensional surface graph embedded in three dimensions, this model
uses `D = 3 - H`. The backward-compatible isotropic power spectral density
scales as `S(k) ∝ k^-(2H+2)`. The advanced model adds directional Hurst
exponents and roll-off wavelengths, four height distributions, separate wall
RMS targets, and controllable wall correlation. A positive minimum aperture
prevents intersections.

The exponent determines scale dependence but not height magnitude. Therefore
wall RMS values, aperture constraints, and `random_seed` are explicit inputs.
Every generated grid records target and achieved wall/aperture statistics.

Validate without launching Cast3M:

```powershell
python -B castem_pipeline_headless.py examples\surfaces\fractal-hurst.ini --validate-only
python -B castem_pipeline_headless.py examples\surfaces\fractal-dimension.ini --validate-only
python -B castem_pipeline_headless.py examples\surfaces\fractal-advanced.ini --validate-only
python -B castem_pipeline_headless.py examples\surfaces\constant-planes.ini --validate-only
```

Remove `--validate-only` to run the complete mesh workflow. Generated CSV files
are written below each example's isolated `_runtime` directory. A planar volume
requires `constant_zmax > constant_zmin`; two identical Z values would have zero
volume and are rejected before Cast3M starts.

## Recorded real-run checks

The legacy Hurst and constant examples were run with Cast3M 25. Both returned `0` at
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

The advanced example was also run through the source-free `python_only`
backend. It generated 21,444 nodes and 13,870 HEXA8 cells, matched the circle
and rectangle interfaces at `44=44` and `52=52`, and checked all eight Gauss
points per cell. No nonpositive Jacobian was found and the minimum scaled
Jacobian was `0.580399`. The realized opening varied from about
`1.05865e-4` to `2.99753e-4`. This current Python-only evidence is separate
from the historical Cast3M evidence above.
