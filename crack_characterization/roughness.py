"""Directional roughness, autocorrelation, and Hurst-fit diagnostics."""

from __future__ import annotations

import numpy as np
from scipy.signal import detrend

from .flow_metrics import ProfileSet, build_profile_set, sample_profiles
from .geometry import surface_gradients
from .model import CharacterizationConfig, HurstFit, PreparedSurface


def _clean_profiles(
    surface: PreparedSurface,
    height: np.ndarray,
    profiles: ProfileSet,
) -> list[tuple[np.ndarray, np.ndarray]]:
    result: list[tuple[np.ndarray, np.ndarray]] = []
    for distance, values in zip(
        profiles.projected_distance,
        sample_profiles(surface, height, profiles),
        strict=True,
    ):
        finite = np.isfinite(distance) & np.isfinite(values)
        if np.count_nonzero(finite) < 8:
            continue
        s = distance[finite]
        z = detrend(values[finite], type="linear")
        result.append((s, z))
    return result


def _linear_fit(
    x: np.ndarray,
    y: np.ndarray,
) -> tuple[float, float, float, np.ndarray]:
    coefficients = np.polyfit(x, y, 1)
    fitted = np.polyval(coefficients, x)
    residual = y - fitted
    total = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 - float(np.sum(residual**2)) / total if total > 0 else 0.0
    return float(coefficients[0]), float(coefficients[1]), r_squared, fitted


def _structure_curve(
    profiles: list[tuple[np.ndarray, np.ndarray]],
    min_lag: int,
    max_fraction: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    shortest = min(len(values) for _distance, values in profiles)
    max_lag = min(shortest // 2, max(min_lag + 3, int(shortest * max_fraction)))
    lags = np.arange(min_lag, max_lag + 1)
    scale: list[float] = []
    response: list[float] = []
    per_profile: list[np.ndarray] = []
    for distance, values in profiles:
        curve = []
        local_scale = []
        for lag in lags:
            increments = values[lag:] - values[:-lag]
            curve.append(float(np.sqrt(np.mean(increments**2))))
            local_scale.append(float(np.mean(distance[lag:] - distance[:-lag])))
        per_profile.append(np.asarray(curve))
        if not scale:
            scale = local_scale
    response = np.nanmean(np.vstack(per_profile), axis=0).tolist()
    return np.asarray(scale), np.asarray(response), np.vstack(per_profile)


def _psd_curve(
    profiles: list[tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    shortest = min(len(values) for _distance, values in profiles)
    spectra: list[np.ndarray] = []
    frequencies: list[np.ndarray] = []
    for distance, values in profiles:
        sample = values[:shortest]
        spacing = float(np.mean(np.diff(distance[:shortest])))
        window = np.hanning(shortest)
        normalization = np.sum(window**2)
        spectrum = np.abs(np.fft.rfft(sample * window)) ** 2 * spacing / normalization
        frequency = np.fft.rfftfreq(shortest, spacing)
        spectra.append(spectrum[1:])
        frequencies.append(frequency[1:])
    reference = frequencies[0]
    stacked = np.vstack(
        [
            spectrum
            if np.array_equal(frequency, reference)
            else np.interp(reference, frequency, spectrum, left=np.nan, right=np.nan)
            for frequency, spectrum in zip(frequencies, spectra, strict=True)
        ]
    )
    return reference, np.nanmean(stacked, axis=0), stacked


def _bootstrap_interval(
    scale: np.ndarray,
    per_profile: np.ndarray,
    method: str,
    samples: int,
    seed: int,
) -> tuple[float | None, float | None]:
    if samples == 0 or per_profile.shape[0] < 2:
        return None, None
    rng = np.random.default_rng(seed)
    exponents: list[float] = []
    for _ in range(samples):
        selected = rng.integers(0, per_profile.shape[0], size=per_profile.shape[0])
        response = np.nanmean(per_profile[selected], axis=0)
        valid = (scale > 0) & (response > 0) & np.isfinite(response)
        if np.count_nonzero(valid) < 4:
            continue
        slope = float(np.polyfit(np.log10(scale[valid]), np.log10(response[valid]), 1)[0])
        exponents.append(slope if method == "structure_function" else (-slope - 1.0) / 2.0)
    if len(exponents) < max(10, samples // 5):
        return None, None
    return tuple(float(value) for value in np.percentile(exponents, (2.5, 97.5)))


def _hurst_fit(
    profiles: list[tuple[np.ndarray, np.ndarray]],
    *,
    method: str,
    surface_name: str,
    direction: str,
    config: CharacterizationConfig,
    seed_offset: int,
) -> HurstFit:
    if len(profiles) < 1:
        return HurstFit(
            method,
            surface_name,
            direction,
            None,
            None,
            None,
            None,
            None,
            None,
            0,
            None,
            None,
            False,
            "No profile contains at least eight finite points.",
            np.array([]),
            np.array([]),
            np.array([]),
        )
    if method == "structure_function":
        scale, response, per_profile = _structure_curve(
            profiles,
            config.hurst_min_lag,
            config.hurst_max_scale_fraction,
        )
    else:
        scale, response, per_profile = _psd_curve(profiles)
        lower = max(1, int(np.floor(scale.size * 0.05)))
        upper = max(lower + 4, int(np.ceil(scale.size * 0.6)))
        scale = scale[lower:upper]
        response = response[lower:upper]
        per_profile = per_profile[:, lower:upper]
    valid = (scale > 0) & (response > np.finfo(float).tiny) & np.isfinite(response)
    scale = scale[valid]
    response = response[valid]
    per_profile = per_profile[:, valid]
    if scale.size < 4 or np.ptp(response) <= np.finfo(float).eps:
        return HurstFit(
            method,
            surface_name,
            direction,
            None,
            None,
            None,
            None,
            None,
            None,
            int(scale.size),
            float(scale.min()) if scale.size else None,
            float(scale.max()) if scale.size else None,
            False,
            "The surface is flat or the usable scaling range has fewer than four points.",
            scale,
            response,
            np.full_like(response, np.nan),
        )
    log_scale = np.log10(scale)
    log_response = np.log10(response)
    slope, intercept, r_squared, fitted_log = _linear_fit(log_scale, log_response)
    exponent = slope if method == "structure_function" else (-slope - 1.0) / 2.0
    confidence = _bootstrap_interval(
        scale,
        per_profile,
        method,
        config.hurst_bootstrap_samples,
        config.random_seed + seed_offset,
    )
    scale_decades = float(np.log10(scale.max() / scale.min()))
    warning = None
    reliable = True
    if scale_decades < 0.5:
        reliable = False
        warning = "Scaling range spans less than half a decade."
    elif r_squared < 0.9:
        reliable = False
        warning = "Log-log regression R-squared is below 0.90."
    elif not 0.0 <= exponent <= 1.0:
        reliable = False
        warning = "Estimated H is outside the physical self-affine range [0, 1]."
    return HurstFit(
        method=method,
        surface=surface_name,
        direction=direction,
        exponent=float(exponent),
        slope=slope,
        intercept=intercept,
        r_squared=r_squared,
        confidence_low=confidence[0],
        confidence_high=confidence[1],
        points_used=int(scale.size),
        scale_min=float(scale.min()),
        scale_max=float(scale.max()),
        reliable=reliable,
        warning=warning,
        scale=scale,
        response=response,
        fitted_response=10.0**fitted_log,
    )


def _autocorrelation_length(profiles: list[tuple[np.ndarray, np.ndarray]]) -> float | None:
    lengths: list[float] = []
    for distance, values in profiles:
        variance = float(np.var(values))
        if variance <= np.finfo(float).tiny:
            continue
        correlation = np.correlate(values, values, mode="full")[values.size - 1 :]
        overlap = np.arange(values.size, 0, -1)
        correlation = correlation / overlap
        correlation /= correlation[0]
        crossing = np.flatnonzero(correlation <= np.exp(-1.0))
        if crossing.size:
            lengths.append(float(distance[crossing[0]] - distance[0]))
    return float(np.mean(lengths)) if lengths else None


def _roughness_metrics(
    surface: PreparedSurface,
    height: np.ndarray,
) -> dict[str, float]:
    valid = surface.valid_mask & np.isfinite(height)
    design = np.column_stack(
        (surface.x[valid], surface.y[valid], np.ones(np.count_nonzero(valid)))
    )
    coefficients, *_ = np.linalg.lstsq(design, height[valid], rcond=None)
    trend = coefficients[0] * surface.x + coefficients[1] * surface.y + coefficients[2]
    residual = np.where(valid, height - trend, np.nan)
    dz_dx, dz_dy = surface_gradients(height, surface)
    values = residual[valid]
    return {
        "arithmetic_roughness_ra": float(np.mean(np.abs(values))),
        "root_mean_square_roughness_rq": float(np.sqrt(np.mean(values**2))),
        "peak_to_valley_height": float(np.ptp(values)),
        "height_standard_deviation": float(np.std(values)),
        "slope_x_standard_deviation": float(np.std(dz_dx[valid])),
        "slope_y_standard_deviation": float(np.std(dz_dy[valid])),
        "slope_magnitude_mean": float(np.mean(np.hypot(dz_dx[valid], dz_dy[valid]))),
    }


def autocorrelation_map(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    centered = np.where(valid, values - np.nanmean(values[valid]), 0.0)
    mask = valid.astype(float)
    spectrum = np.fft.fft2(centered)
    numerator = np.fft.ifft2(spectrum * np.conj(spectrum)).real
    mask_spectrum = np.fft.fft2(mask)
    overlap = np.fft.ifft2(mask_spectrum * np.conj(mask_spectrum)).real
    correlation = np.divide(
        numerator,
        overlap,
        out=np.zeros_like(numerator),
        where=overlap > 0,
    )
    correlation = np.fft.fftshift(correlation)
    maximum = float(np.max(np.abs(correlation)))
    return correlation / maximum if maximum > 0 else correlation


def roughness_analysis(
    surface: PreparedSurface,
    x_profiles: ProfileSet,
    config: CharacterizationConfig,
) -> tuple[dict[str, object], list[dict[str, object]], dict[str, np.ndarray], list[str]]:
    """Analyze upper, lower, and mid walls automatically along X and Y."""

    y_profiles = build_profile_set(
        surface,
        x_profiles.transverse_xy,
        -x_profiles.direction_xy,
    )
    summary: dict[str, object] = {}
    fit_rows: list[dict[str, object]] = []
    arrays: dict[str, np.ndarray] = {}
    warnings: list[str] = []
    seed_offset = 0
    for surface_name, height in (
        ("lower", surface.lower),
        ("upper", surface.upper),
        ("mid", surface.mid),
    ):
        metrics = _roughness_metrics(surface, height)
        directional_profiles = {
            "X": _clean_profiles(surface, height, x_profiles),
            "Y": _clean_profiles(surface, height, y_profiles),
        }
        metrics["correlation_length_x"] = _autocorrelation_length(
            directional_profiles["X"]
        )
        metrics["correlation_length_y"] = _autocorrelation_length(
            directional_profiles["Y"]
        )
        x_length = metrics["correlation_length_x"]
        y_length = metrics["correlation_length_y"]
        metrics["correlation_anisotropy_ratio"] = (
            max(x_length, y_length) / min(x_length, y_length)
            if x_length and y_length
            else None
        )
        summary[surface_name] = metrics
        for direction, profiles in directional_profiles.items():
            for method in ("structure_function", "power_spectral_density"):
                fit = _hurst_fit(
                    profiles,
                    method=method,
                    surface_name=surface_name,
                    direction=direction,
                    config=config,
                    seed_offset=seed_offset,
                )
                seed_offset += 1
                row = {
                    "surface": fit.surface,
                    "direction": fit.direction,
                    "method": fit.method,
                    "hurst_exponent": fit.exponent,
                    "slope": fit.slope,
                    "intercept": fit.intercept,
                    "r_squared": fit.r_squared,
                    "confidence_95_low": fit.confidence_low,
                    "confidence_95_high": fit.confidence_high,
                    "points_used": fit.points_used,
                    "scale_min": fit.scale_min,
                    "scale_max": fit.scale_max,
                    "reliable": fit.reliable,
                    "warning": fit.warning,
                    "profile_fractal_dimension_2_minus_h": (
                        2.0 - fit.exponent if fit.exponent is not None else None
                    ),
                    "surface_graph_dimension_3_minus_h": (
                        3.0 - fit.exponent if fit.exponent is not None else None
                    ),
                }
                fit_rows.append(row)
                prefix = f"hurst_{surface_name}_{direction}_{method}"
                arrays[f"{prefix}_scale"] = fit.scale
                arrays[f"{prefix}_response"] = fit.response
                arrays[f"{prefix}_fit"] = fit.fitted_response
                if fit.warning:
                    warnings.append(
                        f"{surface_name} {direction} {method}: {fit.warning}"
                    )
    arrays["mid_surface_autocorrelation"] = autocorrelation_map(
        surface.mid,
        surface.valid_mask,
    )
    return summary, fit_rows, arrays, warnings
