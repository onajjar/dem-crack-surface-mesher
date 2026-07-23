from pathlib import Path

from castem_pipeline_gui_scientific import ScientificApp

ROOT = Path(__file__).resolve().parents[1]


class _Variable:
    def __init__(self, value=None) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class _Notebook:
    def __init__(self) -> None:
        self.selected = None

    def select(self, tab) -> None:
        self.selected = tab


def test_deap_toolbar_example_loads_bundled_raw_hdf5_case() -> None:
    app = object.__new__(ScientificApp)
    app._suspend_dirty = False
    variable_names = (
        "surface_mode_var",
        "dgibi_var",
        "fiss_dgibi_var",
        "workdir_var",
        "castem_version_var",
        "csv_x_var",
        "csv_y_var",
        "csv_zmin_var",
        "csv_zmax_var",
        "deap_orientation_var",
        "deap_magnification_var",
        "deap_bounding_box_var",
        "re_ti_var",
        "re_crpa_var",
        "re_smfa_var",
        "re_numspa_var",
        "re_opmin_var",
        "nelem_x_var",
        "nelem_y_var",
        "nelem_z_var",
        "re_tol_var",
        "re_fact_z_var",
        "num_el_fill_var",
        "re_fact_hole_var",
        "opti_med_var",
        "opti_stl_var",
        "opti_visu_var",
        "do_merge_var",
        "solver_mode_var",
        "holes_enabled_var",
    )
    for name in variable_names:
        setattr(app, name, _Variable())
    app.hole_shape_rows = []
    app.notebook = _Notebook()
    app.input_tab = object()
    app._refresh_surface_mode = lambda: None
    app._toggle_holes = lambda: None
    app._update_method_summary = lambda: None
    validated: list[str] = []
    app._validate_inputs = lambda operation="mesh": validated.append(operation) or True

    app._load_deap_example()

    assert app.surface_mode_var.get() == "Fit DEAP results (Python)"
    assert Path(app.workdir_var.get()) == ROOT / "examples" / "deap" / "1_simple" / "results"
    assert (Path(app.workdir_var.get()) / "deap_post.h5").is_file()
    assert (Path(app.workdir_var.get()) / "deap_output.h5").is_file()
    assert app.deap_orientation_var.get() == "XY"
    assert (
        app.re_ti_var.get(),
        app.re_crpa_var.get(),
        app.re_smfa_var.get(),
        app.re_numspa_var.get(),
        app.re_opmin_var.get(),
    ) == ("10", "1", "0.6", "20", "1e-5")
    assert app.solver_mode_var.get() == "python"
    assert app.holes_enabled_var.get() is False
    assert app.notebook.selected is app.input_tab
    assert validated == ["mesh"]
