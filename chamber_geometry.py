"""Configuration and DGIBI patching for optional inlet/outlet chambers."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

MAIN_BLOCK_START = "************************** Main Program *******************************"
DEFAULT_CHAMBER_TEMPLATE = (
    Path(__file__).resolve().parent / "source_codes" / "castem_tool_chambers.dgibi"
)

CHAMBER_OUTPUT_NAMES = (
    "castem_mesh_surf_all.bdf",
    "castem_mesh_v_inlet.bdf",
    "castem_mesh_surf_inlet_all.bdf",
    "castem_mesh_surf_inlet_interface.bdf",
    "castem_mesh_surf_inlet_outer.bdf",
    "castem_mesh_surf_inlet_top.bdf",
    "castem_mesh_surf_inlet_bottom.bdf",
    "castem_mesh_surf_inlet_xmin.bdf",
    "castem_mesh_surf_inlet_xmax.bdf",
    "castem_mesh_v_outlet.bdf",
    "castem_mesh_surf_outlet_all.bdf",
    "castem_mesh_surf_outlet_interface.bdf",
    "castem_mesh_surf_outlet_outer.bdf",
    "castem_mesh_surf_outlet_top.bdf",
    "castem_mesh_surf_outlet_bottom.bdf",
    "castem_mesh_surf_outlet_xmin.bdf",
    "castem_mesh_surf_outlet_xmax.bdf",
)

CHAMBER_STL_SURFACES = (
    "castem_mesh_surf_all",
    "castem_mesh_surf_inlet_all",
    "castem_mesh_surf_inlet_interface",
    "castem_mesh_surf_inlet_outer",
    "castem_mesh_surf_inlet_top",
    "castem_mesh_surf_inlet_bottom",
    "castem_mesh_surf_inlet_xmin",
    "castem_mesh_surf_inlet_xmax",
    "castem_mesh_surf_outlet_all",
    "castem_mesh_surf_outlet_interface",
    "castem_mesh_surf_outlet_outer",
    "castem_mesh_surf_outlet_top",
    "castem_mesh_surf_outlet_bottom",
    "castem_mesh_surf_outlet_xmin",
    "castem_mesh_surf_outlet_xmax",
)


@dataclass(frozen=True)
class ChamberParameters:
    """Physical dimensions and graded discretization for both chambers."""

    enabled: bool = False
    height: float = 0.20
    inlet_length: float = 0.20
    outlet_length: float = 0.20
    inlet_height_elements: int = 10
    outlet_height_elements: int = 10
    inlet_length_elements: int = 10
    outlet_length_elements: int = 10
    inlet_height_ratio: float = 5.0
    outlet_height_ratio: float = 5.0
    inlet_length_ratio: float = 5.0
    outlet_length_ratio: float = 5.0

    def validated(self) -> ChamberParameters:
        """Return this immutable object after checking meshing constraints."""

        dimensions = {
            "height": self.height,
            "inlet_length": self.inlet_length,
            "outlet_length": self.outlet_length,
        }
        for name, value in dimensions.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"chambers {name} must be finite and > 0.")

        height_counts = {
            "inlet_height_elements": self.inlet_height_elements,
            "outlet_height_elements": self.outlet_height_elements,
        }
        for name, value in height_counts.items():
            if value < 2 or value % 2:
                raise ValueError(f"chambers {name} must be an even integer >= 2.")

        length_counts = {
            "inlet_length_elements": self.inlet_length_elements,
            "outlet_length_elements": self.outlet_length_elements,
        }
        for name, value in length_counts.items():
            if value < 1:
                raise ValueError(f"chambers {name} must be an integer >= 1.")

        ratios = {
            "inlet_height_ratio": self.inlet_height_ratio,
            "outlet_height_ratio": self.outlet_height_ratio,
            "inlet_length_ratio": self.inlet_length_ratio,
            "outlet_length_ratio": self.outlet_length_ratio,
        }
        for name, value in ratios.items():
            if not math.isfinite(value) or value < 1:
                raise ValueError(
                    f"chambers {name} must be finite and >= 1 so cells grow "
                    "away from the crack."
                )
        return self

    def report(self) -> dict[str, bool | float | int]:
        """Return stable JSON-ready keys for run reports."""

        return asdict(self)


def chambers_from_params(params: object) -> ChamberParameters:
    """Return attached chamber settings or the disabled defaults."""

    value = getattr(params, "chambers", None)
    return value if isinstance(value, ChamberParameters) else ChamberParameters()


def mesh_template_for_params(params: object, configured_template: Path) -> Path:
    """Select the validated chamber source only when chamber mode is enabled."""

    chambers = chambers_from_params(params)
    return DEFAULT_CHAMBER_TEMPLATE if chambers.enabled else configured_template


def _replace_required_assignment(block: str, name: str, expression: str) -> str:
    pattern = rf"(^\s*{re.escape(name)}\s*=\s*)(.*?)(\s*;)"
    replacement = rf"\g<1>{expression}\g<3>"
    patched, count = re.subn(
        pattern,
        replacement,
        block,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )
    if count != 1:
        raise ValueError(
            f"The chamber DGIBI must contain exactly one Main Program assignment for {name}."
        )
    return patched


def patch_chamber_program(program: str, chambers: ChamberParameters) -> str:
    """Patch every chamber assignment inside the DGIBI Main Program."""

    chambers.validated()
    if not chambers.enabled:
        return program
    marker = program.find(MAIN_BLOCK_START)
    if marker < 0:
        raise ValueError("Could not find the Main Program block in the chamber DGIBI.")
    head = program[:marker]
    block = program[marker:]
    assignments = (
        ("height_inlet", f"{chambers.height:.12g}"),
        ("height_outlet", "height_inlet"),
        ("length_inlet", f"{chambers.inlet_length:.12g}"),
        ("length_outlet", f"{chambers.outlet_length:.12g}"),
        ("nelem_height_inlet", str(chambers.inlet_height_elements)),
        ("nelem_height_outlet", str(chambers.outlet_height_elements)),
        ("nelem_length_inlet", str(chambers.inlet_length_elements)),
        ("nelem_length_outlet", str(chambers.outlet_length_elements)),
        ("re_fact_height_inlet", f"{chambers.inlet_height_ratio:.12g}"),
        ("re_fact_height_outlet", f"{chambers.outlet_height_ratio:.12g}"),
        ("re_fact_length_inlet", f"{chambers.inlet_length_ratio:.12g}"),
        ("re_fact_length_outlet", f"{chambers.outlet_length_ratio:.12g}"),
    )
    for name, expression in assignments:
        block = _replace_required_assignment(block, name, expression)
    return head + block
