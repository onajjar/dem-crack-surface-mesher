"""Configuration and DGIBI patching for optional inlet/outlet chambers."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass

from python_hole_interpolation import replace_hole_interpolation_block_names

MAIN_BLOCK_START = "************************** Main Program *******************************"
HOLE_PARAMETER_ANCHOR = "***** Parameters for hole filling (if any)*****"
EXPORT_ANCHOR = "******** Step5: Export the results ***************"
DISPLACE_PROCEDURE_START = "****Displace a geometry   ******"
DISPLACE_PROCEDURE_END = "FINP ;"

CHAMBER_PARAMETER_TEMPLATE = """***** Parameters for inlet and outlet chambers *****
* Heights are the added dimensions: one half is extruded above the crack and
* one half below it. Height element counts must therefore be positive and even.
height_inlet = {height} ;
height_outlet = height_inlet ;
length_inlet = {inlet_length} ;
length_outlet = {outlet_length} ;
nelem_height_inlet = {inlet_height_elements} ;
nelem_height_outlet = {outlet_height_elements} ;
nelem_length_inlet = {inlet_length_elements} ;
nelem_length_outlet = {outlet_length_elements} ;
re_fact_height_inlet = {inlet_height_ratio} ;
re_fact_height_outlet = {outlet_height_ratio} ;
re_fact_length_inlet = {inlet_length_ratio} ;
re_fact_length_outlet = {outlet_length_ratio} ;
"""

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

CHAMBER_CONSTRUCTION = """******** Step5: Create the inlet and outlet chambers ***************
* This optional block is injected by Python from the single maintained
* source_codes/castem_tool.dgibi template.
* The crack flow direction is global Y: inlet at ymin and outlet at ymax.
* Negative layer counts activate DINI/DFIN grading. The smallest cells are at
* the crack/chamber interfaces; cells grow towards the remote box boundaries.

nelem_half_height_inlet = ENTI (nelem_height_inlet / 2.0) ;
nelem_half_height_outlet = ENTI (nelem_height_outlet / 2.0) ;

re_dens_length_inlet = length_inlet / nelem_length_inlet ;
re_dens_length_outlet = length_outlet / nelem_length_outlet ;
re_dens_height_inlet = (0.5 * height_inlet) / nelem_half_height_inlet ;
re_dens_height_outlet = (0.5 * height_outlet) / nelem_half_height_outlet ;

* Recover both halves of each complete crack end face before their volume
* union. FACE 3 above is retained unchanged for the legacy wall/hole exports.
surf_cr1_all = ENVE vo_cr1 ;
surf_cr2_all = ENVE vo_cr2 ;
po_cr1_inlet = (surf_cr1_all COOR 2) POIN 'COMPRIS' (ymin-re_tol) (ymin+re_tol) ;
po_cr2_inlet = (surf_cr2_all COOR 2) POIN 'COMPRIS' (ymin-re_tol) (ymin+re_tol) ;
po_cr1_outlet = (surf_cr1_all COOR 2) POIN 'COMPRIS' (ymax-re_tol) (ymax+re_tol) ;
po_cr2_outlet = (surf_cr2_all COOR 2) POIN 'COMPRIS' (ymax-re_tol) (ymax+re_tol) ;
surf_cr_inlet = ELIM (
    (surf_cr1_all ELEM 'APPUYE' 'STRICTEMENT' po_cr1_inlet) ET
    (surf_cr2_all ELEM 'APPUYE' 'STRICTEMENT' po_cr2_inlet)
    ) re_tol ;
surf_cr_outlet = ELIM (
    (surf_cr1_all ELEM 'APPUYE' 'STRICTEMENT' po_cr1_outlet) ET
    (surf_cr2_all ELEM 'APPUYE' 'STRICTEMENT' po_cr2_outlet)
    ) re_tol ;
surf_cr_inlet = ORIE surf_cr_inlet 'POINT' (0.0 -10000.0 0.0) ;
surf_cr_outlet = ORIE surf_cr_outlet 'POINT' (0.0 10000.0 0.0) ;

* First extrude the complete crack inlet and outlet faces in global Y.
vo_ch_in_base = surf_cr_inlet VOLU (-1*nelem_length_inlet)
    'DINI' re_dens_length_inlet
    'DFIN' (re_fact_length_inlet*re_dens_length_inlet)
    'TRAN' (0.0 (-1.0*length_inlet) 0.0) ;

vo_ch_out_base = surf_cr_outlet VOLU (-1*nelem_length_outlet)
    'DINI' re_dens_length_outlet
    'DFIN' (re_fact_length_outlet*re_dens_length_outlet)
    'TRAN' (0.0 length_outlet 0.0) ;

* Build references for the upper/lower lateral faces of both base extrusions,
* then extract those faces from FACE 3 as requested.
cont_zmax = CONT surf_zmax ;
cont_zmin = CONT surf_zmin ;

po_li_in_up = (cont_zmax COOR 2) POIN 'COMPRIS' (ymin-re_tol) (ymin+re_tol) ;
po_li_in_low = (cont_zmin COOR 2) POIN 'COMPRIS' (ymin-re_tol) (ymin+re_tol) ;
li_in_up = cont_zmax ELEM 'APPUYE' 'STRICTEMENT' po_li_in_up ;
li_in_low = cont_zmin ELEM 'APPUYE' 'STRICTEMENT' po_li_in_low ;

po_li_out_up = (cont_zmax COOR 2) POIN 'COMPRIS' (ymax-re_tol) (ymax+re_tol) ;
po_li_out_low = (cont_zmin COOR 2) POIN 'COMPRIS' (ymax-re_tol) (ymax+re_tol) ;
li_out_up = cont_zmax ELEM 'APPUYE' 'STRICTEMENT' po_li_out_up ;
li_out_low = cont_zmin ELEM 'APPUYE' 'STRICTEMENT' po_li_out_low ;

surf_ch_in_up_ref = li_in_up TRAN (-1*nelem_length_inlet)
    'DINI' re_dens_length_inlet
    'DFIN' (re_fact_length_inlet*re_dens_length_inlet)
    (0.0 (-1.0*length_inlet) 0.0) ;
surf_ch_in_low_ref = li_in_low TRAN (-1*nelem_length_inlet)
    'DINI' re_dens_length_inlet
    'DFIN' (re_fact_length_inlet*re_dens_length_inlet)
    (0.0 (-1.0*length_inlet) 0.0) ;

surf_ch_out_up_ref = li_out_up TRAN (-1*nelem_length_outlet)
    'DINI' re_dens_length_outlet
    'DFIN' (re_fact_length_outlet*re_dens_length_outlet)
    (0.0 length_outlet 0.0) ;
surf_ch_out_low_ref = li_out_low TRAN (-1*nelem_length_outlet)
    'DINI' re_dens_length_outlet
    'DFIN' (re_fact_length_outlet*re_dens_length_outlet)
    (0.0 length_outlet 0.0) ;

fac_ch_in_base = ENVE vo_ch_in_base ;
fac_ch_out_base = ENVE vo_ch_out_base ;
ELIM (fac_ch_in_base ET surf_ch_in_up_ref ET surf_ch_in_low_ref) re_tol ;
ELIM (fac_ch_out_base ET surf_ch_out_up_ref ET surf_ch_out_low_ref) re_tol ;

surf_ch_in_up = fac_ch_in_base ELEM 'APPUYE' 'STRICTEMENT' surf_ch_in_up_ref ;
surf_ch_in_low = fac_ch_in_base ELEM 'APPUYE' 'STRICTEMENT' surf_ch_in_low_ref ;
surf_ch_out_up = fac_ch_out_base ELEM 'APPUYE' 'STRICTEMENT' surf_ch_out_up_ref ;
surf_ch_out_low = fac_ch_out_base ELEM 'APPUYE' 'STRICTEMENT' surf_ch_out_low_ref ;
surf_ch_in_up = ORIE surf_ch_in_up 'POINT' (0.0 0.0 10000.0) ;
surf_ch_in_low = ORIE surf_ch_in_low 'POINT' (0.0 0.0 -10000.0) ;
surf_ch_out_up = ORIE surf_ch_out_up 'POINT' (0.0 0.0 10000.0) ;
surf_ch_out_low = ORIE surf_ch_out_low 'POINT' (0.0 0.0 -10000.0) ;

* Extrude the extracted upper and lower surfaces by half the chamber height.
vo_ch_in_up = surf_ch_in_up VOLU (-1*nelem_half_height_inlet)
    'DINI' re_dens_height_inlet
    'DFIN' (re_fact_height_inlet*re_dens_height_inlet)
    'TRAN' (0.0 0.0 (0.5*height_inlet)) ;
vo_ch_in_low = surf_ch_in_low VOLU (-1*nelem_half_height_inlet)
    'DINI' re_dens_height_inlet
    'DFIN' (re_fact_height_inlet*re_dens_height_inlet)
    'TRAN' (0.0 0.0 (-0.5*height_inlet)) ;

vo_ch_out_up = surf_ch_out_up VOLU (-1*nelem_half_height_outlet)
    'DINI' re_dens_height_outlet
    'DFIN' (re_fact_height_outlet*re_dens_height_outlet)
    'TRAN' (0.0 0.0 (0.5*height_outlet)) ;
vo_ch_out_low = surf_ch_out_low VOLU (-1*nelem_half_height_outlet)
    'DINI' re_dens_height_outlet
    'DFIN' (re_fact_height_outlet*re_dens_height_outlet)
    'TRAN' (0.0 0.0 (-0.5*height_outlet)) ;

vo_ch_in = ELIM (vo_ch_in_base ET vo_ch_in_up ET vo_ch_in_low) re_tol ;
vo_ch_out = ELIM (vo_ch_out_base ET vo_ch_out_up ET vo_ch_out_low) re_tol ;
vo_all = ELIM (vo_cr ET vo_ch_in ET vo_ch_out) re_tol ;

* Extract complete chamber envelopes and each recognizable boundary.
surf_ch_in_all = ENVE vo_ch_in ;
surf_ch_out_all = ENVE vo_ch_out ;
surf_all = ENVE vo_all ;

po_ch_in_interface = (surf_ch_in_all COOR 2) POIN 'COMPRIS' (ymin-re_tol) (ymin+re_tol) ;
surf_ch_in_interface = surf_ch_in_all ELEM 'APPUYE' 'STRICTEMENT' po_ch_in_interface ;
po_ch_in_outer = (surf_ch_in_all COOR 2) POIN 'COMPRIS'
    (ymin-length_inlet-re_tol) (ymin-length_inlet+re_tol) ;
surf_ch_in_outer = surf_ch_in_all ELEM 'APPUYE' 'STRICTEMENT' po_ch_in_outer ;
po_ch_in_xmin = (surf_ch_in_all COOR 1) POIN 'COMPRIS' (xmin-re_tol) (xmin+re_tol) ;
surf_ch_in_xmin = surf_ch_in_all ELEM 'APPUYE' 'STRICTEMENT' po_ch_in_xmin ;
po_ch_in_xmax = (surf_ch_in_all COOR 1) POIN 'COMPRIS' (xmax-re_tol) (xmax+re_tol) ;
surf_ch_in_xmax = surf_ch_in_all ELEM 'APPUYE' 'STRICTEMENT' po_ch_in_xmax ;
surf_ch_in_top = FACE vo_ch_in_up 2 ;
surf_ch_in_bottom = FACE vo_ch_in_low 2 ;

po_ch_out_interface = (surf_ch_out_all COOR 2) POIN 'COMPRIS' (ymax-re_tol) (ymax+re_tol) ;
surf_ch_out_interface = surf_ch_out_all ELEM 'APPUYE' 'STRICTEMENT' po_ch_out_interface ;
po_ch_out_outer = (surf_ch_out_all COOR 2) POIN 'COMPRIS'
    (ymax+length_outlet-re_tol) (ymax+length_outlet+re_tol) ;
surf_ch_out_outer = surf_ch_out_all ELEM 'APPUYE' 'STRICTEMENT' po_ch_out_outer ;
po_ch_out_xmin = (surf_ch_out_all COOR 1) POIN 'COMPRIS' (xmin-re_tol) (xmin+re_tol) ;
surf_ch_out_xmin = surf_ch_out_all ELEM 'APPUYE' 'STRICTEMENT' po_ch_out_xmin ;
po_ch_out_xmax = (surf_ch_out_all COOR 1) POIN 'COMPRIS' (xmax-re_tol) (xmax+re_tol) ;
surf_ch_out_xmax = surf_ch_out_all ELEM 'APPUYE' 'STRICTEMENT' po_ch_out_xmax ;
surf_ch_out_top = FACE vo_ch_out_up 2 ;
surf_ch_out_bottom = FACE vo_ch_out_low 2 ;

"""

CHAMBER_EXPORTS = """* Separate chamber volumes and all six named chamber boundaries.
OPTI SORT 'castem_mesh_v_inlet.bdf' ;
SORT 'NAS' vo_ch_in ;
OPTI SORT 'castem_mesh_surf_inlet_all.bdf' ;
SORT 'NAS' surf_ch_in_all ;
OPTI SORT 'castem_mesh_surf_inlet_interface.bdf' ;
SORT 'NAS' surf_ch_in_interface ;
OPTI SORT 'castem_mesh_surf_inlet_outer.bdf' ;
SORT 'NAS' surf_ch_in_outer ;
OPTI SORT 'castem_mesh_surf_inlet_top.bdf' ;
SORT 'NAS' surf_ch_in_top ;
OPTI SORT 'castem_mesh_surf_inlet_bottom.bdf' ;
SORT 'NAS' surf_ch_in_bottom ;
OPTI SORT 'castem_mesh_surf_inlet_xmin.bdf' ;
SORT 'NAS' surf_ch_in_xmin ;
OPTI SORT 'castem_mesh_surf_inlet_xmax.bdf' ;
SORT 'NAS' surf_ch_in_xmax ;

OPTI SORT 'castem_mesh_v_outlet.bdf' ;
SORT 'NAS' vo_ch_out ;
OPTI SORT 'castem_mesh_surf_outlet_all.bdf' ;
SORT 'NAS' surf_ch_out_all ;
OPTI SORT 'castem_mesh_surf_outlet_interface.bdf' ;
SORT 'NAS' surf_ch_out_interface ;
OPTI SORT 'castem_mesh_surf_outlet_outer.bdf' ;
SORT 'NAS' surf_ch_out_outer ;
OPTI SORT 'castem_mesh_surf_outlet_top.bdf' ;
SORT 'NAS' surf_ch_out_top ;
OPTI SORT 'castem_mesh_surf_outlet_bottom.bdf' ;
SORT 'NAS' surf_ch_out_bottom ;
OPTI SORT 'castem_mesh_surf_outlet_xmin.bdf' ;
SORT 'NAS' surf_ch_out_xmin ;
OPTI SORT 'castem_mesh_surf_outlet_xmax.bdf' ;
SORT 'NAS' surf_ch_out_xmax ;

"""


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


def _replace_once(text: str, old: str, new: str, *, context: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(
            f"The mesh DGIBI must contain exactly one {context}; found {count}."
        )
    return text.replace(old, new, 1)


def _remove_displace_procedure(program: str) -> str:
    """Remove the unused baseline node-by-node displacement procedure."""

    start = program.find(DISPLACE_PROCEDURE_START)
    if start < 0:
        raise ValueError("Could not find the baseline DISPLACE procedure.")
    end = program.find(DISPLACE_PROCEDURE_END, start)
    if end < 0:
        raise ValueError("Could not find the end of the baseline DISPLACE procedure.")
    end += len(DISPLACE_PROCEDURE_END)
    return (
        program[:start]
        + "* Python chamber mode omits the unused node-by-node displacement procedure."
        + program[end:]
    )


def _patch_volume_exports(program: str) -> str:
    """Export the combined volume, full envelope, and named chamber boundaries."""

    volume_pattern = (
        r"(OPTI SORT 'castem_mesh_v\.bdf'\s*;\s*\n\s*SORT 'NAS')"
        r"\s+vo_cr\s*;"
    )
    combined = (
        r"\1 vo_all ;\n"
        "OPTI SORT 'castem_mesh_surf_all.bdf' ;\n"
        "SORT 'NAS' surf_all ;"
    )
    program, count = re.subn(volume_pattern, combined, program, count=1)
    if count != 1:
        raise ValueError("Could not patch the baseline combined-volume export.")

    export_marker = "******** Step6: Export the results ***************"
    export_start = program.find(export_marker)
    if export_start < 0:
        raise ValueError("Could not find the generated chamber export section.")
    hole_exports = "SI (NON (EGA (DIME re_cr) 0)) ;"
    insertion = program.find(hole_exports, export_start)
    if insertion < 0:
        raise ValueError("Could not find the baseline hole-boundary exports.")
    program = program[:insertion] + CHAMBER_EXPORTS + program[insertion:]

    program = _replace_once(
        program,
        "**Visualization of the crack volume**",
        "**Visualization of the crack and chamber volume**",
        context="baseline visualization heading",
    )
    program = _replace_once(
        program,
        "TRAC 'FACE' (COUL 'ROUG' vo_cr) 'TITR' 'Crack Volume' ;",
        "TRAC 'FACE' (COUL 'ROUG' vo_all) "
        "'TITR' 'Crack with inlet and outlet chambers' ;",
        context="baseline visualization command",
    )
    program = _replace_once(
        program,
        "SORT 'MED' vo_cr",
        "SORT 'MED' vo_all",
        context="baseline MED volume export",
    )
    return program


def patch_chamber_program(program: str, chambers: ChamberParameters) -> str:
    """Inject optional chambers into a generated copy of the single mesh source.

    The repository's historical ``source_codes/castem_tool.dgibi`` stays
    byte-identical. Chamber parameters, construction, and exports exist only in
    the per-run DGIBI written to the selected working directory.
    """

    chambers.validated()
    if not chambers.enabled:
        return program
    if program.count(MAIN_BLOCK_START) != 1:
        raise ValueError(
            "The mesh DGIBI must contain exactly one recognized Main Program block."
        )

    chamber_parameters = CHAMBER_PARAMETER_TEMPLATE.format(
        height=f"{chambers.height:.12g}",
        inlet_length=f"{chambers.inlet_length:.12g}",
        outlet_length=f"{chambers.outlet_length:.12g}",
        inlet_height_elements=chambers.inlet_height_elements,
        outlet_height_elements=chambers.outlet_height_elements,
        inlet_length_elements=chambers.inlet_length_elements,
        outlet_length_elements=chambers.outlet_length_elements,
        inlet_height_ratio=f"{chambers.inlet_height_ratio:.12g}",
        outlet_height_ratio=f"{chambers.outlet_height_ratio:.12g}",
        inlet_length_ratio=f"{chambers.inlet_length_ratio:.12g}",
        outlet_length_ratio=f"{chambers.outlet_length_ratio:.12g}",
    )
    program = _replace_once(
        program,
        HOLE_PARAMETER_ANCHOR,
        chamber_parameters + HOLE_PARAMETER_ANCHOR,
        context="hole-parameter heading",
    )
    program = _remove_displace_procedure(program)
    program = replace_hole_interpolation_block_names(program)
    program = _replace_once(
        program,
        EXPORT_ANCHOR,
        CHAMBER_CONSTRUCTION
        + "******** Step6: Export the results ***************",
        context="baseline export heading",
    )
    return _patch_volume_exports(program)
