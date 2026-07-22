from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from castem_pipeline_gui_scientific import ScientificApp
from castem_pipeline_headless import (
    _materialize_surface_inputs,
    load_setup,
    validate_setup,
)
from deap_crack_surface import quadratic_loess_surface
from surface_generation import build_surface_grid

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_CONFIG = ROOT / "examples" / "deap" / "1_simple" / "run.ini"


def test_simple_python_fit_matches_archived_matlab_surface() -> None:
    setup = load_setup(SIMPLE_CONFIG)
    fitted = build_surface_grid(setup.surface_source)
    csv_setup = load_setup(SIMPLE_CONFIG, surface_mode_override="csv")
    reference = build_surface_grid(csv_setup.surface_source)

    assert setup.workdir.name == "results"
    assert setup.surface_source.normalized_mode == "deap"
    assert fitted.metadata is not None
    assert fitted.metadata["component_nodes"] == 105
    np.testing.assert_allclose(fitted.x, reference.x, rtol=0.0, atol=1.0e-12)
    np.testing.assert_allclose(fitted.y, reference.y, rtol=0.0, atol=1.0e-12)
    np.testing.assert_allclose(fitted.zmin, reference.zmin, rtol=0.0, atol=1.0e-12)
    np.testing.assert_allclose(fitted.zmax, reference.zmax, rtol=0.0, atol=1.0e-12)
    assert np.all(fitted.opening >= 0.0)


def test_example_contract_validates_in_deap_and_csv_modes() -> None:
    setup = load_setup(SIMPLE_CONFIG)
    fitted = build_surface_grid(setup.surface_source)
    reference_setup = load_setup(SIMPLE_CONFIG, surface_mode_override="csv")

    assert validate_setup(setup, surface_grid=fitted) == ()
    assert validate_setup(reference_setup) == ()


def test_scientific_workbench_exposes_python_fit_mode() -> None:
    assert ScientificApp._surface_mode_key("Fit DEAP results (Python)") == "deap"


def test_deap_materialization_writes_csvs_and_fit_report() -> None:
    setup = load_setup(SIMPLE_CONFIG)
    runtime = ROOT / "_runtime" / "tests" / "deap-materialization"
    output = runtime / "_generated_surface_inputs"
    runtime_setup = replace(
        setup,
        workdir=runtime,
        csv_x=output / "xrange_generated.csv",
        csv_y=output / "yrange_generated.csv",
        csv_zmin=output / "zfit_zmin_generated.csv",
        csv_zmax=output / "zfit_zmax_generated.csv",
    )

    grid = _materialize_surface_inputs(runtime_setup)
    report = json.loads((output / "deap-fit-report.json").read_text(encoding="utf-8"))

    assert grid.mode == "deap"
    assert all(path.is_file() for path in (
        runtime_setup.csv_x,
        runtime_setup.csv_y,
        runtime_setup.csv_zmin,
        runtime_setup.csv_zmax,
    ))
    assert report["surface_mode"] == "deap"
    assert report["fit"]["algorithm"].startswith("normalized 2D quadratic LOESS")


def test_quadratic_loess_recovers_quadratic_surface() -> None:
    axis = np.linspace(-1.0, 1.0, 9)
    x, y = np.meshgrid(axis, axis)
    z = 2.0 + 0.3 * x - 0.4 * y + 0.2 * x * x + 0.1 * x * y - 0.5 * y * y
    query_axis = np.linspace(-0.8, 0.8, 7)
    query_x, query_y = np.meshgrid(query_axis, query_axis)
    expected = (
        2.0
        + 0.3 * query_x
        - 0.4 * query_y
        + 0.2 * query_x * query_x
        + 0.1 * query_x * query_y
        - 0.5 * query_y * query_y
    )

    actual = quadratic_loess_surface(
        x.ravel(),
        y.ravel(),
        z.ravel(),
        query_x,
        query_y,
        span=0.5,
    )

    np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1.0e-12)
