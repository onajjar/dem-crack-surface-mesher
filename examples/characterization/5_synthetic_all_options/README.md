# Synthetic example using every exposed option

This case matches the **Bounded contact ensemble** preset in the embedded
Characterization tab. It exists to explain and regression-test every editable
synthetic input while the ordinary characterization remains parameter-free.

| Input | Meaning in this example |
|---|---|
| `points_x`, `points_y` | Compact regression resolution, 48 × 40 |
| `size_x`, `size_y` | Physical in-plane dimensions |
| `mean_aperture` | Target average wall separation |
| `aperture_standard_deviation` | Target opening variability before clipping/contact |
| `mid_surface_rms` | Target detrended mid-surface roughness amplitude |
| `hurst_x`, `hurst_y` | Directional self-affine spectral exponents |
| `correlation_length_x`, `correlation_length_y` | Directional spectral length scales |
| `minimum_aperture`, `maximum_aperture` | Hard generated-opening bounds |
| `contact_fraction` | Fraction of the lowest openings explicitly set to zero |
| `positive_aperture` | Prevents negative wall separation |
| `mean_plane_slope_x`, `mean_plane_slope_y` | Inclines the generated mean plane |
| `random_seed` | Makes all generated arrays exactly reproducible |
| `realizations` | Generates three independent members using seed, seed+1, seed+2 |

Clipping and imposed contacts alter the achieved mean, standard deviation, and
spectrum. Therefore, the program automatically re-characterizes each
realization. Review `synthetic_surface_validation.csv` and the per-realization
verification folders rather than assuming the targets were achieved exactly.
