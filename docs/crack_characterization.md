# Advanced crack characterization

## Scope and data contract

Characterization consumes the same validated `SurfaceGrid` that is subsequently
written to the four Cast3M CSV matrices. A grid contains global `x` and `y`
coordinates and point-aligned lower (`zmin`) and upper (`zmax`) wall heights.
The complete equation-by-equation definition, units, discrete estimators, and
output map are provided in the
[physical equations report](CHARACTERIZATION_PHYSICAL_EQUATIONS.md).
The mid-surface is

$$
z_m(x,y)=\frac{z_{\max}(x,y)+z_{\min}(x,y)}{2}.
$$

Input values are never rescaled. The Workbench reports its reconstructed
coordinates in metres. The current mesh contract is a rectilinear
height graph $z=f(x,y)$; arbitrary unstructured or overhanging walls require
a future mesh-to-mesh distance implementation.

Preprocessing verifies matching shapes, finite coordinates, unique monotonic
axes, wall validity, and a minimum 3 × 3 resolution. Descending axes are
reordered consistently. Missing wall heights remain explicitly excluded
samples. Negative openings are counted and rejected. No invalid sample is
silently removed from the reported counts.

## Coordinate and direction definitions

The embedded Workbench analysis evaluates global X and global Y automatically.
No direction selection is required and Z is not offered because the current
crack is represented as a height graph over the X/Y plane. Axis-aligned
profiles use the original nonuniform physical coordinates.

## Aperture definitions

### Global-Z aperture

$$
b_z(x,y)=z_{\max}(x,y)-z_{\min}(x,y).
$$

This is the only global point-paired direction directly available from the
existing height-grid contract.

### Local-normal aperture

The preferred geometrical aperture is the paired wall separation projected onto
the upward unit normal of the mid-surface:

$$
\mathbf n_m =
\frac{(-\partial z_m/\partial x,-\partial z_m/\partial y,1)}
{\sqrt{1+(\partial z_m/\partial x)^2+(\partial z_m/\partial y)^2}},
\qquad
b_n=(0,0,b_z)\cdot\mathbf n_m.
$$

Second-order finite differences use the physical x/y axes; boundaries use
second-order one-sided differences. The automatic Workbench policy applies no
smoothing before the normal estimate. Because the
walls are point-aligned, this is a point-pair projection rather than a ray
intersection with the opposing wall. That distinction is recorded in every
report.

## Aperture statistics

For valid values $b_i$, the implementation reports sample counts, zero and
negative counts, closed/invalid sample and projected-area fractions, minimum,
maximum, range, mean, median, variance, population standard deviation,
coefficient of variation, RMS, skewness, excess kurtosis, interquartile range,
median absolute deviation, robust standard deviation $1.4826\,\mathrm{MAD}$,
and percentiles 1, 5, 10, 25, 50, 75, 90, 95, and 99.

Geometric and harmonic means are reported only when every valid aperture is
strictly positive. Spatial descriptors include the mean within-profile
standard deviation and the standard deviation of profile means in both grid
directions.

Projected-area node weights are trapezoidal control widths:

$$
\bar b_A=\frac{\sum_i A_i b_i}{\sum_i A_i}.
$$

Actual mid-surface-area weights multiply $A_i$ by
$\sqrt{1+z_{m,x}^2+z_{m,y}^2}$. Projected-area and actual-area quantities have
different output names and are never mixed.

## Cubic and hydraulic-equivalent apertures

The global cubic mean is

$$
b_{\mathrm{cubic}}=
\left(\frac{1}{N}\sum_i b_i^3\right)^{1/3},
$$

and its projected-area-weighted form is

$$
b_{\mathrm{cubic},A}=
\left(\frac{\sum_i A_i b_i^3}{\sum_i A_i}\right)^{1/3}.
$$

These are global conductance proxies, not series-flow equivalents.

For every flow-parallel path $j$, trapezoidal integration evaluates the
series-resistance equivalent:

$$
b_{\mathrm{eq},j}=
\left[
\frac{\sum_k\Delta s_k\left(b_k^{-3}+b_{k+1}^{-3}\right)/2}
{\sum_k\Delta s_k}
\right]^{-1/3}.
$$

Any path containing an opening at or below the configured cutoff has infinite
normalized resistance and zero equivalent aperture. Paths are combined in
parallel with projected transverse control widths $w_j$:

$$
b_{\mathrm{eq,global}}=
\left(\frac{\sum_j w_j b_{\mathrm{eq},j}^3}
{\sum_j w_j}\right)^{1/3}.
$$

Every path, its width, projected length, normalized resistance, closure state,
and equivalent aperture is exported. The largest- and smallest-resistance paths
are identified. These quantities assume local laminar cubic-law conductance and
are explicitly labeled hydraulic proxies requiring CFD validation.

## Geometrical tortuosity

For a sampled wall or mid-surface profile,

$$
\tau_g=\frac{\sum_k\sqrt{\Delta s_k^2+\Delta z_k^2}}
{\sum_k|\Delta s_k|}.
$$

Lower-wall, upper-wall, and mid-surface values are calculated automatically
along global X and global Y. Tables include each profile and summary mean,
median, extrema, standard deviation, and percentiles. The software deliberately
does not call this hydraulic tortuosity.

## Roughness and Hurst analysis

A least-squares plane is removed before amplitude statistics. Reported wall and
mid-surface metrics include arithmetic roughness $R_a$, RMS roughness $R_q$,
peak-to-valley height, height standard deviation, x/y slope standard deviations,
mean slope magnitude, directional autocorrelation lengths, and a correlation
anisotropy ratio.

Two Hurst estimators are run automatically in both X and Y:

1. **Second-order structure function.** The RMS increment follows
   $\sqrt{\langle[z(s+\ell)-z(s)]^2\rangle}\propto\ell^H$.
2. **One-dimensional profile PSD.** For a self-affine profile,
   $S(k)\propto k^{-(2H+1)}$, so $H=(-m-1)/2$ for fitted log-log slope $m$.

Each fit records its scale range, number of points, slope, intercept, $R^2$,
profile-bootstrap 95% confidence interval, and a reliability flag. Fits are
warned when they span less than half a decade, have $R^2<0.90$, yield
$H\notin[0,1]$, or contain too few/nonvarying values. A flat surface therefore
reports no meaningful H rather than an invented value.

For a profile, $D_p=2-H$. For an isotropic two-dimensional self-affine
surface graph, $D_s=3-H$. Both are labeled separately; a directional profile
estimate does not by itself prove isotropic surface fractality.

## Additional geometry

The report includes projected area, upper/lower/mid actual areas, surface-area
ratio, projected crack volume, least-squares crack-plane slopes and normal,
normal-vector dispersion, four-neighbor open-region connectivity, disconnected
region extents, aperture-gradient statistics, minimum-aperture coordinates,
the integral of $b^3$, and conductance normalized by smooth parallel plates
at the arithmetic mean opening.

## Additive wavelet-scale representation

The lower wall, upper wall, mid-surface, global-Z aperture, and local-normal
aperture are decomposed automatically with a two-dimensional `db2` discrete
wavelet transform. The folder `wavelet_decomposition/` contains a coarse
full-resolution surface and full-resolution horizontal, vertical, diagonal,
and combined detail surfaces at every supported dyadic level, up to five
levels.

For every field $Z$, the exported components satisfy

$$
Z=A_J+\sum_{j=1}^{J}D_j
$$

to recorded floating-point reconstruction tolerance. `metadata.json`,
`reconstruction_error.csv`, and `wavelet_decomposition.csv` record the wavelet,
boundary policy, approximate physical wavelength bands, component amplitudes,
and reconstruction errors. Complete equations and limitations are given in
[Section 21 of the physical equations report](CHARACTERIZATION_PHYSICAL_EQUATIONS.md#21-additive-two-dimensional-wavelet-decomposition).
Nested synthetic-validation realizations retain the scalar wavelet table and
summary but do not duplicate the full-resolution component file tree.

## Outputs

Every characterization run writes:

- `characterization_summary.json`
- `characterization_summary.csv`
- `aperture_statistics.csv`
- `directional_tortuosity.csv`
- `flow_path_equivalent_aperture.csv`
- `hurst_analysis.csv`
- `roughness_statistics.csv`
- `wavelet_decomposition.csv`
- `surface_orientation_statistics.csv`
- `synthetic_surface_validation.csv`
- `characterization_report.md`
- `characterization_equations.md`
- `wavelet_decomposition/`

In the Workbench, these artifacts are always placed below
`<selected working directory>/characterization`. Synthetic ensembles remain
below that folder under `synthetic/`.

The embedded Workbench generates PNG figures for the wall geometry,
aperture/PDF/CDF/resistance maps, flow-path equivalents, tortuosity
distribution, Hurst diagnostics, slope field, 2D autocorrelation, and additive
wavelet components.

The headless compatibility API still accepts explicit configuration values for
older INI files, but the interactive Characterization tab does not expose or
require them.

## Known limitations

- Walls must remain single-valued rectilinear height graphs on one matching grid.
- Local-normal aperture is paired-point projection, not shortest-wall distance.
- Oblique profiles require interpolation and may contain fewer boundary samples.
- Connectivity is grid-based and does not replace a three-dimensional flow solve.
- The cubic law neglects inertia, compressibility, contact deformation, and
  unresolved sub-grid roughness.
- Directional H estimates on BPM surfaces can be unreliable; warnings and plots
  must be reviewed rather than using H alone.
- Wavelet detail surfaces are signed scale components, not separate physical
  crack openings. Physical wavelength labels are approximate on nonuniform
  grids, and full-resolution component exports require additional storage.
