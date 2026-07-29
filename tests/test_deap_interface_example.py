from pathlib import Path
from unittest.mock import patch

from castem_pipeline_gui_scientific import (
    ARTICLE_URL,
    DEFAULT_SOLVER_MODE,
    ScientificApp,
)

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


class _Widget:
    def __init__(self) -> None:
        self.state = "normal"

    def configure(self, *, state: str) -> None:
        self.state = state


def test_python_only_is_the_default_solver_mode() -> None:
    assert DEFAULT_SOLVER_MODE == "python_only"


def test_python_only_disables_castem_controls_and_switching_back_enables_them() -> None:
    app = object.__new__(ScientificApp)
    app.solver_mode_var = _Variable("python_only")
    app.opti_visu_var = _Variable(True)
    app.gmsh_checkbox = _Widget()
    app._castem_mesh_widgets = tuple(_Widget() for _index in range(3))

    app._refresh_solver_mode_controls()

    assert app.opti_visu_var.get() is False
    assert app.gmsh_checkbox.state == "disabled"
    assert {widget.state for widget in app._castem_mesh_widgets} == {"disabled"}

    app.solver_mode_var.set("python")
    app._refresh_solver_mode_controls()

    assert app.gmsh_checkbox.state == "normal"
    assert {widget.state for widget in app._castem_mesh_widgets} == {"normal"}


def test_fractal_toolbar_loads_the_advanced_source_free_example() -> None:
    app = object.__new__(ScientificApp)
    app._suspend_dirty = False
    variable_names = (
        "surface_mode_var",
        "fractal_parameter_var",
        "fractal_value_var",
        "fractal_value_y_var",
        "surface_points_x_var",
        "surface_points_y_var",
        "surface_size_x_var",
        "surface_size_y_var",
        "surface_center_x_var",
        "surface_center_y_var",
        "fractal_rms_height_var",
        "fractal_upper_rms_height_var",
        "fractal_aperture_var",
        "fractal_minimum_aperture_var",
        "fractal_wall_correlation_var",
        "fractal_rolloff_x_var",
        "fractal_rolloff_y_var",
        "fractal_distribution_var",
        "fractal_lognormal_shape_var",
        "fractal_seed_var",
        "solver_mode_var",
        "opti_visu_var",
        "workdir_var",
    )
    for name in variable_names:
        setattr(app, name, _Variable())
    app.notebook = _Notebook()
    app.input_tab = object()
    app._load_documented_example = lambda validate=False: None
    app._refresh_surface_mode = lambda: None
    app._refresh_fractal_distribution_controls = lambda: None
    app._update_fractal_relation = lambda: None
    app._update_method_summary = lambda: None
    validated: list[str] = []
    app._validate_inputs = lambda operation="mesh": validated.append(operation) or True

    app._load_fractal_example()

    assert app.surface_mode_var.get() == "Synthetic fractal"
    assert (app.fractal_value_var.get(), app.fractal_value_y_var.get()) == (
        "0.85",
        "0.55",
    )
    assert app.fractal_distribution_var.get() == "Lognormal"
    assert app.fractal_wall_correlation_var.get() == "0.0"
    assert (
        app.fractal_rolloff_x_var.get(),
        app.fractal_rolloff_y_var.get(),
    ) == ("0.4", "0.12")
    assert app.solver_mode_var.get() == "python_only"
    assert app.opti_visu_var.get() is False
    assert app.notebook.selected is app.input_tab
    assert validated == ["mesh"]


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
        "chambers_enabled_var",
    )
    for name in variable_names:
        setattr(app, name, _Variable())
    app.hole_shape_rows = []
    app.notebook = _Notebook()
    app.input_tab = object()
    app._refresh_surface_mode = lambda: None
    app._toggle_holes = lambda: None
    app._toggle_chambers = lambda: None
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


def test_article_footer_opens_publisher_doi() -> None:
    with patch("castem_pipeline_gui_scientific.webbrowser.open_new_tab") as open_tab:
        ScientificApp._open_article()

    open_tab.assert_called_once_with(ARTICLE_URL)
