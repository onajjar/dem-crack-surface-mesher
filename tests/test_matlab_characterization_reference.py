import json
from pathlib import Path

import numpy as np

from crack_characterization import CharacterizationConfig, characterize_surface
from surface_generation import SurfaceGrid

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = (
    ROOT / "docs" / "validation" / "matlab-characterization-reference.json"
)


def _surface(aperture: np.ndarray) -> SurfaceGrid:
    y_axis = np.linspace(0.0, 0.8, 9)
    x_axis = np.linspace(0.0, 1.2, aperture.shape[1])
    x, y = np.meshgrid(x_axis, y_axis)
    opening = np.broadcast_to(aperture, x.shape)
    return SurfaceGrid(
        x=x,
        y=y,
        zmin=-0.5 * opening,
        zmax=0.5 * opening,
        mode="matlab_reference",
    )


def _characterize(grid: SurfaceGrid):
    return characterize_surface(
        grid,
        CharacterizationConfig(
            aperture_method="global_z",
            flow_direction="X",
            hurst_bootstrap_samples=0,
            generate_figures=False,
        ),
    )


def test_python_matches_matlab_r2025b_planar_and_series_resistance_reference() -> None:
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    planar = _characterize(_surface(np.full((1, 25), 2.0e-4)))
    planar_aperture = planar.summary["aperture"]["statistics"]
    planar_hydraulic = planar.summary["hydraulic"]
    matlab_planar = reference["planar_constant"]

    assert np.isclose(
        planar_aperture["arithmetic_mean"],
        matlab_planar["arithmetic_mean_aperture"],
        rtol=1.0e-14,
    )
    assert np.isclose(
        planar_aperture["global_cubic_mean"],
        matlab_planar["cubic_mean_aperture"],
        rtol=1.0e-14,
    )
    assert np.isclose(
        planar_hydraulic["global_equivalent_hydraulic_aperture"],
        matlab_planar["equivalent_aperture"],
        rtol=1.0e-14,
    )
    assert np.isclose(
        planar.summary["tortuosity"]["mid"]["mean"],
        matlab_planar["geometrical_tortuosity"],
        rtol=0.0,
        atol=1.0e-15,
    )

    x_axis = np.linspace(0.0, 1.2, 31)
    varying_aperture = (1.0e-4 + 2.0e-4 * x_axis / 1.2)[None, :]
    varying = _characterize(_surface(varying_aperture))
    matlab_varying = reference["varying_aperture"]

    assert np.isclose(
        varying.summary["hydraulic"]["global_equivalent_hydraulic_aperture"],
        matlab_varying["equivalent_aperture"],
        rtol=1.0e-14,
    )
    assert np.isclose(
        varying.summary["aperture"]["statistics"]["global_cubic_mean"],
        matlab_varying["cubic_mean_aperture"],
        rtol=1.0e-14,
    )
