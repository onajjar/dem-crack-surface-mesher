# Automatic characterization guide

## What you enter

For an existing reconstructed crack, you enter **no scientific
characterization parameters**. Select or reconstruct the crack in
**1 Geometry & inputs**, then open **3 Characterization** and press
**Characterize only** or **Characterize and continue to mesh**.

The program uses the same `SurfaceGrid` already prepared for meshing. It does
not ask which aperture, direction, tortuosity, or Hurst method to calculate
because it calculates every supported, meaningful X/Y result.

All results are stored automatically in
`<selected working directory>/characterization`; there is no separate output
directory to enter in the Characterization tab.

The only editable scientific parameters in the Characterization tab belong to
the optional generation of a **new synthetic crack**.

## What is always calculated

### 1. Both opening definitions

- **Global-Z aperture** is `zmax - zmin` at matching X/Y points.
- **Local-normal aperture** projects that paired separation onto the
  mid-surface normal. This is the preferred geometrical opening for inclined or
  rough cracks.

For both definitions, `aperture_statistics.csv` reports all sample counts,
closed/negative fractions, mean, median, extrema, range, variance, standard
deviation, coefficient of variation, RMS, geometric/harmonic means,
percentiles, skewness, kurtosis, IQR, MAD, robust deviation, spatial
deviations, area-weighted means, cubic mean, and area-weighted cubic mean.

Why report both? They are equal for a horizontal crack. On an inclined or
rough surface, global-Z is the vertical separation, while local-normal is the
opening relative to the crack geometry.

### 2. Hydraulic aperture in X and Y

For each aperture definition, the program evaluates paths in global **X** and
global **Y**. Every path integrates the local `1/b³` series resistance, then
parallel path conductances are combined with physical transverse widths.

This produces four automatic combinations:

| Aperture | Direction |
|---|---|
| Global Z | X |
| Global Z | Y |
| Local normal | X |
| Local normal | Y |

They are geometrical cubic-law proxies, not CFD solutions.
`flow_path_equivalent_aperture.csv` records every path and
`characterization_summary.json` records each global equivalent.

### 3. Geometrical tortuosity in X and Y

`directional_tortuosity.csv` contains X and Y profile-length/projected-length
ratios for:

- the lower crack wall;
- the upper crack wall; and
- the crack mid-surface.

No Z direction is requested because the current crack representation is a
single-valued height field over X/Y. This quantity is deliberately named
**geometrical tortuosity**, not hydraulic tortuosity.

### 4. Hurst estimation in X and Y

For the lower wall, upper wall, and mid-surface, the program automatically runs
both:

- second-order structure-function fitting; and
- one-dimensional profile power-spectral-density fitting.

Each X/Y fit exports the estimated H, slope, intercept, scale range, number of
points, R², deterministic 95% bootstrap interval, reliability flag, warning,
and profile/surface fractal-dimension conventions. A flat or insufficiently
resolved surface correctly reports that H is not estimable.

### 5. Everything else

The same run also calculates roughness amplitudes, slopes, surface areas,
surface-area ratio, crack volume, contact and invalid fractions, crack-plane
orientation, local-normal dispersion, connectivity, disconnected-region
sizes, aperture gradients, bottleneck coordinates, autocorrelation,
correlation lengths, anisotropy ratio, and normalized `b³` conductance.

## Fixed automatic policy

The interface no longer asks for numerical-analysis tuning. The documented
policy is:

- reconstructed coordinates are used without rescaling and reported in metres;
- X and Y are always evaluated;
- local normals use unsmoothed physical-axis finite differences;
- aperture at or below `1e-12 m` is hydraulically closed;
- negative wall separation is rejected and invalid samples are reported;
- Hurst scales start at one sample and stop at 25% of the profile length; and
- 100 deterministic profile-bootstrap resamples quantify H uncertainty.

The JSON report stores these values for reproducibility.

## Example matrix

| Example | What it verifies | Expected interpretation |
|---|---|---|
| `1_planar_constant` | Both apertures, X/Y resistance, X/Y tortuosity, flat H behavior | Both openings and all equivalent apertures equal `2e-4 m`; tortuosity is 1; H is not estimable |
| `2_anisotropic_rough` | X/Y roughness, Hurst, correlation, directional resistance | X and Y diagnostics differ; reliability warnings determine whether H may be interpreted |
| `3_hydraulic_bottleneck` | Direction-sensitive series resistance | X paths cross the narrow band and show a stronger conductance reduction than Y paths |
| `4_synthetic_from_characteristics` | Generate from measured descriptors and verify again | Target and achieved values are compared rather than assumed equal |
| `5_synthetic_all_options` | Every editable synthetic option and three realizations | Bounds/contact alter achieved statistics; each seed is exported and re-characterized |

Run all examples:

```powershell
python.exe .\examples\characterization\run_examples.py
```

The committed `expected_results.json` and `reference_summary.png` files are
compact reviewed references. Complete regenerated CSVs, reports, validation
tables, and figures are written to ignored `generated_output` directories.

## Synthetic inputs only

Synthetic inputs describe a new realization, not the measured crack analysis:

| Input | Purpose |
|---|---|
| Grid points X/Y | Matrix resolution |
| Size X/Y | Physical dimensions |
| Mean aperture | Target average separation |
| Aperture standard deviation | Target opening variability |
| Mid-surface RMS roughness | Target roughness amplitude after detrending |
| Hurst X/Y | Directional spectral scaling targets |
| Correlation length X/Y | Directional spectral length scales; blank uses one quarter of the size |
| Minimum/maximum aperture | Optional clipping bounds |
| Contact-area fraction | Lowest ranked openings forced to zero |
| Mean-plane slopes X/Y | Inclination of the new synthetic mid-plane |
| Enforce non-negative aperture | Prevent negative wall separation |
| Random seed | Exact reproducibility |
| Number of realizations | Independent ensemble size using `seed + index` |

Use the three buttons in the Synthetic surface tab to load complete documented
presets. The **Bounded contact ensemble** preset exercises every input.
