# Physical equations and numerical estimators for crack characterization

## 1. Purpose and scientific scope

This report defines every crack characteristic calculated by the Python
characterization pipeline. It records:

- the physical or statistical definition;
- the discrete numerical estimator used by the software;
- the units and output name;
- the assumptions required for interpretation; and
- the distinction between geometrical descriptors and hydraulic proxies.

The equations correspond to the implementation in `crack_characterization/`
as of 24 July 2026. They apply to the same structured crack surface passed to
the Cast3M meshing workflow. No coordinate or opening is rescaled during
characterization.

The reconstruction methodology should be cited as:

> O. Najjar, T. Heitz, C. Oliver-Leblond, J.-L. Tailhan, G. Rastiello, and
> F. Ragueneau, “Three-dimensional crack reconstruction from Beam–Particle
> Model for CFD-based leakage assessment,” *Nuclear Engineering and Design*,
> vol. 448, 114718, 2026.
> [doi:10.1016/j.nucengdes.2025.114718](https://doi.org/10.1016/j.nucengdes.2025.114718)

The present report documents the software estimators. It does not turn a
geometrical cubic-law proxy into a validated leakage prediction.

## 2. Input surfaces and notation

The input is a rectilinear grid with point-aligned wall elevations:

$$
\left\{x_j,\ y_i,\ z_{\min,ij},\ z_{\max,ij}\right\},
\qquad
i=1,\ldots,N_y,\quad j=1,\ldots,N_x.
$$

The lower wall, upper wall, and mid-surface are

$$
z_\ell(x,y)=z_{\min}(x,y),
\qquad
z_u(x,y)=z_{\max}(x,y),
$$

$$
z_m(x,y)=\frac{z_u(x,y)+z_\ell(x,y)}{2}.
$$

The Workbench convention is:

| Symbol | Meaning | Unit |
|---|---|---|
| $x,y,z$ | global Cartesian coordinates | m |
| $b$ | crack aperture/opening | m |
| $A$ | area | m² |
| $V$ | volume proxy | m³ |
| $\tau_g$ | geometrical tortuosity | 1 |
| $H$ | Hurst exponent | 1 |
| $D$ | fractal dimension convention | 1 |

The current representation requires both walls to remain single-valued height
graphs $z=f(x,y)$ on the same X/Y grid. It does not represent overhangs or
general opposing unstructured meshes.

## 3. Preprocessing and valid samples

All four arrays must have the same shape, the coordinates must be finite, and
the X and Y axes must be monotonic without repeated values. Descending axes are
reversed together with all wall arrays.

For ordinary Workbench analysis, a wall pair is valid when

$$
\mathcal V_{ij}=
\operatorname{finite}(z_{\ell,ij})
\land
\operatorname{finite}(z_{u,ij})
\land
\left(z_{u,ij}-z_{\ell,ij}\ge 0\right).
$$

Negative raw separations are counted and excluded. Missing values remain
excluded. The legacy/headless API can request interpolation or retain negative
geometrical values, but the embedded automatic policy does neither.

The hydraulic open mask uses the preferred local-normal aperture:

$$
\mathcal O_{ij}=
\mathcal V_{ij}\land b_{n,ij}>b_{\mathrm{cut}},
\qquad
b_{\mathrm{cut}}=10^{-12}\ {\rm m}.
$$

Therefore, “closed” means aperture at or below the numerical cutoff, or an
invalid wall pair. It is not a mechanical contact-pressure calculation.

## 4. Physical-axis derivatives and integration weights

### 4.1 Height gradients

For a height field $z(x,y)$, the software estimates

$$
p=\frac{\partial z}{\partial x},
\qquad
q=\frac{\partial z}{\partial y}
$$

with second-order finite differences on the physical, possibly nonuniform,
coordinate axes. Second-order one-sided differences are used at boundaries.
The automatic Workbench policy applies no smoothing.

### 4.2 Nodal control widths

For an ordered coordinate axis $s_1,\ldots,s_N$, the nodal control width is

$$
\Delta s_1^{c}=\frac{s_2-s_1}{2},
\qquad
\Delta s_N^{c}=\frac{s_N-s_{N-1}}{2},
$$

$$
\Delta s_i^{c}=\frac{s_{i+1}-s_{i-1}}{2},
\qquad i=2,\ldots,N-1.
$$

The projected nodal area weight is

$$
A^{p}_{ij}=\Delta x_j^{c}\Delta y_i^{c}.
$$

For a height field $z$, its approximate actual-area weight is

$$
A^{s}_{ij}(z)=
A^{p}_{ij}\sqrt{1+p_{ij}^{2}+q_{ij}^{2}}.
$$

These are node-centered quadrature weights. They are not areas obtained by
triangulating the surface.

### 4.3 Directional profile basis

The automatic labels X and Y begin with the global unit vectors
$\mathbf d_X=(1,0,0)$ and $\mathbf d_Y=(0,1,0)$. For hydraulic paths and
geometrical tortuosity, each requested vector is projected into the
least-squares mid-surface plane. If $\mathbf n_p$ is the fitted plane normal,

$$
\mathbf t=
\mathbf d-(\mathbf d\cdot\mathbf n_p)\mathbf n_p.
$$

The direction used in the structured X/Y parameter plane is

$$
\mathbf u=
\frac{(t_x,t_y)}
{\sqrt{t_x^2+t_y^2}},
$$

and its in-plane transverse is

$$
\mathbf v=(-u_y,u_x).
$$

For a horizontal crack these reduce exactly to the global X and Y axes. For an
inclined crack, the profile may be oblique in the X/Y parameter rectangle.
Axis-aligned profiles use the original samples. Oblique profiles are clipped
to the rectangular domain and sampled by bilinear interpolation.

Roughness and Hurst analysis uses the projected-X profile family and its
orthogonal parameter-plane transverse as the reported X/Y basis. Therefore,
for an inclined plane its reported Y roughness direction is the transverse to
projected X rather than a second independently projected global-Y vector.

## 5. Aperture definitions

Both definitions are always evaluated.

### 5.1 Global-Z aperture

$$
b_z(x,y)=z_u(x,y)-z_\ell(x,y).
$$

This is the paired vertical separation available directly from the four-grid
height-field contract.

### 5.2 Local-normal projected aperture

The upward unit normal of the mid-surface is

$$
\mathbf n_m=
\frac{(-z_{m,x},-z_{m,y},1)}
{\sqrt{1+z_{m,x}^{2}+z_{m,y}^{2}}}.
$$

The paired vertical wall-separation vector is

$$
\Delta\mathbf r=(0,0,b_z).
$$

The preferred geometrical opening is

$$
b_n=\Delta\mathbf r\cdot\mathbf n_m
=b_z\,n_{m,z}
=\frac{b_z}{\sqrt{1+z_{m,x}^{2}+z_{m,y}^{2}}}.
$$

This is a projection of a point-paired vertical separation. It is not the
shortest distance between walls and is not a ray/surface intersection.

## 6. Aperture sample counts and fractions

For $N=N_xN_y$ grid nodes:

$$
N_{\mathrm{valid}}=\sum_{ij}\mathbf 1_{\operatorname{finite}(b_{ij})},
$$

$$
N_0=\sum_{ij}\mathbf 1_{b_{z,ij}=0},
\qquad
N_-=\sum_{ij}\mathbf 1_{b_{z,ij}<0},
$$

$$
N_{\mathrm{closed}}=
\sum_{ij}\mathbf 1_{\neg\operatorname{finite}(b_{ij})
\ \lor\ b_{ij}\le b_{\mathrm{cut}}}.
$$

The closed/invalid sample fraction is

$$
f_{\mathrm{closed},N}=\frac{N_{\mathrm{closed}}}{N}.
$$

The projected-area fraction is

$$
f_{\mathrm{closed},A}=
\frac{\sum_{ij}A^p_{ij}
\mathbf 1_{\neg\operatorname{finite}(b_{ij})
\ \lor\ b_{ij}\le b_{\mathrm{cut}}}}
{\sum_{ij}A^p_{ij}}.
$$

The zero and negative counts are based on the raw global-Z separation so that
invalid wall ordering remains visible even when local-normal statistics are
reported.

## 7. Aperture distribution statistics

Let $b_k$, $k=1,\ldots,n$, denote the finite apertures for one definition.
The software uses population moments (`ddof=0`) unless stated otherwise.

### 7.1 Central tendency and extrema

$$
\bar b=\frac{1}{n}\sum_{k=1}^{n}b_k
\quad\text{(`arithmetic_mean`)},
$$

$$
b_{\min}=\min_k b_k,\qquad
b_{\max}=\max_k b_k,
$$

$$
R_b=b_{\max}-b_{\min}
\quad\text{(`range`)}.
$$

The median is the 50th percentile. Percentiles 1, 5, 10, 25, 50, 75, 90, 95,
and 99 use NumPy’s default linear quantile interpolation.

### 7.2 Variance, standard deviation, coefficient of variation, and RMS

$$
\sigma_b^2=\frac{1}{n}\sum_{k=1}^{n}(b_k-\bar b)^2
\quad\text{(`variance`)},
$$

$$
\sigma_b=\sqrt{\sigma_b^2}
\quad\text{(`standard_deviation`)},
$$

$$
C_v=\frac{\sigma_b}{\bar b}
\quad\text{(`coefficient_of_variation`)},
$$

$$
b_{\mathrm{RMS}}=
\sqrt{\frac{1}{n}\sum_{k=1}^{n}b_k^2}
\quad\text{(`root_mean_square`)}.
$$

$C_v$ is undefined when $\bar b=0$.

### 7.3 Geometric and harmonic means

When every valid aperture is strictly positive:

$$
b_{\mathrm{geom}}=
\left(\prod_{k=1}^{n}b_k\right)^{1/n},
$$

$$
b_{\mathrm{harm}}=
\frac{n}{\sum_{k=1}^{n}b_k^{-1}}.
$$

If any valid value is zero or negative, both outputs are reported as null
rather than forcing a nonphysical value.

### 7.4 Robust spread statistics

The interquartile range is

$$
\mathrm{IQR}=Q_{0.75}-Q_{0.25}.
$$

The median absolute deviation is

$$
\mathrm{MAD}=
\operatorname{median}_k
\left|b_k-\operatorname{median}(b)\right|.
$$

The normal-consistent robust standard-deviation estimate is

$$
\sigma_{\mathrm{robust}}=1.4826\,\mathrm{MAD}.
$$

### 7.5 Skewness and excess kurtosis

With central moments

$$
m_r=\frac{1}{n}\sum_{k=1}^{n}(b_k-\bar b)^r,
$$

the moment skewness is $g_1=m_3/m_2^{3/2}$. The reported value uses the
bias-corrected Fisher–Pearson estimator

$$
G_1=\frac{\sqrt{n(n-1)}}{n-2}\,g_1,
\qquad n\ge3.
$$

Let $g_2=m_4/m_2^2-3$. The reported Fisher excess kurtosis uses the
small-sample correction

$$
G_2=
\frac{n-1}{(n-2)(n-3)}
\left[(n+1)g_2+6\right],
\qquad n\ge4.
$$

For a numerically constant distribution, both are reported as zero.

### 7.6 Area-weighted opening

The projected-area-weighted mean is

$$
\bar b_{A_p}=
\frac{\sum_{\mathcal V}A^p_{ij}b_{ij}}
{\sum_{\mathcal V}A^p_{ij}}.
$$

The mid-surface-area-weighted mean is

$$
\bar b_{A_s}=
\frac{\sum_{\mathcal V}A^s_{ij}(z_m)b_{ij}}
{\sum_{\mathcal V}A^s_{ij}(z_m)}.
$$

The two means answer different questions and are exported under distinct names.

### 7.7 Distribution and resistance-map estimators

The empirical cumulative distribution shown in the aperture figure is

$$
\widehat F_N(\beta)=
\frac{1}{n}\sum_{k=1}^{n}\mathbf 1_{b_k\le\beta}.
$$

For a nondegenerate histogram bin $h$, with count $n_h$ and width
$\Delta b_h$, the plotted probability density is

$$
\widehat f_h=\frac{n_h}{n\,\Delta b_h}.
$$

The number of bins is bounded between 12 and 80 and scales approximately with
$\sqrt n$. A constant or numerically degenerate aperture has no finite
continuous density; the figure therefore shows a labeled single-value marker
instead of dividing by a zero-width bin.

The local cubic-resistance map is

$$
r_b(x,y)=b(x,y)^{-3},
\qquad b>b_{\mathrm{cut}},
$$

and is left undefined at closed or invalid nodes.

## 8. Directional spatial aperture variability

An X profile is one grid row $b_{i,:}$, and a Y profile is one grid column
$b_{:,j}$. For each direction the software reports:

$$
\overline{\sigma_{\mathrm{within},X}}
=\frac{1}{N_y}\sum_i
\operatorname{std}(b_{i,:}),
$$

$$
\sigma_{\mathrm{between},X}
=\operatorname{std}_i
\left(\operatorname{mean}_j b_{ij}\right),
$$

and their Y-direction equivalents.

The following output pairs are intentional aliases of the same calculations:

| Primary interpretation | Equivalent output names |
|---|---|
| mean standard deviation within X profiles | `spatial_std_along_x_mean`, `mean_std_within_x_profiles` |
| mean standard deviation within Y profiles | `spatial_std_along_y_mean`, `mean_std_within_y_profiles` |
| standard deviation of X-profile means | `std_of_x_line_averages`, `std_across_x_profiles` |
| standard deviation of Y-profile means | `std_of_y_line_averages`, `std_across_y_profiles` |

## 9. Cubic-mean aperture

For nonnegative valid openings, the unweighted cubic mean is

$$
b_{\mathrm{cubic}}=
\left(\frac{1}{n}\sum_{k=1}^{n}b_k^3\right)^{1/3}.
$$

The projected-area-weighted cubic mean is

$$
b_{\mathrm{cubic},A_p}=
\left(
\frac{\sum_{\mathcal V}A^p_{ij}b_{ij}^3}
{\sum_{\mathcal V}A^p_{ij}}
\right)^{1/3}.
$$

These characterize the spatial integral of $b^3$, but they do not include
series resistance along a flow path.

## 10. Cubic-law path-equivalent aperture

### 10.1 Physical approximation

For steady, laminar, incompressible flow of a Newtonian fluid between locally
parallel plates, the flow rate per unit transverse width is

$$
q'=-\frac{b^3}{12\mu}\frac{dp}{ds},
$$

where $\mu$ is dynamic viscosity. Removing common fluid and pressure factors
leaves a geometrical resistance density proportional to $b^{-3}$.

### 10.2 One path: resistances in series

For path $j$, with projected coordinate $s$, path length $L_j$, and
aperture $b_j(s)$, the normalized cubic resistance is

$$
R_j^*=
\frac{1}{L_j}\int_0^{L_j}\frac{ds}{b_j(s)^3}.
$$

The discrete trapezoidal estimator is

$$
R_j^*\approx
\frac{
\sum_k\Delta s_k
\left(b_{j,k}^{-3}+b_{j,k+1}^{-3}\right)/2
}{
\sum_k\Delta s_k
}.
$$

The path-equivalent aperture is

$$
b_{\mathrm{eq},j}=(R_j^*)^{-1/3}.
$$

If any sampled aperture satisfies $b\le b_{\mathrm{cut}}$, the entire path is
classified closed:

$$
R_j^*=\infty,\qquad b_{\mathrm{eq},j}=0.
$$

Non-finite samples are removed before the path quadrature. A path with fewer
than two finite samples is closed. Otherwise, separated finite samples can be
joined across a missing interval by one trapezoidal segment; datasets with
substantial gaps must therefore be repaired or interpreted conservatively.

### 10.3 All paths: conductances in parallel

With projected transverse control width $w_j$, the global directional
equivalent is

$$
b_{\mathrm{eq,global}}=
\left(
\frac{\sum_jw_jb_{\mathrm{eq},j}^{3}}
{\sum_jw_j}
\right)^{1/3}.
$$

The calculation is performed for all four combinations:

| Aperture | Direction |
|---|---|
| $b_z$ | X |
| $b_z$ | Y |
| $b_n$ | X |
| $b_n$ | Y |

Each direction also reports the arithmetic mean, minimum, maximum, population
standard deviation, positive-path mean, number of closed paths, and indices of
the largest- and smallest-resistance paths.

The global combination uses the normalized resistance of each path and does
not apply an additional $1/L_j$ weighting between paths. It is exact for the
software’s normalized parallel-path definition and is most directly physical
when the parallel paths have the same projected length, as in axis-aligned
rectangular X or Y traversal.

### 10.4 Interpretation limit

$b_{\mathrm{eq}}$ is a geometry-based cubic-law proxy. It does not account
for inertial losses, compressibility, wall contact deformation, recirculation,
three-dimensional channel switching, entrance/exit losses, or unresolved
roughness. It must not be presented as a CFD result.

## 11. Geometrical tortuosity

For a wall or mid-surface profile $z(s)$, the three-dimensional profile
length in the vertical section is

$$
L_g=
\sum_k\sqrt{(\Delta s_k)^2+(\Delta z_k)^2}.
$$

The projected in-plane length is

$$
L_p=\sum_k|\Delta s_k|.
$$

The geometrical tortuosity is

$$
\tau_g=\frac{L_g}{L_p}\ge1.
$$

It is calculated for the lower wall, upper wall, and mid-surface, separately
along X and Y. Each profile is exported, followed by directional summary mean,
median, extrema, population standard deviation, and percentiles.

This is not hydraulic tortuosity: it measures the lengthening of a geometrical
height profile. Finite samples are compacted before differencing, so datasets
with large missing gaps should be repaired or interpreted carefully because a
gap may be bridged by one segment.

## 12. Plane detrending and roughness amplitudes

For each of $z_\ell$, $z_u$, and $z_m$, a least-squares plane

$$
\hat z(x,y)=ax+by+c
$$

is obtained from

$$
(a,b,c)=
\underset{a,b,c}{\operatorname{arg\,min}}
\sum_{\mathcal V}
\left[z_{ij}-(ax_j+by_i+c)\right]^2.
$$

The detrended residual is

$$
r_{ij}=z_{ij}-\hat z_{ij}.
$$

For $n$ valid residuals:

$$
R_a=\frac{1}{n}\sum|r_k|
\quad\text{(`arithmetic_roughness_ra`)},
$$

$$
R_q=\sqrt{\frac{1}{n}\sum r_k^2}
\quad\text{(`root_mean_square_roughness_rq`)},
$$

$$
R_t=\max(r)-\min(r)
\quad\text{(`peak_to_valley_height`)},
$$

$$
\sigma_r=
\sqrt{\frac{1}{n}\sum(r_k-\bar r)^2}
\quad\text{(`height_standard_deviation`)}.
$$

The slope descriptors use physical-axis derivatives of the original height
field:

$$
\sigma_{p}=\operatorname{std}\left(\frac{\partial z}{\partial x}\right),
\qquad
\sigma_{q}=\operatorname{std}\left(\frac{\partial z}{\partial y}\right),
$$

$$
\overline{|\nabla z|}=
\frac{1}{n}\sum
\sqrt{
\left(\frac{\partial z}{\partial x}\right)^2+
\left(\frac{\partial z}{\partial y}\right)^2
}.
$$

Constant mean-plane slope does not change the slope standard deviations, but it
does contribute to the reported mean slope magnitude.

## 13. Directional autocorrelation

### 13.1 Profile autocorrelation length

Each X or Y height profile is linearly detrended. For a discrete residual
profile $r_0,\ldots,r_{N-1}$, the overlap-corrected nonnegative-lag
autocovariance is

$$
\widehat C(m)=
\frac{1}{N-m}\sum_{k=0}^{N-m-1}r_kr_{k+m}.
$$

The normalized autocorrelation is

$$
\rho(m)=\frac{\widehat C(m)}{\widehat C(0)}.
$$

The profile correlation length is the physical distance to the first sampled
lag satisfying

$$
\rho\le e^{-1}.
$$

The reported `correlation_length_x` or `correlation_length_y` is the arithmetic
mean of available profile crossing lengths. No crossing or a flat profile
produces a null value. The anisotropy ratio is

$$
\chi_\lambda=
\frac{\max(\lambda_x,\lambda_y)}
{\min(\lambda_x,\lambda_y)}\ge1.
$$

### 13.2 Two-dimensional autocorrelation map

For the centered mid-surface field $r$ and binary validity mask $M$, the
FFT implementation evaluates

$$
C_{2D}=
\mathcal F^{-1}
\left[\mathcal F(r)\mathcal F(r)^*\right],
$$

$$
N_{\mathrm{overlap}}=
\mathcal F^{-1}
\left[\mathcal F(M)\mathcal F(M)^*\right],
$$

$$
\rho_{2D}=
\frac{C_{2D}}{N_{\mathrm{overlap}}},
$$

where division is performed only at positive overlap. The map is centered with
an FFT shift and normalized by its largest absolute value. It is a diagnostic
figure; scalar X/Y correlation lengths come from the profile estimator above.

## 14. Hurst exponent: structure-function estimator

Each valid X or Y profile with at least eight samples is linearly detrended.
For sample lag $m$, the second-order RMS increment for profile $j$ is

$$
S_{2,j}^{1/2}(m)=
\sqrt{
\frac{1}{N_j-m}
\sum_{k=0}^{N_j-m-1}
\left[r_{j,k+m}-r_{j,k}\right]^2
}.
$$

The associated physical scale is

$$
\ell_j(m)=
\frac{1}{N_j-m}
\sum_{k=0}^{N_j-m-1}(s_{j,k+m}-s_{j,k}).
$$

The response fitted by the software is the profile mean

$$
\overline S_2^{1/2}(m)=
\frac{1}{N_p}\sum_jS_{2,j}^{1/2}(m).
$$

For a self-affine profile:

$$
\overline S_2^{1/2}(\ell)=C\ell^H.
$$

Ordinary least squares is applied to

$$
\log_{10}\overline S_2^{1/2}
=H\log_{10}\ell+\log_{10}C.
$$

Therefore, for `structure_function`,

$$
H=m_{\mathrm{fit}}.
$$

The automatic lag range begins at one sample and normally stops at 25% of the
shortest profile. Short profiles may extend the limit enough to supply at least
four candidate lags, but never beyond half the profile.

## 15. Hurst exponent: profile-PSD estimator

For a detrended profile $r_n$, $n=0,\ldots,N-1$, a Hann window $w_n$ is
applied. With mean physical sampling interval $\Delta s$, the one-sided
periodogram is

$$
P(f_k)=
\frac{\Delta s}
{\sum_{n=0}^{N-1}w_n^2}
\left|
\sum_{n=0}^{N-1}r_nw_n
\exp(-2\pi i kn/N)
\right|^2.
$$

The zero-frequency component is removed. Profile spectra are interpolated to a
common frequency grid when necessary and then averaged.

For a self-affine profile:

$$
P(f)=C f^{-(2H+1)}.
$$

If the fitted log-log slope is $m_{\mathrm{fit}}$,

$$
H=\frac{-m_{\mathrm{fit}}-1}{2}.
$$

The implementation fits the interior portion from approximately 5% to 60% of
the available positive-frequency indices, with at least four points.

## 16. Hurst fit diagnostics and fractal-dimension conventions

For log responses $y_i$ and fitted values $\hat y_i$,

$$
R^2=
1-
\frac{\sum_i(y_i-\hat y_i)^2}
{\sum_i(y_i-\bar y)^2}.
$$

The deterministic 95% interval resamples entire parallel profiles with
replacement. For each of $B=100$ bootstrap replicates, the mean response and
Hurst slope are recalculated. The interval is

$$
\left[
Q_{0.025}(H^{*}),
Q_{0.975}(H^{*})
\right].
$$

An interval is omitted when fewer than $\max(10,B/5)$ valid replicates remain.

The fitted scale span in decades is

$$
\Delta_{\mathrm{decade}}=
\log_{10}
\left(\frac{\ell_{\max}}{\ell_{\min}}\right)
$$

for the structure function, or the analogous
$\log_{10}(f_{\max}/f_{\min})$ PSD-frequency span.

A fit is flagged unreliable if:

1. its fitted scale range is shorter than 0.5 decades;
2. $R^2<0.90$;
3. $H\notin[0,1]$; or
4. fewer than four varying fit points are available.

For a flat or unresolved surface, $H$ is null. The software does not invent a
fractal exponent.

The reported dimension conventions are

$$
D_{\mathrm{profile}}=2-H,
$$

$$
D_{\mathrm{surface\ graph}}=3-H.
$$

The second relation assumes an isotropic self-affine surface graph. A
directional profile estimate alone does not prove that assumption.

## 17. Surface areas and projected crack volume

For valid nodes:

$$
A_{\mathrm{proj}}=\sum_{\mathcal V}A^p_{ij},
$$

$$
A_\ell=\sum_{\mathcal V}
A^p_{ij}\sqrt{1+z_{\ell,x}^2+z_{\ell,y}^2},
$$

$$
A_u=\sum_{\mathcal V}
A^p_{ij}\sqrt{1+z_{u,x}^2+z_{u,y}^2},
$$

$$
A_m=\sum_{\mathcal V}
A^p_{ij}\sqrt{1+z_{m,x}^2+z_{m,y}^2}.
$$

The mid-surface area ratio is

$$
\rho_A=\frac{A_m}{A_{\mathrm{proj}}}.
$$

The exported `crack_volume_projected` uses the preferred local-normal aperture:

$$
V_{\mathrm{proj}}=
\sum_{\mathcal V}A^p_{ij}\max(b_{n,ij},0).
$$

It is explicitly a projected-volume proxy. For an inclined crack it is not the
same as integrating global-Z opening over projected area or local-normal
opening over actual area.

## 18. Mean plane and normal orientation

The mid-surface plane $z=ax+by+c$ is fitted by least squares. Its upward unit
normal is

$$
\mathbf n_p=
\frac{(-a,-b,1)}
{\sqrt{a^2+b^2+1}}.
$$

The reported inclination is

$$
\theta_{\mathrm{dip}}=
\cos^{-1}(n_{p,z}),
$$

and the reported normal azimuth is

$$
\theta_{\mathrm{azimuth}}=
\operatorname{atan2}(n_{p,y},n_{p,x})
\pmod{360^\circ}.
$$

For local mid-surface normals $\mathbf n_k$, define

$$
\mathbf r=\frac{1}{n}\sum_k\mathbf n_k,
\qquad
R=\|\mathbf r\|,
\qquad
\bar{\mathbf n}=\frac{\mathbf r}{R}.
$$

`mean_resultant_length` is $R$. Values near one indicate aligned normals;
smaller values indicate greater orientation dispersion. The angular deviations
are

$$
\alpha_k=
\cos^{-1}\left(
\operatorname{clip}(\mathbf n_k\cdot\bar{\mathbf n},-1,1)
\right).
$$

The software reports the population standard deviation and 95th percentile of
$\alpha_k$ in degrees.

## 19. Open-region connectivity

Connectivity uses the binary open mask $\mathcal O$ and four-neighbor
adjacency:

$$
(i,j)\sim(i\pm1,j)
\quad\text{or}\quad
(i,j)\sim(i,j\pm1).
$$

Diagonal contact alone does not connect two nodes. Connected-component
labeling returns:

- the number of open regions;
- `disconnected_open_regions = max(0, open_regions - 1)`;
- samples per region;
- projected area $\sum A^p_{ij}$;
- axis-aligned X and Y extents.

This is topology on the projected grid. It is not three-dimensional hydraulic
connectivity.

## 20. Aperture gradients, bottleneck, and conductance proxies

For the preferred local-normal aperture:

$$
g_x=\frac{\partial b_n}{\partial x},
\qquad
g_y=\frac{\partial b_n}{\partial y},
\qquad
|\nabla b_n|=\sqrt{g_x^2+g_y^2}.
$$

The software reports the mean and population standard deviation of $g_x$ and
$g_y$, plus the mean of $|\nabla b_n|$. These gradients are dimensionless
when coordinates and aperture use the same length unit.

The bottleneck grid node is

$$
(i_b,j_b)=
\underset{(i,j)\in\mathcal V}{\operatorname{arg\,min}}\ b_{n,ij}.
$$

Its grid indices and physical X/Y coordinates are stored. This is a pointwise
minimum, not necessarily the controlling hydraulic path.

The area-integrated cubic conductance proxy is

$$
I_{b^3}=
\sum_{ij}A^p_{ij}
\left[\max(b_{n,ij},0)\mathbf 1_{\mathcal O_{ij}}\right]^3.
$$

Its unit is m⁵. The smooth parallel-plate reference is

$$
I_{\mathrm{smooth}}=
\left(\sum_{ij}A^p_{ij}\right)\bar b_n^3.
$$

The normalized proxy is

$$
\Gamma=
\frac{I_{b^3}}{I_{\mathrm{smooth}}}.
$$

$\Gamma$ measures the effect of aperture variability under a purely parallel
local-conductance interpretation. It does not include series path resistance.

## 21. Additive two-dimensional wavelet decomposition

Wavelet decomposition is automatic and is applied independently to:

1. the lower wall $z_\ell$;
2. the upper wall $z_u$;
3. the mid-surface $z_m$;
4. the global-Z aperture $b_z$; and
5. the local-normal aperture $b_n$.

The objective is not only to store wavelet coefficients. Every scale and
orientation is reconstructed onto the original full-resolution X/Y grid so the
component surfaces can be visualized and added directly.

### 21.1 Separable two-dimensional filter bank

Let $A_0[m,n]$ be one sampled input field. At wavelet level $j+1$, a
low-pass analysis filter $h$, high-pass analysis filter $g$, and dyadic
downsampling give

$$
A_{j+1}[m,n]=
\sum_{p,q}h[p]h[q]\,
A_j[2m-p,2n-q],
$$

$$
C_{j+1}^{H}[m,n]=
\sum_{p,q}g[p]h[q]\,
A_j[2m-p,2n-q],
$$

$$
C_{j+1}^{V}[m,n]=
\sum_{p,q}h[p]g[q]\,
A_j[2m-p,2n-q],
$$

$$
C_{j+1}^{D}[m,n]=
\sum_{p,q}g[p]g[q]\,
A_j[2m-p,2n-q].
$$

$A_{j+1}$ is the coarse coefficient array. The three $C$ arrays contain
the library-convention horizontal, vertical, and diagonal detail coefficients.
The automatic policy uses the orthogonal Daubechies-2 wavelet (`db2`) with
symmetric boundary extension. A grid too small for one `db2` level falls back
to the Haar wavelet.

In the coefficient order used by PyWavelets, the `db2` analysis filters are

$$
h=
[-0.12940952255126037,\,
  0.2241438680420134,\,
  0.8365163037378079,\,
  0.48296291314453416],
$$

$$
g=
[-0.48296291314453416,\,
  0.8365163037378079,\,
 -0.2241438680420134,\,
 -0.12940952255126037].
$$

For the small-grid Haar fallback,
$h=[1/\sqrt 2,1/\sqrt 2]$ and
$g=[-1/\sqrt 2,1/\sqrt 2]$.

The maximum decomposition depth is

$$
J=
\min\left(
5,\,
J_{\max}(N_x,\mathrm{filter\ length}),\,
J_{\max}(N_y,\mathrm{filter\ length})
\right).
$$

The library selects $J_{\max}$ so at least one coefficient remains
uncontaminated by complete filter-length boundary overlap.

### 21.2 Full-resolution component surfaces

Inverse wavelet synthesis is applied with all coefficient groups set to zero
except the desired group. This produces:

$$
\mathcal A_J=
\mathcal W^{-1}(A_J,0,\ldots,0),
$$

$$
\mathcal D_j^H=
\mathcal W^{-1}(0,\ldots,C_j^H,\ldots,0),
$$

$$
\mathcal D_j^V=
\mathcal W^{-1}(0,\ldots,C_j^V,\ldots,0),
$$

$$
\mathcal D_j^D=
\mathcal W^{-1}(0,\ldots,C_j^D,\ldots,0).
$$

The combined full-resolution detail surface at level $j$ is

$$
\mathcal D_j=
\mathcal D_j^H+
\mathcal D_j^V+
\mathcal D_j^D.
$$

The exported additive identity is

$$
\boxed{
A_0=
\mathcal A_J+
\sum_{j=1}^{J}\mathcal D_j
}
$$

to floating-point reconstruction precision. Equivalently,

$$
A_0=
\mathcal A_J+
\sum_{j=1}^{J}
\left(
\mathcal D_j^H+
\mathcal D_j^V+
\mathcal D_j^D
\right).
$$

Level 1 is the finest detail. Increasing $j$ represents progressively larger
spatial structures. Individual detail components are signed oscillatory
surfaces and are not physical crack openings by themselves; the additive sum
reconstructs the physical field.

### 21.3 Approximate physical wavelength bands

For uniform mean spacings $\overline{\Delta x}$ and
$\overline{\Delta y}$, detail level $j$ is labeled with the approximate
dyadic bands

$$
\lambda_x\in
\left[
2^j\overline{\Delta x},
2^{j+1}\overline{\Delta x}
\right],
$$

$$
\lambda_y\in
\left[
2^j\overline{\Delta y},
2^{j+1}\overline{\Delta y}
\right].
$$

The coarse approximation contains the remaining long scales, approximately

$$
\lambda_x\gtrsim2^{J+1}\overline{\Delta x},
\qquad
\lambda_y\gtrsim2^{J+1}\overline{\Delta y},
$$

including the mean/DC component.

These bands are scale interpretations, not ideal brick-wall Fourier bands,
because compact wavelet filters have overlapping frequency responses. On a
nonuniform input grid, the transform operates in sample-index space and these
physical wavelengths are explicitly flagged as approximate values based on
mean spacing.

### 21.4 Reconstruction verification

Let $\widehat A_0$ be the sum of the exported coarse and combined-detail
surfaces. The reconstruction error field is

$$
E_{ij}=\widehat A_{0,ij}-A_{0,ij}.
$$

The metadata reports

$$
E_\infty=\max_{ij}|E_{ij}|,
$$

$$
E_{\mathrm{RMS}}=
\sqrt{\frac{1}{N_xN_y}\sum_{ij}E_{ij}^2},
$$

$$
E_{\mathrm{rel},2}=
\frac{\|E\|_2}{\|A_0\|_2}.
$$

For finite inputs these values should remain near machine precision. If an
input contains non-finite nodes, linear interpolation with nearest-neighbor
boundary fallback constructs a transparent `wavelet_target_surface`; the
additive identity reconstructs that completed field. The untouched input with
NaNs is also exported.

### 21.5 Component amplitudes

For every reconstructed component $W$, the wavelet summary table reports

$$
\bar W=\frac{1}{N}\sum_iW_i,
\qquad
\sigma_W=
\sqrt{\frac{1}{N}\sum_i(W_i-\bar W)^2},
$$

$$
W_{\mathrm{RMS}}=
\sqrt{\frac{1}{N}\sum_iW_i^2},
\qquad
\|W\|_2=\sqrt{\sum_iW_i^2},
$$

$$
\eta_{W,2}=
\frac{\sum_iW_i^2}{\sum_iA_{0,i}^2}.
$$

$\eta_{W,2}$ is labeled a squared-L2 fraction, not an energy-conservation
claim after full-resolution reconstruction and boundary extension.

### 21.6 Export structure

All wavelet results are isolated under
`wavelet_decomposition/`. Shared `x_coordinates.csv` and `y_coordinates.csv`
retain the original grid. Each field subfolder contains:

- `input_surface.csv`;
- `wavelet_target_surface.csv`;
- `approximation_level_J.csv`;
- `detail_level_j_combined.csv`;
- `detail_level_j_horizontal.csv`;
- `detail_level_j_vertical.csv`;
- `detail_level_j_diagonal.csv`;
- `reconstructed_surface.csv`;
- `reconstruction_error.csv`;
- `metadata.json`; and
- `wavelet_components.png`.

The root `README.md` states the additive file recipe. The root `manifest.json`
identifies all fields and reconstruction errors.
`wavelet_decomposition.csv` provides one scalar-statistics row per coarse,
combined-detail, and directional-detail component.

## 22. Synthetic anisotropic surface generation

Synthetic generation is optional and independent of measured-surface analysis.
Two independent Gaussian spectral fields are created: one for the mid-surface
and one for aperture fluctuations.

### 22.1 Fourier grid and anisotropic radius

For physical sizes $L_x,L_y$, define angular wavenumbers $k_x,k_y$.
With target correlation scales $\lambda_x,\lambda_y$,

$$
\rho(k_x,k_y)=
\sqrt{(k_x\lambda_x)^2+(k_y\lambda_y)^2}.
$$

Blank correlation inputs use

$$
\lambda_x=\frac{L_x}{4},
\qquad
\lambda_y=\frac{L_y}{4}.
$$

The directional weight is

$$
w_x=
\frac{(k_x\lambda_x)^2}{\rho^2},
$$

and the locally blended exponent is

$$
H_{\mathrm{loc}}=
w_xH_x+(1-w_x)H_y.
$$

### 22.2 Spectral filter

For nonzero $\rho$, the Fourier-amplitude filter is

$$
F(k_x,k_y)=
\rho^{-(H_{\mathrm{loc}}+1)}.
$$

If $\eta(x,y)$ is unit Gaussian white noise, the unnormalized field is

$$
u=
\mathcal F^{-1}
\left[\mathcal F(\eta)F\right].
$$

The zero-frequency coefficient is set to zero. The field is then standardized:

$$
u_0=\frac{u-\bar u}{\operatorname{std}(u)}.
$$

This is a finite-grid anisotropic Gaussian spectral model. $H_x$, $H_y$,
and the correlation lengths are spectral targets, not guaranteed achieved
measurements.

### 22.3 Mid-surface

$$
z_m(x,y)=
R_{q,\mathrm{target}}u_{m,0}
+a_xx+a_yy.
$$

Because $u_{m,0}$ has unit population standard deviation, the random
component has target RMS amplitude before finite-grid re-detrending.

### 22.4 Aperture field

The aperture field uses an independent standardized field $u_{b,0}$:

$$
b_{\mathrm{raw}}=
\bar b_{\mathrm{target}}
+\sigma_{b,\mathrm{target}}u_{b,0}.
$$

The aperture spectral field uses

$$
H_{b,x}=\min(0.95,H_x+0.05),
\qquad
H_{b,y}=\min(0.95,H_y+0.05).
$$

The following operations are applied in order:

1. lower clipping,
   $b\leftarrow\max(b,b_{\min})$;
2. optional upper clipping,
   $b\leftarrow\min(b,b_{\max})$;
3. the lowest-ranked
   $\operatorname{round}(f_cN)$ samples are set to zero;
4. if positivity is enabled,
   $b\leftarrow\max(b,0)$.

Because contact is imposed after lower clipping, contact nodes become zero even
when $b_{\min}>0$. Clipping and contact generally change the achieved mean,
standard deviation, spectrum, and correlation.

### 22.5 Wall reconstruction

$$
z_\ell=z_m-\frac{b}{2},
\qquad
z_u=z_m+\frac{b}{2}.
$$

The separation is symmetric in global Z to preserve the mesh-compatible CSV
contract. The local-normal opening is recalculated during verification.

### 22.6 Ensembles

For realization index $r=0,\ldots,R-1$,

$$
\mathrm{seed}_r=\mathrm{seed}_0+r.
$$

Every realization is generated independently and re-characterized.

## 23. Synthetic target-versus-achieved errors

For target $t$ and achieved value $a$:

$$
e_{\mathrm{abs}}=a-t,
$$

$$
e_{\mathrm{rel}}=\frac{a-t}{t},
\qquad t\ne0.
$$

The achieved aperture metrics use the preferred local-normal definition. The
reported achieved contact fraction is the closed-or-invalid fraction based on
the hydraulic cutoff, not merely the exact count of zero-valued generated
samples.

## 24. Output-to-equation map

| Output artifact | Main quantities |
|---|---|
| `characterization_summary.json` | all configuration, aperture, hydraulic, tortuosity, roughness, geometry, connectivity, additional metrics, warnings |
| `characterization_summary.csv` | flattened scalar summary fields |
| `aperture_statistics.csv` | Sections 6–9 for both $b_z$ and $b_n$ |
| `flow_path_equivalent_aperture.csv` | Section 10, each path, both aperture definitions, X and Y |
| `directional_tortuosity.csv` | Section 11, every lower/upper/mid profile in X and Y |
| `roughness_statistics.csv` | Sections 12–13 for lower, upper, and mid surfaces |
| `hurst_analysis.csv` | Sections 14–16 for both methods, X and Y |
| `wavelet_decomposition.csv` | Section 21 component scales, wavelength bands, amplitudes, and L2 fractions |
| `wavelet_decomposition/` | Section 21 full-resolution additive surfaces and reconstruction evidence |
| `surface_orientation_statistics.csv` | Section 18 |
| `synthetic_surface_validation.csv` | Section 23 |
| `characterization_report.md` | run-specific concise results and warnings |
| `characterization_equations.md` | a copy of this full equations report |

Geometry, connectivity, aperture-gradient, bottleneck, and conductance fields
are stored in the JSON summary and its flattened CSV representation.

## 25. Interpretation hierarchy

The outputs should be interpreted in this order:

1. **Validate the geometry:** inspect invalid/negative samples and wall order.
2. **Inspect both apertures:** compare global-Z and local-normal opening.
3. **Inspect closure and connectivity:** confirm that open regions are
   physically meaningful.
4. **Use descriptive statistics:** quantify opening and roughness variability.
5. **Use X/Y geometrical tortuosity:** describe surface-profile lengthening.
6. **Interpret wavelet scales additively:** use the signed detail surfaces to
   locate structures by scale and orientation, then recover the physical field
   only from the documented complete sum.
7. **Review Hurst diagnostics:** accept an exponent only when its scale range,
   $R^2$, confidence interval, and warnings are credible.
8. **Treat cubic-law quantities as proxies:** compare with CFD or experiments
   before using them for leakage prediction.

## 26. Principal limitations

- The walls are point-aligned height graphs; overhangs and branching wall
  correspondences are outside the current estimator.
- Local-normal opening is a projection, not an opposing-wall intersection.
- Projected-volume and $b^3$ integrals are geometry proxies with explicitly
  stated measures.
- Four-neighbor open connectivity is not a flow solve.
- Geometrical tortuosity is not hydraulic tortuosity.
- Cubic-law equivalents omit inertia, compressibility, contact mechanics,
  unresolved roughness, and general three-dimensional flow redistribution.
- Hurst behavior must exist over a sufficient physical scale range; a fitted
  straight line alone is not proof of self-affinity.
- Wavelet detail levels are signed scale components, not independent physical
  crack surfaces; only their documented additive sum reconstructs the input.
- Wavelet wavelength labels are approximate dyadic bands and become
  index-space interpretations on nonuniform grids.
- Synthetic clipping and imposed contact change the achieved spectral and
  marginal statistics, which is why every realization is verified.

## 27. Implementation traceability

| Subject | Python implementation |
|---|---|
| validation and wall ordering | `crack_characterization/validation.py` |
| aperture definitions | `crack_characterization/aperture.py` |
| nodal areas, gradients, normals, orientation, connectivity | `crack_characterization/geometry.py` |
| descriptive and cubic statistics | `crack_characterization/statistics.py` |
| path-equivalent aperture and tortuosity | `crack_characterization/flow_metrics.py` |
| roughness, autocorrelation, and Hurst estimators | `crack_characterization/roughness.py` |
| additive wavelet decomposition and export | `crack_characterization/wavelet.py` |
| additional metrics and orchestration | `crack_characterization/pipeline.py` |
| synthetic spectral model | `crack_characterization/synthetic_surface.py` |
| CSV/JSON/Markdown exports | `crack_characterization/export.py` |

The analytical planar and varying-aperture regression reference is documented
in `docs/validation/matlab-characterization-reference.json`. It validates
selected equations independently; it does not validate every physical
assumption of the reconstructed crack or the cubic-law model.
