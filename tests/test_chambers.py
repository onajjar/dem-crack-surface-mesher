from pathlib import Path

import pytest

import castem_pipeline_gui_t13 as baseline
from castem_pipeline_gui_python_holes import (
    expected_mesh_output_names,
    patch_mesh_program,
)
from castem_pipeline_gui_scientific import ScientificApp
from castem_pipeline_headless import load_setup, validate_setup
from chamber_geometry import (
    CHAMBER_OUTPUT_NAMES,
    ChamberParameters,
)
from stl_export import boundary_output_pairs

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples" / "chambers" / "run.ini"
MESH_TEMPLATE = ROOT / "source_codes" / "castem_tool.dgibi"


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


def test_headless_chamber_example_uses_single_template_and_validated_parameters() -> None:
    setup = load_setup(CONFIG)

    assert setup.mesh_template == MESH_TEMPLATE
    assert setup.chambers == ChamberParameters(enabled=True)
    assert setup.params.nelem_x == setup.params.nelem_y == 2
    assert setup.params.nelem_z == 30
    assert setup.params.num_el_fill == 15
    assert setup.params.opti_stl == 1
    assert validate_setup(setup) == (64, 64)


def test_repository_has_one_maintained_castem_mesh_source() -> None:
    assert tuple((ROOT / "source_codes").glob("castem_tool*.dgibi")) == (
        MESH_TEMPLATE,
    )
    assert not tuple((ROOT / "examples" / "chambers").glob("*.dgibi"))


def test_chamber_source_is_patched_without_displacement() -> None:
    params = baseline.CastemMainParams(
        nelem_x=2,
        nelem_y=2,
        nelem_z=30,
        re_fact_z=1.025,
        num_el_fill=15,
        re_fact_hole=5.0,
        holes_enabled=False,
    )
    params.chambers = ChamberParameters(
        enabled=True,
        height=0.30,
        inlet_length=0.25,
        outlet_length=0.35,
        inlet_height_elements=12,
        outlet_height_elements=14,
        inlet_length_elements=8,
        outlet_length_elements=9,
        inlet_height_ratio=3.0,
        outlet_height_ratio=4.0,
        inlet_length_ratio=5.0,
        outlet_length_ratio=6.0,
    )

    program = patch_mesh_program(
        MESH_TEMPLATE.read_text(encoding="utf-8"),
        params,
    )

    expected = (
        "height_inlet = 0.3",
        "height_outlet = height_inlet",
        "length_inlet = 0.25",
        "length_outlet = 0.35",
        "nelem_height_inlet = 12",
        "nelem_height_outlet = 14",
        "nelem_length_inlet = 8",
        "nelem_length_outlet = 9",
        "re_fact_height_inlet = 3",
        "re_fact_height_outlet = 4",
        "re_fact_length_inlet = 5",
        "re_fact_length_outlet = 6",
    )
    assert all(text in program for text in expected)
    active = "\n".join(
        line for line in program.splitlines() if not line.lstrip().startswith("*")
    ).upper()
    assert "DISPLACE" not in active
    assert "DEPL" not in active
    assert "INT_COMP" not in active
    assert program.count("Step5: Create the inlet and outlet chambers") == 1
    assert "single maintained\n* source_codes/castem_tool.dgibi template" in program


def test_chamber_outputs_are_required_only_when_enabled() -> None:
    params = baseline.CastemMainParams()
    params.chambers = ChamberParameters(enabled=True)

    names = expected_mesh_output_names(params)

    assert set(CHAMBER_OUTPUT_NAMES).issubset(names)
    params.chambers = ChamberParameters()
    assert set(CHAMBER_OUTPUT_NAMES).isdisjoint(expected_mesh_output_names(params))


def test_chamber_stl_mapping_includes_every_named_surface() -> None:
    output = ROOT / "_runtime" / "test-chamber-stl-mapping"
    pairs = boundary_output_pairs(
        output,
        hole_count=2,
        include_chambers=True,
    )
    sources = {source.name for source, _target in pairs}

    assert len(pairs) == 24
    assert "castem_mesh_surf_inlet_interface.bdf" in sources
    assert "castem_mesh_surf_outlet_outer.bdf" in sources


def test_interface_chamber_example_loads_the_validated_values() -> None:
    app = object.__new__(ScientificApp)
    app._suspend_dirty = False
    variables = (
        "workdir_var",
        "nelem_x_var",
        "nelem_y_var",
        "nelem_z_var",
        "re_fact_z_var",
        "num_el_fill_var",
        "re_fact_hole_var",
        "opti_stl_var",
        "opti_visu_var",
        "do_merge_var",
        "solver_mode_var",
        "chambers_enabled_var",
        "chamber_height_var",
        "chamber_inlet_length_var",
        "chamber_outlet_length_var",
        "chamber_inlet_height_elements_var",
        "chamber_outlet_height_elements_var",
        "chamber_inlet_length_elements_var",
        "chamber_outlet_length_elements_var",
        "chamber_inlet_height_ratio_var",
        "chamber_outlet_height_ratio_var",
        "chamber_inlet_length_ratio_var",
        "chamber_outlet_length_ratio_var",
    )
    for name in variables:
        setattr(app, name, _Variable())
    app.notebook = _Notebook()
    app.mesh_tab = object()
    app._load_documented_example = lambda validate=False: None
    app._toggle_chambers = lambda: None
    app._update_method_summary = lambda: None
    validated: list[str] = []
    app._validate_inputs = lambda operation="mesh": validated.append(operation) or True

    app._load_chamber_example()

    assert app.chambers_enabled_var.get() is True
    assert app.solver_mode_var.get() == "python"
    assert app.nelem_x_var.get() == app.nelem_y_var.get() == "2"
    assert app.nelem_z_var.get() == "30"
    assert app.re_fact_z_var.get() == "1.025"
    assert app.num_el_fill_var.get() == "15"
    assert app.opti_stl_var.get() is True
    assert app.notebook.selected is app.mesh_tab
    assert validated == ["mesh"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("height", 0.0, "height"),
        ("inlet_height_elements", 9, "even integer"),
        ("outlet_length_elements", 0, "integer >= 1"),
        ("inlet_length_ratio", 0.5, "finite and >= 1"),
    ),
)
def test_invalid_chamber_values_are_rejected(
    field: str,
    value: float,
    message: str,
) -> None:
    values = ChamberParameters(enabled=True).__dict__ | {field: value}

    with pytest.raises(ValueError, match=message):
        ChamberParameters(**values).validated()
