from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest

from castem_pipeline_gui_scientific import ScientificApp
from castem_pipeline_headless import load_setup
from dataset_naming import parse_csv_filename_metadata, parse_csv_set_metadata

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples" / "scientific-run.ini"


class _Variable:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class _Entry:
    def __init__(self) -> None:
        self.state = "normal"

    def configure(self, *, state: str) -> None:
        self.state = state


class _Frame:
    def grid(self) -> None:
        pass

    def grid_remove(self) -> None:
        pass


def test_canonical_csv_name_decodes_dataset_metadata() -> None:
    metadata = parse_csv_filename_metadata(
        "zfit_zmax_ti50_crpa2_smfa7_numsp80_opmin3.csv"
    )

    assert metadata.ti == 50
    assert metadata.crpa == 2
    assert metadata.smfa == 0.07
    assert metadata.numspa == 80
    assert metadata.opmin == 3e-6
    assert metadata.ui_values == ("50", "2", "0.07", "80", "3e-06")


def test_csv_set_rejects_inconsistent_filename_metadata() -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        parse_csv_set_metadata(
            (
                "xrange_ti50_crpa1_smfa5_numsp50_opmin1.csv",
                "yrange_ti60_crpa1_smfa5_numsp50_opmin1.csv",
            )
        )


def test_legacy_csv_name_without_opmin_uses_unchanged_default() -> None:
    metadata = parse_csv_filename_metadata(
        "xrange_ti50_crpa1_smfa5_numsp50.csv"
    )

    assert metadata.ui_values == ("50", "1", "0.05", "50", "1e-06")


def _runtime_directory(name: str) -> Path:
    result = ROOT / "_runtime" / name / uuid4().hex
    result.mkdir(parents=True)
    return result


def test_csv_headless_mode_ignores_entered_naming_and_uses_filenames() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    text = text.replace("ti = 60", "ti = 999")
    text = text.replace("crpa = 1", "crpa = 9")
    config = _runtime_directory("test-csv-naming") / "csv-derived.ini"
    config.write_text(text, encoding="utf-8")

    setup = load_setup(config)

    assert setup.params.re_ti == 60
    assert setup.params.re_crpa == 1
    assert setup.params.re_smfa == 0.05
    assert setup.params.re_numspa == 50
    assert setup.params.re_opmin == 1e-6


def test_csv_headless_mode_does_not_require_naming_section() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    text = re.sub(
        r"(?ms)^\[naming\]\s*.*?(?=^\[mesh\])",
        "",
        text,
    )
    config = _runtime_directory("test-csv-naming") / "csv-without-naming.ini"
    config.write_text(text, encoding="utf-8")

    setup = load_setup(config)

    assert setup.params.re_ti == 60
    assert setup.params.re_smfa == 0.05


def test_workbench_metadata_is_editable_only_for_deap_and_derived_for_csv() -> None:
    app = object.__new__(ScientificApp)
    app._suspend_dirty = False
    app.surface_mode_var = _Variable("CSV files")
    app.surface_frames = {
        "csv": _Frame(),
        "deap": _Frame(),
        "fractal": _Frame(),
        "constant": _Frame(),
    }
    app.csv_x_var = _Variable(
        "xrange_ti50_crpa2_smfa7_numsp80_opmin3.csv"
    )
    app.csv_y_var = _Variable(
        "yrange_ti50_crpa2_smfa7_numsp80_opmin3.csv"
    )
    app.csv_zmin_var = _Variable(
        "zfit_zmin_ti50_crpa2_smfa7_numsp80_opmin3.csv"
    )
    app.csv_zmax_var = _Variable(
        "zfit_zmax_ti50_crpa2_smfa7_numsp80_opmin3.csv"
    )
    app._csv_metadata_variables = tuple(_Variable("") for _index in range(5))
    app._csv_metadata_defaults = ("60", "1", "0.05", "50", "1e-6")
    app._csv_metadata_entries = tuple(_Entry() for _index in range(5))
    app._update_fractal_relation = lambda: None

    app._refresh_surface_mode()

    assert tuple(variable.get() for variable in app._csv_metadata_variables) == (
        "50",
        "2",
        "0.07",
        "80",
        "3e-06",
    )
    assert {entry.state for entry in app._csv_metadata_entries} == {"disabled"}

    app.surface_mode_var.set("Fit DEAP results (Python)")
    app._refresh_surface_mode()
    assert {entry.state for entry in app._csv_metadata_entries} == {"normal"}

    app.surface_mode_var.set("Synthetic fractal")
    app._refresh_surface_mode()
    assert tuple(variable.get() for variable in app._csv_metadata_variables) == (
        "60",
        "1",
        "0.05",
        "50",
        "1e-6",
    )
    assert {entry.state for entry in app._csv_metadata_entries} == {"disabled"}
