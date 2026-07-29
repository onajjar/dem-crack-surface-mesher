"""
CASTEM CSV -> mesh pipeline with GUI (Tkinter)

What this program does:
1) User selects:
   - CASTEM .dgibi template
   - 4 CSV files: xrange, yrange, zfit_zmax, zfit_zmin
   - Working directory (where CASTEM will run and write .bdf outputs)

2) User enters CASTEM parameters (physical values):
   - re_ti, re_crpa, re_smfa, re_numspa, re_opmin
   - IMPORTANT: enter physical values (example: re_smfa=0.05, re_opmin=1e-6)
   - File naming convention uses scaled integers (as in your CSV_LIRE procedure):
       smfa_int  = ENTI(re_smfa * 100)   -> 0.05 -> 5
       opmin_int = ENTI(re_opmin * 1e6)  -> 1e-6 -> 1

3) User can also edit the remaining "Main Program" parameters (with defaults pre-filled):
   - Mesh refinements: nelem_x, nelem_y, nelem_z, re_tol
   - Inflation along z: re_fact_z
   - Hole filling: num_el_fill, re_fact_hole
   - Visualization: opti_visu (checkbox) -> handled by Gmsh, not CASTEM

4) Holes (optional):
   - If "Holes exist" is checked, the user can enter one or more circles:
       (cx, cy, r) for each hole
   - These are written as:
       re_cx = PROG cx1 cx2 ... ;
       re_cy = PROG cy1 cy2 ... ;
       re_cr = PROG r1  r2  ... ;
   - If unchecked, holes are disabled with:
       re_cx = PROG ;
       re_cy = PROG ;
       re_cr = PROG ;

5) The program copies/renames the CSVs into the working directory with the exact names CASTEM expects:
   xrange_ti{re_ti}_crpa{re_crpa}_smfa{smfa_int}_numsp{re_numspa}_opmin{opmin_int}.csv
   yrange_ti{...}.csv
   zfit_zmax_ti{...}.csv
   zfit_zmin_ti{...}.csv

6) It generates a new .dgibi file in the working directory whose filename also uses the scaled naming.

7) It runs CASTEM using only the version input:
   - User enters 25 or 2025
   - Executable path is always:
       C:\\Cast3M\\PCW_25\\bin\\castem25.bat  (for version 25)
   - Uses cmd.exe /c to reliably run .bat

8) It optionally merges volume + surface .bdf files into one combined .bdf.

Important implementation detail:
- The .dgibi edit is done ONLY inside the "Main Program" block
  (starting at: ************************** Main Program *******************************).
  This prevents accidental edits inside DEBP procedures such as CSV_LIRE.

Run:
  python castem_pipeline_gui.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from mpl_toolkits.mplot3d.art3d import Line3DCollection  # for XY colored lines


import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# --- ADD near the top of your file (imports) ---
from datetime import datetime

try:
    import h5py
except Exception:
    h5py = None


# ----------------------------
# CASTEM executable (version only)
# ----------------------------

def resolve_castem_exe(version: str) -> Path:
    env = os.environ.get("CASTEM_PATH", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            cand = next(p.glob("castem*.bat"), None)
            if cand and cand.exists():
                return cand
        if p.is_file() and p.exists():
            return p

    v = str(version).strip()
    if not v.isdigit():
        raise ValueError("CASTEM version must be numeric (example: 25 or 2025).")

    v2 = v[-2:]  # 2025 -> 25
    exe = Path(rf"C:\Cast3M\PCW_{v2}\bin\castem{v2}.bat")
    if not exe.exists():
        raise FileNotFoundError(
            f"CASTEM executable not found:\n{exe}\n\n"
            "You can set CASTEM_PATH to the folder containing castem*.bat or to the full .bat path."
        )
    return exe


# ----------------------------
# CSV naming scaling
# ----------------------------

def parse_float(s: str) -> float:
    return float(s.strip().lower().replace(",", "."))


def smfa_int(smfa: float) -> int:
    return int(round(smfa * 100.0))


def opmin_int(opmin: float) -> int:
    return int(round(opmin * 1.0e6))


def safe_copy(src: Path, dst: Path) -> None:
    src = src.resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        dst_res = dst.resolve()
    except FileNotFoundError:
        dst_res = dst
    if src == dst_res:
        return
    shutil.copyfile(src, dst)


def ensure_dir(p: str) -> Path:
    d = Path(p).expanduser().resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ----------------------------
# GMSH executable
# ----------------------------

def resolve_gmsh_exe() -> Path:
    """
    Try to find gmsh.exe automatically:
    1) If env var GMSH_PATH is set (file or folder), use it.
    2) Look in common install locations (Program Files).
    3) Look in user's home for folders like gmsh-4.xx.*.
    4) If still not found, raise with instructions.
    """
    env = os.environ.get("GMSH_PATH", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            cand = p / "gmsh.exe"
            if cand.exists():
                return cand
        if p.is_file() and p.name.lower() == "gmsh.exe" and p.exists():
            return p

    candidates: list[Path] = [
        Path(r"C:\Program Files\Gmsh\gmsh.exe"),
        Path(r"C:\Program Files (x86)\Gmsh\gmsh.exe"),
    ]

    home = Path.home()
    for pat in ["gmsh-*-Windows64", "Gmsh*", "gmsh*"]:
        for d in home.glob(pat):
            if d.is_dir():
                candidates.append(d / "gmsh.exe")

    from shutil import which
    w = which("gmsh")
    if w:
        candidates.append(Path(w))

    for c in candidates:
        try:
            if c.exists():
                return c
        except Exception:
            pass

    raise FileNotFoundError(
        "Could not find gmsh.exe automatically.\n\n"
        "Fix options:\n"
        "1) Install Gmsh, or\n"
        "2) Set environment variable GMSH_PATH to the folder that contains gmsh.exe\n"
        "   Example: GMSH_PATH=C:\\Users\\<user>\\gmsh-4.15.0-Windows64\n"
        "   (or directly to the exe)\n"
        "3) Or update resolve_gmsh_exe() with your gmsh.exe location."
    )



# --- ADD somewhere above class App (for example after the dataclasses) ---

class H5ResultStore:
    """
    Read-only access to a single HDF5 file that contains:
      /meta/line_ids, /meta/Ps, /meta/Ts
      /geometry/Xi, Yi, Zi, Ouv, Eten
      /results/<var>/P<p>_T<t>   (2D float array)
      /results/<var>/P<p>_T<t>_mask (1D uint8 array, 1 if the line exists)
    """
    def __init__(self, h5_path: Path):
        if h5py is None:
            raise RuntimeError(
                "h5py is not installed, cannot read/write .h5.\n"
                "Install it with: pip install h5py"
            )
        self.path = Path(h5_path)
        self.h5 = h5py.File(str(self.path), "r")

        self.line_ids = self.h5["/meta/line_ids"][...].astype(int).tolist()
        self.Ps = self.h5["/meta/Ps"][...].astype(int).tolist()
        self.Ts = self.h5["/meta/Ts"][...].astype(int).tolist()

        self.vars = []
        if "/results" in self.h5:
            self.vars = sorted(list(self.h5["/results"].keys()))

    def close(self):
        try:
            self.h5.close()
        except Exception:
            pass

    def _ds_name(self, p: int, t: int) -> str:
        return f"P{int(p)}_T{int(t)}"

    def has(self, var: str, p: int, t: int) -> bool:
        grp = f"/results/{var}"
        if grp not in self.h5:
            return False
        name = self._ds_name(p, t)
        return (f"{grp}/{name}" in self.h5)

    def complete(self, var: str, p: int, t: int) -> bool:
        if not self.has(var, p, t):
            return False
        name = self._ds_name(p, t)
        mask_path = f"/results/{var}/{name}_mask"
        if mask_path not in self.h5:
            return True  # fallback
        m = self.h5[mask_path][...]
        return bool((m.astype(int) == 1).all())

    def load(self, var: str, p: int, t: int) -> np.ndarray | None:
        if not self.has(var, p, t):
            return None
        name = self._ds_name(p, t)
        return self.h5[f"/results/{var}/{name}"][...]

    def geometry(self):
        g = self.h5["/geometry"]
        Xi = g["Xi"][...]
        Yi = g["Yi"][...]
        Zi = g["Zi"][...]
        Ouv = g["Ouv"][...]
        Eten = g["Eten"][...]
        return Xi, Yi, Zi, Ouv, Eten



# ----------------------------
# Data model
# ----------------------------

@dataclass
class Hole:
    cx: float
    cy: float
    r: float


@dataclass
class CastemMainParams:
    # CSV naming params
    re_ti: int = 60
    re_crpa: int = 1
    re_smfa: float = 0.05
    re_numspa: int = 50
    re_opmin: float = 1e-6

    # mesh refinements
    nelem_x: int = 1
    nelem_y: int = 1
    nelem_z: int = 1
    re_tol: float = 1e-10

    # inflation along z
    re_fact_z: float = 1.05

    # hole filling
    num_el_fill: int = 5
    re_fact_hole: float = 5.0

    # visualization (Gmsh)
    opti_visu: int = 0

    # MED/STL export
    opti_med: int = 0
    opti_stl: int = 0

    # holes
    holes_enabled: bool = False
    holes: List[Hole] = field(default_factory=list)

    @property
    def re_smfa_int(self) -> int:
        return smfa_int(self.re_smfa)

    @property
    def re_opmin_int(self) -> int:
        return opmin_int(self.re_opmin)


@dataclass
class FissSetup:
    model: str
    gas: str
    cond: str

    # material/friction
    rugo: float | None
    rec: float | None
    fk: float | None
    fa: float | None
    fb: float | None
    fc: float | None
    fd: float | None
    fk_k: float | None  # for FROT3/4

    # BC
    temp_wall: float
    p_aval: float
    psteam: float
    num_elem_y: int

    p_mode: str
    p_in: float | None
    p_ini: float | None
    p_fin: float | None
    p_step: float | None

    t_mode: str
    t_in: float | None
    t_ini: float | None
    t_fin: float | None
    t_step: float | None


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)

        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.v_scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.v_scroll.set)

        self.v_scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        # Frame that will contain all your widgets
        self.content = ttk.Frame(self.canvas)
        self._window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")

        # Update scrollregion when content changes size
        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Mouse wheel support (Windows/macOS/Linux)
        self._bind_mousewheel(self.canvas)

    def _on_content_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # Keep inner frame width equal to canvas width
        self.canvas.itemconfigure(self._window_id, width=event.width)

    def _bind_mousewheel(self, widget):
        widget.bind("<Enter>", self._enable_mousewheel)
        widget.bind("<Leave>", self._disable_mousewheel)

    def _enable_mousewheel(self, _event=None):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)
        self.canvas.bind_all("<Prior>", lambda e: self.canvas.yview_scroll(-1, "pages"))
        self.canvas.bind_all("<Next>",  lambda e: self.canvas.yview_scroll(1, "pages"))

    def _disable_mousewheel(self, _event=None):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")
        self.canvas.unbind_all("<Prior>")
        self.canvas.unbind_all("<Next>")



    def _on_mousewheel(self, event):
        if event.num == 4:      # Linux scroll up
            self.canvas.yview_scroll(-3, "units")
        elif event.num == 5:    # Linux scroll down
            self.canvas.yview_scroll(3, "units")
        else:                   # Windows / macOS
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


# ----------------------------
# DGIBI patching (ONLY within Main Program block)
# ----------------------------

MAIN_BLOCK_START = "************************** Main Program *******************************"


def _replace_assign_in_block(block: str, var_name: str, value_expr: str) -> str:
    """
    Replace a CASTEM assignment like:
      var = something ;
    even if 'something' spans multiple lines, up to the first ';'.

    If not found, insert exactly one assignment near the top of the Main Program block.
    """
    pattern = rf"(^\s*{re.escape(var_name)}\s*=\s*)(.*?)(\s*;)"
    repl = rf"\g<1>{value_expr}\g<3>"
    new_block, n = re.subn(pattern, repl, block, count=1, flags=re.MULTILINE | re.DOTALL)

    if n == 0:
        # Insert near the top of the block (after first non-empty line)
        lines = block.splitlines(True)
        ins = f"{var_name} = {value_expr} ;\n"

        insert_at = 0
        for i, ln in enumerate(lines[:40]):
            if ln.strip():
                insert_at = i + 1
                break

        # Do not insert if it exists anywhere
        if re.search(rf"^\s*{re.escape(var_name)}\s*=", block, flags=re.MULTILINE):
            return block

        lines.insert(insert_at, ins)
        new_block = "".join(lines)

    return new_block


def _format_prog_list(values: List[float]) -> str:
    if not values:
        return "PROG"
    items = " ".join(f"{v:.12g}" for v in values)
    return f"PROG {items}"


def _format_prog_range(a: float, step: float, b: float) -> str:
    return f"PROG {a:.12g} PAS {step:.12g} {b:.12g}"


def _format_prog_single(a: float) -> str:
    return f"PROG {a:.12g}"


def patch_dgibi_main_program(template_text: str, p: CastemMainParams) -> str:
    idx = template_text.find(MAIN_BLOCK_START)
    if idx < 0:
        raise ValueError("Could not find the Main Program block marker in the dgibi.")

    head = template_text[:idx]
    block = template_text[idx:]

    # Core naming params
    block = _replace_assign_in_block(block, "re_ti", str(p.re_ti))
    block = _replace_assign_in_block(block, "re_crpa", str(p.re_crpa))
    block = _replace_assign_in_block(block, "re_smfa", f"{p.re_smfa:.12g}")
    block = _replace_assign_in_block(block, "re_numspa", str(p.re_numspa))
    block = _replace_assign_in_block(block, "re_opmin", f"{p.re_opmin:.12g}")

    # mesh refinements
    block = _replace_assign_in_block(block, "nelem_x", str(p.nelem_x))
    block = _replace_assign_in_block(block, "nelem_y", str(p.nelem_y))
    block = _replace_assign_in_block(block, "nelem_z", str(p.nelem_z))
    block = _replace_assign_in_block(block, "re_tol", f"{p.re_tol:.12g}")

    # inflation along z
    block = _replace_assign_in_block(block, "re_fact_z", f"{p.re_fact_z:.12g}")

    # hole filling
    block = _replace_assign_in_block(block, "num_el_fill", str(p.num_el_fill))
    block = _replace_assign_in_block(block, "re_fact_hole", f"{p.re_fact_hole:.12g}")

    # Visualization: handled by Gmsh (not CASTEM)
    block = _replace_assign_in_block(block, "opti_visu", "1" if p.opti_visu else "0")

    # MED/STL export options
    block = _replace_assign_in_block(block, "opti_med", "1" if p.opti_med else "0")
    block = _replace_assign_in_block(block, "opti_stl", "1" if p.opti_stl else "0")

    # holes lists
    if p.holes_enabled and p.holes:
        cx = [h.cx for h in p.holes]
        cy = [h.cy for h in p.holes]
        cr = [h.r for h in p.holes]
        block = _replace_assign_in_block(block, "re_cx", _format_prog_list(cx))
        block = _replace_assign_in_block(block, "re_cy", _format_prog_list(cy))
        block = _replace_assign_in_block(block, "re_cr", _format_prog_list(cr))
    else:
        block = _replace_assign_in_block(block, "re_cx", "PROG")
        block = _replace_assign_in_block(block, "re_cy", "PROG")
        block = _replace_assign_in_block(block, "re_cr", "PROG")

    return head + block


# ----------------------------
# BDF merge (simple)
# ----------------------------

def merge_bdfs(workdir: Path, log) -> Optional[Path]:
    volume_file = workdir / "castem_mesh_v.bdf"
    if not volume_file.exists():
        log("No castem_mesh_v.bdf found. Skipping merge.\n")
        return None

    preferred = [
        "castem_mesh_surf_min.bdf",
        "castem_mesh_surf_max.bdf",
        "castem_mesh_surf_xmin.bdf",
        "castem_mesh_surf_xmax.bdf",
        "castem_mesh_surf_ymin.bdf",
        "castem_mesh_surf_ymax.bdf",
        # "castem_mesh_surf_mean.bdf",  # DO NOT MERGE MEAN
    ]

    trou = sorted([p.name for p in workdir.glob("castem_mesh_surf_trou_*.bdf")])
    surface_names = [n for n in preferred if (workdir / n).exists()] + trou

    excluded = set(surface_names) | {"castem_mesh_surf_mean.bdf"}
    others = sorted([
        p.name for p in workdir.glob("castem_mesh_surf_*.bdf")
        if p.name not in excluded
    ])
    surface_names += others

    if not surface_names:
        log("No surface .bdf found. Returning volume only.\n")
        return volume_file

    def read_lines(p: Path) -> list[str]:
        return p.read_text(encoding="utf-8", errors="ignore").splitlines(True)

    def is_bulk_header(line: str) -> bool:
        s = line.strip().upper()
        return s.startswith(("BEGIN BULK", "MAT1", "GRID", "ENDDATA"))

    def format_bdf_large(fields: list[str]) -> list[str]:
        """
        LARGE FIELD (16-char) with '*' continuation.
        Line 1: CARD* (8 chars) + 4 fields * 16 chars
        Next:   *     (8 chars) + 4 fields * 16 chars
        """
        if not fields:
            return ["\n"]

        card = fields[0].strip()
        rest = [str(x) for x in fields[1:]]
        lines: list[str] = []

        first = f"{(card + '*'):<8}"
        chunk = rest[:4]
        for f in chunk:
            first += f"{f:>16}"
        lines.append(first.rstrip() + "\n")
        rest = rest[4:]

        while rest:
            cont = f"{'*':<8}"
            chunk = rest[:4]
            for f in chunk:
                cont += f"{f:>16}"
            lines.append(cont.rstrip() + "\n")
            rest = rest[4:]

        return lines

    def parse_cquad4_fields(line: str) -> list[str] | None:
        s = line.strip()
        if not s.upper().startswith("CQUAD4"):
            return None
        parts = s.split()
        if len(parts) < 7:
            return None
        return parts[:7]  # CQUAD4 EID PID G1 G2 G3 G4

    def parse_max_elem_id(lines: list[str]) -> int:
        max_eid = 0
        elem_cards = {"CHEXA", "CTETRA", "CPENTA", "CPYRAM", "CQUAD4", "CTRIA3"}
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            parts = s.split()
            if not parts:
                continue
            card = parts[0].upper().rstrip("*")  # IMPORTANT: handle CHEXA*
            if card in elem_cards and len(parts) >= 2:
                try:
                    max_eid = max(max_eid, int(parts[1]))
                except Exception:
                    pass
        return max_eid

    vol_lines = read_lines(volume_file)
    vol_lines_wo_end = [ln for ln in vol_lines if not ln.strip().upper().startswith("ENDDATA")]

    current_elem_id = parse_max_elem_id(vol_lines_wo_end)
    current_pshell_id = 0  # PSHELL numbering starts at 1

    combined_path = workdir / "combined_raw.bdf"

    with combined_path.open("w", encoding="utf-8") as fout:
        fout.writelines(vol_lines_wo_end)
        fout.write("$ ---- MERGED SURFACES (one PSHELL per surface file) ----\n")

        for surf_name in surface_names:
            surf_path = workdir / surf_name
            if not surf_path.exists():
                continue

            surf_lines = read_lines(surf_path)

            cquad_cards: list[list[str]] = []
            for ln in surf_lines:
                if is_bulk_header(ln):
                    continue
                if ln.strip().upper().startswith("CQUAD4"):
                    f = parse_cquad4_fields(ln)
                    if f is not None:
                        cquad_cards.append(f)

            if not cquad_cards:
                log(f"Skipping {surf_name} (no CQUAD4 found)\n")
                continue

            current_pshell_id += 1
            fout.write(f"$ ---- {surf_name} ----\n")
            fout.write(f"$ PSHELL for {surf_name}\n")

            # PSHELL PID MID1 T (simple)
            for l in format_bdf_large(["PSHELL", str(current_pshell_id), "1", "1.0"]):
                fout.write(l)

            for f in cquad_cards:
                current_elem_id += 1
                f[1] = str(current_elem_id)       # new EID
                f[2] = str(current_pshell_id)     # new PID
                for l in format_bdf_large(f):
                    fout.write(l)

            fout.write(f"$ ---- END {surf_name} ----\n")

        fout.write("ENDDATA\n")

    log(f"Combined BDF written: {combined_path.name}\n")
    return combined_path



# ----------------------------
# GUI
# ----------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BPM to CFX Mesh Converter")
        try:
            self.iconbitmap("bpm_cfx.ico")
        except Exception:
            pass
        self.geometry("1300x650")
        self.minsize(1000, 600)

        # Paths
        self.dgibi_var = tk.StringVar()
        self.workdir_var = tk.StringVar()
        self.castem_version_var = tk.StringVar(value="25")

        self.csv_x_var = tk.StringVar()
        self.csv_y_var = tk.StringVar()
        self.csv_zmax_var = tk.StringVar()
        self.csv_zmin_var = tk.StringVar()

        # Main params defaults
        self.re_ti_var = tk.StringVar(value="60")
        self.re_crpa_var = tk.StringVar(value="1")
        self.re_smfa_var = tk.StringVar(value="0.05")
        self.re_numspa_var = tk.StringVar(value="50")
        self.re_opmin_var = tk.StringVar(value="1e-6")

        self.nelem_x_var = tk.StringVar(value="1")
        self.nelem_y_var = tk.StringVar(value="1")
        self.nelem_z_var = tk.StringVar(value="1")
        self.re_tol_var = tk.StringVar(value="1e-10")

        self.re_fact_z_var = tk.StringVar(value="1.05")

        self.num_el_fill_var = tk.StringVar(value="5")
        self.re_fact_hole_var = tk.StringVar(value="5.0")

        self.opti_visu_var = tk.BooleanVar(value=True)
        self.opti_med_var = tk.BooleanVar(value=False)
        self.opti_stl_var = tk.BooleanVar(value=False)

        self.holes_enabled_var = tk.BooleanVar(value=False)
        self.do_merge_var = tk.BooleanVar(value=True)

        self.hole_rows: List[Tuple[tk.StringVar, tk.StringVar, tk.StringVar]] = []

        # ----------------------------
        # FISS (flow) inputs
        # ----------------------------
        self.fiss_dgibi_var = tk.StringVar()
        self.fiss_model_var = tk.StringVar(value="POISEU_GELAIN_2012")

        self.fiss_rugo_var = tk.StringVar(value="40e-6")
        self.fiss_rec_var = tk.StringVar(value="10.0")

        self.fiss_fk_var = tk.StringVar(value="96.0")
        self.fiss_fa_var = tk.StringVar(value="0.316")
        self.fiss_fb_var = tk.StringVar(value="2.0e-6")
        self.fiss_fc_var = tk.StringVar(value="-0.25")
        self.fiss_fd_var = tk.StringVar(value="2.0")

        self.fiss_fk_k_var = tk.StringVar(value="0.5")

        self.fiss_gas_var = tk.StringVar(value="PARF")
        self.fiss_cond_var = tk.StringVar(value="MASS")

        self.fiss_temp_wall_var = tk.StringVar(value="25.0")
        self.fiss_p_aval_var = tk.StringVar(value="101325.0")
        self.fiss_psteam_var = tk.StringVar(value="0.0")

        self.fiss_p_mode_var = tk.StringVar(value="range")
        self.fiss_p_in_var = tk.StringVar(value="5e5")
        self.fiss_p_ini_var = tk.StringVar(value="101325.0")
        self.fiss_p_fin_var = tk.StringVar(value="5e5")
        self.fiss_p_step_var = tk.StringVar(value="2.5e5")

        self.fiss_t_mode_var = tk.StringVar(value="range")
        self.fiss_t_in_var = tk.StringVar(value="25.0")
        self.fiss_t_ini_var = tk.StringVar(value="25.0")
        self.fiss_t_fin_var = tk.StringVar(value="50.0")
        self.fiss_t_step_var = tk.StringVar(value="25.0")

        self.fiss_num_elem_y_var = tk.StringVar(value="5")

        # Store entry widgets for toggle enable/disable
        self._p_entries: dict[str, ttk.Entry] = {}
        self._t_entries: dict[str, ttk.Entry] = {}

        self.scroll = ScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True)

        self._build_ui(parent=self.scroll.content)

    # ============================================================
    # PATCH 1/2: LIVE LOG helper
    # ============================================================
    def _stream_process_to_log(self, cmd, cwd: Path, on_done=None):
        """
        Runs process and streams stdout to the Tk log in real time.
        Does NOT block the Tk mainloop.
        """
        self._log("Command:\n  " + " ".join(cmd) + "\n")

        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
            universal_newlines=True,
        )

        def reader():
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    self.after(0, self._log, line)
            finally:
                rc = proc.wait()

                def finish():
                    if rc == 0:
                        self._log("\nProcess OK.\n")
                    else:
                        self._log(f"\nProcess FAILED (return code {rc}).\n")
                    if on_done:
                        on_done(rc)

                self.after(0, finish)

        threading.Thread(target=reader, daemon=True).start()
        return proc

    def _validate_params(self, p: CastemMainParams):
        if p.re_smfa <= 0:
            raise ValueError("re_smfa must be > 0")
        if p.re_opmin < 0:
            raise ValueError("re_opmin must be >= 0")
        if p.nelem_x < 1 or p.nelem_y < 1 or p.nelem_z < 1:
            raise ValueError("nelem_x, nelem_y, nelem_z must be >= 1")
        if p.re_fact_z <= 0:
            raise ValueError("re_fact_z must be > 0")
        if p.holes_enabled:
            for k, h in enumerate(p.holes or [], start=1):
                if h.r <= 0:
                    raise ValueError(f"Hole {k}: radius r must be > 0")

    def _build_ui(self, parent):
        pad = {"padx": 8, "pady": 4}

        # ----------------------------
        # Top: Paths
        # ----------------------------
        frm_paths = ttk.LabelFrame(parent, text="Paths")

        frm_paths.pack(fill="x", padx=10, pady=8)

        ttk.Label(frm_paths, text="DGIBI template:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm_paths, textvariable=self.dgibi_var, width=105).grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(frm_paths, text="Browse", command=self._browse_dgibi).grid(row=0, column=2, **pad)

        ttk.Label(frm_paths, text="Working directory:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm_paths, textvariable=self.workdir_var, width=105).grid(row=1, column=1, sticky="we", **pad)
        ttk.Button(frm_paths, text="Browse", command=self._browse_workdir).grid(row=1, column=2, **pad)

        ttk.Label(frm_paths, text="CAST3M version (25 or 2025):").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm_paths, textvariable=self.castem_version_var, width=10).grid(row=2, column=1, sticky="w", **pad)

        frm_paths.columnconfigure(1, weight=1)

        # ----------------------------
        # CSV inputs
        # ----------------------------
        frm_csv = ttk.LabelFrame(parent, text="CSV inputs")
        frm_csv.pack(fill="x", padx=10, pady=6)
        self._csv_row(frm_csv, 0, "xrange CSV:", self.csv_x_var, self._browse_csv_x)
        self._csv_row(frm_csv, 1, "yrange CSV:", self.csv_y_var, self._browse_csv_y)
        self._csv_row(frm_csv, 2, "zfit_zmax CSV:", self.csv_zmax_var, self._browse_csv_zmax)
        self._csv_row(frm_csv, 3, "zfit_zmin CSV:", self.csv_zmin_var, self._browse_csv_zmin)

        # ----------------------------
        # Parameters area (3 columns frames)
        # ----------------------------
        frm_params = ttk.LabelFrame(parent, text="Parameters")
        frm_params.pack(fill="x", padx=10, pady=6)

        frm_params.columnconfigure(0, weight=1, uniform="cols")
        frm_params.columnconfigure(1, weight=1, uniform="cols")
        frm_params.columnconfigure(2, weight=1, uniform="cols")

        # ---- Column 0: Naming ----
        frm_naming = ttk.LabelFrame(frm_params, text="CSV naming")
        frm_naming.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        self._labeled_entry(frm_naming, 0, 0, "re_ti", self.re_ti_var)
        self._labeled_entry(frm_naming, 1, 0, "re_crpa", self.re_crpa_var)
        self._labeled_entry(frm_naming, 2, 0, "re_smfa", self.re_smfa_var)
        self._labeled_entry(frm_naming, 3, 0, "re_numspa", self.re_numspa_var)
        self._labeled_entry(frm_naming, 4, 0, "re_opmin", self.re_opmin_var)

        # ---- Column 1: Mesh ----
        frm_mesh = ttk.LabelFrame(frm_params, text="Mesh")
        frm_mesh.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)

        self._labeled_entry(frm_mesh, 0, 0, "nelem_x", self.nelem_x_var)
        self._labeled_entry(frm_mesh, 1, 0, "nelem_y", self.nelem_y_var)
        self._labeled_entry(frm_mesh, 2, 0, "nelem_z", self.nelem_z_var)
        self._labeled_entry(frm_mesh, 3, 0, "re_tol", self.re_tol_var)
        self._labeled_entry(frm_mesh, 4, 0, "re_fact_z", self.re_fact_z_var)

        # ---- Column 2: Export + Run options ----
        frm_opts = ttk.LabelFrame(frm_params, text="Export / Run")
        frm_opts.grid(row=0, column=2, sticky="nsew", padx=6, pady=6)

        ttk.Checkbutton(frm_opts, text="View mesh in Gmsh", variable=self.opti_visu_var).grid(
            row=0, column=0, columnspan=2, sticky="w", **pad
        )
        ttk.Checkbutton(frm_opts, text="Merge BDFs (CFX mesh)", variable=self.do_merge_var).grid(
            row=1, column=0, columnspan=2, sticky="w", **pad
        )

        ttk.Checkbutton(frm_opts, text="Save mesh as MED", variable=self.opti_med_var).grid(
            row=3, column=0, columnspan=2, sticky="w", **pad
        )
        ttk.Checkbutton(frm_opts, text="Save STL files", variable=self.opti_stl_var).grid(
            row=4, column=0, columnspan=2, sticky="w", **pad
        )

        # ----------------------------
        # Holes section
        # ----------------------------
        frm_holes = ttk.LabelFrame(parent, text="Holes (circles)")
        frm_holes.pack(fill="x", padx=10, pady=6)

        ttk.Checkbutton(frm_holes, text="Holes exist", variable=self.holes_enabled_var, command=self._toggle_holes).grid(
            row=0, column=0, sticky="w", **pad
        )
        ttk.Button(frm_holes, text="Add hole", command=self._add_hole_row).grid(row=0, column=1, **pad)
        ttk.Button(frm_holes, text="Remove last", command=self._remove_hole_row).grid(row=0, column=2, **pad)

        ttk.Separator(frm_holes, orient="horizontal").grid(row=1, column=0, columnspan=6, sticky="we", pady=6)

        self._labeled_entry(frm_holes, 2, 0, "num_el_fill", self.num_el_fill_var)
        self._labeled_entry(frm_holes, 2, 2, "re_fact_hole", self.re_fact_hole_var)

        ttk.Separator(frm_holes, orient="horizontal").grid(row=3, column=0, columnspan=6, sticky="we", pady=6)

        ttk.Label(frm_holes, text="cx").grid(row=4, column=1, sticky="w", **pad)
        ttk.Label(frm_holes, text="cy").grid(row=4, column=2, sticky="w", **pad)
        ttk.Label(frm_holes, text="r").grid(row=4, column=3, sticky="w", **pad)

        self.holes_rows_start = 5
        self.hole_row_widgets: list[tuple[tk.Widget, tk.Widget, tk.Widget, tk.Widget]] = []
        self.holes_container = frm_holes
        self._toggle_holes()

        # ----------------------------
        # FISS simulation section
        # ----------------------------
        frm_fiss = ttk.LabelFrame(parent, text="Flow estimation (FISS)")
        frm_fiss.pack(fill="x", padx=10, pady=6)

        ttk.Label(frm_fiss, text="FISS dgibi template:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm_fiss, textvariable=self.fiss_dgibi_var, width=95).grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(frm_fiss, text="Browse", command=self._browse_fiss_dgibi).grid(row=0, column=2, **pad)
        frm_fiss.columnconfigure(1, weight=1)

        # Main 2-column area inside FISS
        fiss_body = ttk.Frame(frm_fiss)
        fiss_body.grid(row=1, column=0, columnspan=3, sticky="we", padx=6, pady=6)
        fiss_body.columnconfigure(0, weight=1, uniform="fisscols")
        fiss_body.columnconfigure(1, weight=1, uniform="fisscols")

        # Left column: Model + Model parameters
        left_col = ttk.Frame(fiss_body)
        left_col.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        left_col.columnconfigure(0, weight=1)

        frm_model = ttk.LabelFrame(left_col, text="Model (one choice)")
        frm_model.grid(row=0, column=0, sticky="we", padx=0, pady=0)
        frm_model.columnconfigure(0, weight=1)
        frm_model.columnconfigure(1, weight=1)

        models = [
            "POISEU_BLASIUS",
            "POISEU_COLEBROOK",
            "POISEU_GELAIN_2008",
            "POISEU_GELAIN_2012",
            "POISEU_RIZKALLA",
            "FROTTEMENT1",
            "FROTTEMENT2",
            "FROTTEMENT3",
            "FROTTEMENT4",
        ]

        # Put radios in 2 columns to use space better
        for k, m in enumerate(models):
            ttk.Radiobutton(
                frm_model,
                text=m,
                value=m,
                variable=self.fiss_model_var,
                command=self._refresh_fiss_model_inputs
            ).grid(row=k // 2, column=k % 2, sticky="w", padx=8, pady=2)

        self.frm_fiss_dyn = ttk.LabelFrame(left_col, text="Model parameters")
        self.frm_fiss_dyn.grid(row=1, column=0, sticky="we", padx=0, pady=6)
        self.frm_fiss_dyn.columnconfigure(0, weight=1)

        # Right column: Gas + Condensation + Boundary conditions
        right_col = ttk.Frame(fiss_body)
        right_col.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        right_col.columnconfigure(0, weight=1)

        top_right = ttk.Frame(right_col)
        top_right.grid(row=0, column=0, sticky="we")
        top_right.columnconfigure(0, weight=1, uniform="topr")
        top_right.columnconfigure(1, weight=1, uniform="topr")

        frm_gas = ttk.LabelFrame(top_right, text="Gas")
        frm_gas.grid(row=0, column=0, sticky="we", padx=0, pady=0)
        ttk.Radiobutton(frm_gas, text="Perfect gas (PARF)", value="PARF", variable=self.fiss_gas_var).grid(
            row=0, column=0, sticky="w", padx=8, pady=2
        )
        ttk.Radiobutton(frm_gas, text="Real gas (REEL)", value="REEL", variable=self.fiss_gas_var).grid(
            row=0, column=1, sticky="w", padx=8, pady=2
        )

        frm_cond = ttk.LabelFrame(top_right, text="Condensation")
        frm_cond.grid(row=0, column=1, sticky="we", padx=6, pady=0)
        ttk.Radiobutton(frm_cond, text="MASS", value="MASS", variable=self.fiss_cond_var).grid(
            row=0, column=0, sticky="w", padx=8, pady=2
        )
        ttk.Radiobutton(frm_cond, text="FILM", value="FILM", variable=self.fiss_cond_var).grid(
            row=0, column=1, sticky="w", padx=8, pady=2
        )

        frm_bc = ttk.LabelFrame(right_col, text="Boundary conditions")
        frm_bc.grid(row=1, column=0, sticky="we", padx=0, pady=6)
        frm_bc.columnconfigure(0, weight=1, uniform="bc")
        frm_bc.columnconfigure(1, weight=1, uniform="bc")

        # small grid for global BC values (full width inside frm_bc)
        bc_top = ttk.Frame(frm_bc)
        bc_top.grid(row=0, column=0, columnspan=2, sticky="we", padx=6, pady=6)
        bc_top.columnconfigure(0, weight=1)
        bc_top.columnconfigure(1, weight=1)
        bc_top.columnconfigure(2, weight=1)
        bc_top.columnconfigure(3, weight=1)

        self._labeled_entry(bc_top, 0, 0, "P_aval (Pa)", self.fiss_p_aval_var)
        self._labeled_entry(bc_top, 0, 2, "temp_wall (°C)", self.fiss_temp_wall_var)
        self._labeled_entry(bc_top, 1, 0, "P_steam_amont (Pa)", self.fiss_psteam_var)
        self._labeled_entry(bc_top, 1, 2, "num_elem_y", self.fiss_num_elem_y_var)

        # Pressure block (left) and Temperature block (right)
        frm_pin = ttk.LabelFrame(frm_bc, text="Inlet total pressure P_amont")
        frm_pin.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        frm_pin.columnconfigure(0, weight=1)
        frm_pin.columnconfigure(1, weight=1)
        frm_pin.columnconfigure(2, weight=1)
        frm_pin.columnconfigure(3, weight=1)

        ttk.Radiobutton(
            frm_pin, text="Single", value="single", variable=self.fiss_p_mode_var,
            command=self._refresh_fiss_bc_inputs
        ).grid(row=0, column=0, sticky="w", padx=8, pady=2)
        ttk.Radiobutton(
            frm_pin, text="Range", value="range", variable=self.fiss_p_mode_var,
            command=self._refresh_fiss_bc_inputs
        ).grid(row=0, column=1, sticky="w", padx=8, pady=2)

        e_pin = self._labeled_entry(frm_pin, 1, 0, "P_in (Pa)", self.fiss_p_in_var)
        e_pini = self._labeled_entry(frm_pin, 2, 0, "P_ini (Pa)", self.fiss_p_ini_var)
        e_pfin = self._labeled_entry(frm_pin, 2, 2, "P_fin (Pa)", self.fiss_p_fin_var)
        e_pstep = self._labeled_entry(frm_pin, 3, 0, "P_step (Pa)", self.fiss_p_step_var)

        self._p_entries = {"P_in": e_pin, "P_ini": e_pini, "P_fin": e_pfin, "P_step": e_pstep}

        frm_tin = ttk.LabelFrame(frm_bc, text="Inlet temperature temp_amont")
        frm_tin.grid(row=1, column=1, sticky="nsew", padx=6, pady=6)
        frm_tin.columnconfigure(0, weight=1)
        frm_tin.columnconfigure(1, weight=1)
        frm_tin.columnconfigure(2, weight=1)
        frm_tin.columnconfigure(3, weight=1)

        ttk.Radiobutton(
            frm_tin, text="Single", value="single", variable=self.fiss_t_mode_var,
            command=self._refresh_fiss_bc_inputs
        ).grid(row=0, column=0, sticky="w", padx=8, pady=2)
        ttk.Radiobutton(
            frm_tin, text="Range", value="range", variable=self.fiss_t_mode_var,
            command=self._refresh_fiss_bc_inputs
        ).grid(row=0, column=1, sticky="w", padx=8, pady=2)

        e_tin = self._labeled_entry(frm_tin, 1, 0, "T_in (°C)", self.fiss_t_in_var)
        e_tini = self._labeled_entry(frm_tin, 2, 0, "T_ini (°C)", self.fiss_t_ini_var)
        e_tfin = self._labeled_entry(frm_tin, 2, 2, "T_fin (°C)", self.fiss_t_fin_var)
        e_tstep = self._labeled_entry(frm_tin, 3, 0, "T_step (°C)", self.fiss_t_step_var)

        self._t_entries = {"T_in": e_tin, "T_ini": e_tini, "T_fin": e_tfin, "T_step": e_tstep}

        frm_fiss_btn = ttk.Frame(frm_fiss)
        frm_fiss_btn.grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=6)
        ttk.Button(frm_fiss_btn, text="Calcul (FISS)", command=self._run_fiss).pack(side="left", padx=5)
        ttk.Button(frm_fiss_btn, text="Post-Process", command=self._postprocess_picker).pack(side="left", padx=5)

        self._refresh_fiss_model_inputs()
        self._refresh_fiss_bc_inputs()

        # ----------------------------
        # Buttons
        # ----------------------------
        frm_btn = ttk.Frame(parent)
        frm_btn.pack(fill="x", padx=10, pady=6)

        ttk.Button(frm_btn, text="Run converter", command=self._run).pack(side="left", padx=5)
        ttk.Button(frm_btn, text="Open working directory", command=self._open_workdir).pack(side="left", padx=5)
        ttk.Button(frm_btn, text="Clear log", command=self._clear_log).pack(side="left", padx=5)

        # ----------------------------
        # Log
        # ----------------------------
        frm_log = ttk.LabelFrame(parent, text="Log")
        frm_log.pack(fill="both", expand=True, padx=10, pady=8)

        self.log = tk.Text(frm_log, wrap="word")
        self.log.pack(fill="both", expand=True, padx=8, pady=8)
        self._log("Ready.\n")

    def _labeled_entry(self, parent, row, col, label, var):
        pad = {"padx": 8, "pady": 4}
        ttk.Label(parent, text=label + ":").grid(row=row, column=col, sticky="w", **pad)
        ent = ttk.Entry(parent, textvariable=var, width=14)
        ent.grid(row=row, column=col + 1, sticky="w", **pad)
        return ent

    def _csv_row(self, parent, r, label, var, cmd):
        pad = {"padx": 8, "pady": 5}
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", **pad)
        ttk.Entry(parent, textvariable=var, width=95).grid(row=r, column=1, sticky="we", **pad)
        ttk.Button(parent, text="Browse", command=cmd).grid(row=r, column=2, **pad)
        parent.columnconfigure(1, weight=1)

    def _log(self, msg: str):
        self.log.insert("end", msg)
        self.log.see("end")
        self.update_idletasks()

    def _clear_log(self):
        self.log.delete("1.0", "end")

    def _open_workdir(self):
        wd = self.workdir_var.get().strip()
        if not wd:
            return
        p = Path(wd)
        if not p.exists():
            return
        try:
            os.startfile(str(p))
        except Exception:
            pass

    # ----------------------------
    # Browsers
    # ----------------------------

    def _browse_dgibi(self):
        p = filedialog.askopenfilename(filetypes=[("DGIBI", "*.dgibi"), ("All", "*.*")])
        if p:
            self.dgibi_var.set(p)

    def _browse_workdir(self):
        p = filedialog.askdirectory()
        if p:
            self.workdir_var.set(p)

    def _browse_csv_x(self):
        self._browse_csv_to(self.csv_x_var)

    def _browse_csv_y(self):
        self._browse_csv_to(self.csv_y_var)

    def _browse_csv_zmax(self):
        self._browse_csv_to(self.csv_zmax_var)

    def _browse_csv_zmin(self):
        self._browse_csv_to(self.csv_zmin_var)

    def _browse_csv_to(self, var):
        p = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if p:
            var.set(p)

    # ----------------------------
    # Holes UI
    # ----------------------------

    def _toggle_holes(self):
        enabled = self.holes_enabled_var.get()
        state = "normal" if enabled else "disabled"
        for child in self.holes_container.grid_slaves():
            info = child.grid_info()
            if info.get("row", 0) >= 5:
                try:
                    if "state" in child.keys():
                        child.configure(state=state)
                except Exception:
                    pass

    def _add_hole_row(self):
        row_index = self.holes_rows_start + len(self.hole_rows)

        v_cx = tk.StringVar(value="0.0")
        v_cy = tk.StringVar(value="0.0")
        v_r = tk.StringVar(value="0.07")
        self.hole_rows.append((v_cx, v_cy, v_r))

        state = "normal" if self.holes_enabled_var.get() else "disabled"

        lbl = ttk.Label(self.holes_container, text=f"Hole {len(self.hole_rows)}")
        e1 = ttk.Entry(self.holes_container, textvariable=v_cx, width=12)
        e2 = ttk.Entry(self.holes_container, textvariable=v_cy, width=12)
        e3 = ttk.Entry(self.holes_container, textvariable=v_r, width=12)

        lbl.grid(row=row_index, column=0, sticky="w", padx=8, pady=3)
        e1.grid(row=row_index, column=1, sticky="w", padx=8, pady=3)
        e2.grid(row=row_index, column=2, sticky="w", padx=8, pady=3)
        e3.grid(row=row_index, column=3, sticky="w", padx=8, pady=3)

        e1.configure(state=state)
        e2.configure(state=state)
        e3.configure(state=state)

        self.hole_row_widgets.append((lbl, e1, e2, e3))

    def _remove_hole_row(self):
        if not self.hole_rows:
            return
        widgets = self.hole_row_widgets.pop()
        for w in widgets:
            w.destroy()
        self.hole_rows.pop()

    # ----------------------------
    # Read params
    # ----------------------------

    def _read_params(self) -> CastemMainParams:
        p = CastemMainParams()
        p.re_ti = int(self.re_ti_var.get().strip())
        p.re_crpa = int(self.re_crpa_var.get().strip())
        p.re_smfa = parse_float(self.re_smfa_var.get())
        p.re_numspa = int(self.re_numspa_var.get().strip())
        p.re_opmin = parse_float(self.re_opmin_var.get())

        p.nelem_x = int(self.nelem_x_var.get().strip())
        p.nelem_y = int(self.nelem_y_var.get().strip())
        p.nelem_z = int(self.nelem_z_var.get().strip())
        p.re_tol = parse_float(self.re_tol_var.get())

        p.re_fact_z = parse_float(self.re_fact_z_var.get())

        p.num_el_fill = int(self.num_el_fill_var.get().strip())
        p.re_fact_hole = parse_float(self.re_fact_hole_var.get())

        p.opti_visu = 1 if self.opti_visu_var.get() else 0
        p.opti_med = 1 if self.opti_med_var.get() else 0
        p.opti_stl = 1 if self.opti_stl_var.get() else 0

        p.holes_enabled = self.holes_enabled_var.get()

        holes: List[Hole] = []
        if p.holes_enabled:
            for (v_cx, v_cy, v_r) in self.hole_rows:
                cx = parse_float(v_cx.get())
                cy = parse_float(v_cy.get())
                rr = parse_float(v_r.get())
                holes.append(Hole(cx=cx, cy=cy, r=rr))
        p.holes = holes
        return p

    # ----------------------------
    # FISS UI handlers
    # ----------------------------

    def _browse_fiss_dgibi(self):
        p = filedialog.askopenfilename(filetypes=[("DGIBI", "*.dgibi"), ("All", "*.*")])
        if p:
            self.fiss_dgibi_var.set(p)

    def _clear_children(self, parent):
        for w in parent.winfo_children():
            w.destroy()

    def _refresh_fiss_model_inputs(self):
        self._clear_children(self.frm_fiss_dyn)
        pad = {"padx": 8, "pady": 4}
        model = self.fiss_model_var.get().strip()

        r = 0
        if model == "POISEU_BLASIUS":
            ttk.Label(self.frm_fiss_dyn, text="No material parameter required (RUGO fixed to 0.0).").grid(
                row=r, column=0, sticky="w", **pad
            )

        elif model == "POISEU_COLEBROOK":
            ttk.Label(self.frm_fiss_dyn, text="Roughness RUGO (m):").grid(row=r, column=0, sticky="w", **pad)
            ttk.Entry(self.frm_fiss_dyn, textvariable=self.fiss_rugo_var, width=16).grid(row=r, column=1, sticky="w", **pad)

        elif model in ("POISEU_GELAIN_2008", "POISEU_GELAIN_2012", "POISEU_RIZKALLA"):
            ttk.Label(self.frm_fiss_dyn, text="Critical Reynolds REC (unitless):").grid(row=r, column=0, sticky="w", **pad)
            ttk.Entry(self.frm_fiss_dyn, textvariable=self.fiss_rec_var, width=16).grid(row=r, column=1, sticky="w", **pad)

        elif model in ("FROTTEMENT1", "FROTTEMENT2"):
            ttk.Label(self.frm_fiss_dyn, text="REC (unitless):").grid(row=r, column=0, sticky="w", **pad)
            ttk.Entry(self.frm_fiss_dyn, textvariable=self.fiss_rec_var, width=16).grid(row=r, column=1, sticky="w", **pad)
            r += 1
            for lab, var in [
                ("FK", self.fiss_fk_var),
                ("FA", self.fiss_fa_var),
                ("FB", self.fiss_fb_var),
                ("FC", self.fiss_fc_var),
                ("FD", self.fiss_fd_var),
            ]:
                ttk.Label(self.frm_fiss_dyn, text=f"{lab}:").grid(row=r, column=0, sticky="w", **pad)
                ttk.Entry(self.frm_fiss_dyn, textvariable=var, width=16).grid(row=r, column=1, sticky="w", **pad)
                r += 1

        elif model in ("FROTTEMENT3", "FROTTEMENT4"):
            ttk.Label(self.frm_fiss_dyn, text="Roughness RUGO (m):").grid(row=r, column=0, sticky="w", **pad)
            ttk.Entry(self.frm_fiss_dyn, textvariable=self.fiss_rugo_var, width=16).grid(row=r, column=1, sticky="w", **pad)
            r += 1
            ttk.Label(self.frm_fiss_dyn, text="FK:").grid(row=r, column=0, sticky="w", **pad)
            ttk.Entry(self.frm_fiss_dyn, textvariable=self.fiss_fk_k_var, width=16).grid(row=r, column=1, sticky="w", **pad)

    def _set_state(self, widgets: list[ttk.Entry], state: str):
        for w in widgets:
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _refresh_fiss_bc_inputs(self):
        p_mode = self.fiss_p_mode_var.get().strip().lower()
        t_mode = self.fiss_t_mode_var.get().strip().lower()

        if self._p_entries:
            if p_mode == "single":
                self._set_state([self._p_entries["P_in"]], "normal")
                self._set_state([self._p_entries["P_ini"], self._p_entries["P_fin"], self._p_entries["P_step"]], "disabled")
            else:
                self._set_state([self._p_entries["P_in"]], "disabled")
                self._set_state([self._p_entries["P_ini"], self._p_entries["P_fin"], self._p_entries["P_step"]], "normal")

        if self._t_entries:
            if t_mode == "single":
                self._set_state([self._t_entries["T_in"]], "normal")
                self._set_state([self._t_entries["T_ini"], self._t_entries["T_fin"], self._t_entries["T_step"]], "disabled")
            else:
                self._set_state([self._t_entries["T_in"]], "disabled")
                self._set_state([self._t_entries["T_ini"], self._t_entries["T_fin"], self._t_entries["T_step"]], "normal")

    # ----------------------------
    # Helpers for file naming
    # ----------------------------

    def _expected_csv_names(self, p: CastemMainParams):
        base = f"ti{p.re_ti}_crpa{p.re_crpa}_smfa{p.re_smfa_int}_numsp{p.re_numspa}_opmin{p.re_opmin_int}"
        return {
            "xrange": f"xrange_{base}.csv",
            "yrange": f"yrange_{base}.csv",
            "zfit_zmax": f"zfit_zmax_{base}.csv",
            "zfit_zmin": f"zfit_zmin_{base}.csv",
        }

    def _patch_fiss_vars(self, template_text: str, fiss: FissSetup) -> str:
        idx = template_text.find(MAIN_BLOCK_START)
        if idx < 0:
            raise ValueError("Could not find the Main Program block marker in the dgibi.")

        head = template_text[:idx]
        block = template_text[idx:]

        block = _replace_assign_in_block(block, "num_elem_y", str(fiss.num_elem_y))
        block = _replace_assign_in_block(block, "temp_wall", f"{fiss.temp_wall:.12g}")
        block = _replace_assign_in_block(block, "P_aval", f"{fiss.p_aval:.12g}")
        block = _replace_assign_in_block(block, "P_steam_amont", f"{fiss.psteam:.12g}")

        block = _replace_assign_in_block(block, "mot_mode_user", f"CHAI '{fiss.model}'")
        block = _replace_assign_in_block(block, "mot_gaz", f"CHAI '{fiss.gas}'")
        block = _replace_assign_in_block(block, "mot_cond", f"CHAI '{fiss.cond}'")

        if fiss.p_mode == "single":
            block = _replace_assign_in_block(block, "P_amont", _format_prog_single(float(fiss.p_in)))
            block = _replace_assign_in_block(block, "P_am", f"{float(fiss.p_in):.12g}")
        else:
            block = _replace_assign_in_block(block, "P_am", f"{float(fiss.p_fin):.12g}")
            block = _replace_assign_in_block(block, "step_P", f"{float(fiss.p_step):.12g}")
            block = _replace_assign_in_block(block, "P_amont", _format_prog_range(float(fiss.p_ini), float(fiss.p_step), float(fiss.p_fin)))

        if fiss.t_mode == "single":
            block = _replace_assign_in_block(block, "temp_amont", _format_prog_single(float(fiss.t_in)))
            block = _replace_assign_in_block(block, "T_in", f"{float(fiss.t_in):.12g}")
            block = _replace_assign_in_block(block, "T_fin", f"{float(fiss.t_in):.12g}")
            block = _replace_assign_in_block(block, "step_T", "1.0")
        else:
            block = _replace_assign_in_block(block, "T_in", f"{float(fiss.t_ini):.12g}")
            block = _replace_assign_in_block(block, "T_fin", f"{float(fiss.t_fin):.12g}")
            block = _replace_assign_in_block(block, "step_T", f"{float(fiss.t_step):.12g}")
            block = _replace_assign_in_block(block, "temp_amont", _format_prog_range(float(fiss.t_ini), float(fiss.t_step), float(fiss.t_fin)))

        if fiss.rugo is not None:
            block = _replace_assign_in_block(block, "re_rugo", f"{float(fiss.rugo):.12g}")
        if fiss.rec is not None:
            block = _replace_assign_in_block(block, "re_rec", f"{float(fiss.rec):.12g}")
        if fiss.fk is not None:
            block = _replace_assign_in_block(block, "re_fk", f"{float(fiss.fk):.12g}")
            block = _replace_assign_in_block(block, "re_fa", f"{float(fiss.fa):.12g}")
            block = _replace_assign_in_block(block, "re_fb", f"{float(fiss.fb):.12g}")
            block = _replace_assign_in_block(block, "re_fc", f"{float(fiss.fc):.12g}")
            block = _replace_assign_in_block(block, "re_fd", f"{float(fiss.fd):.12g}")
        if fiss.fk_k is not None:
            block = _replace_assign_in_block(block, "re_fk", f"{float(fiss.fk_k):.12g}")

        return head + block

    # ----------------------------
    # FISS: read setup + run
    # ----------------------------

    def _read_fiss_setup(self) -> FissSetup:
        model = self.fiss_model_var.get().strip()
        gas = self.fiss_gas_var.get().strip()
        cond = self.fiss_cond_var.get().strip()

        temp_wall = parse_float(self.fiss_temp_wall_var.get())
        p_aval = parse_float(self.fiss_p_aval_var.get())
        psteam = parse_float(self.fiss_psteam_var.get())
        num_elem_y = int(self.fiss_num_elem_y_var.get().strip())

        p_mode = self.fiss_p_mode_var.get().strip()
        t_mode = self.fiss_t_mode_var.get().strip()

        rugo = rec = fk = fa = fb = fc = fd = fk_k = None

        if model == "POISEU_BLASIUS":
            rugo = 0.0
        elif model == "POISEU_COLEBROOK":
            rugo = parse_float(self.fiss_rugo_var.get())
        elif model in ("POISEU_GELAIN_2008", "POISEU_GELAIN_2012", "POISEU_RIZKALLA"):
            rec = parse_float(self.fiss_rec_var.get())
        elif model in ("FROTTEMENT1", "FROTTEMENT2"):
            rec = parse_float(self.fiss_rec_var.get())
            fk = parse_float(self.fiss_fk_var.get())
            fa = parse_float(self.fiss_fa_var.get())
            fb = parse_float(self.fiss_fb_var.get())
            fc = parse_float(self.fiss_fc_var.get())
            fd = parse_float(self.fiss_fd_var.get())
        elif model in ("FROTTEMENT3", "FROTTEMENT4"):
            rugo = parse_float(self.fiss_rugo_var.get())
            fk_k = parse_float(self.fiss_fk_k_var.get())

        if p_mode == "single":
            p_in = parse_float(self.fiss_p_in_var.get())
            p_ini = p_fin = p_step = None
        else:
            p_in = None
            p_ini = parse_float(self.fiss_p_ini_var.get())
            p_fin = parse_float(self.fiss_p_fin_var.get())
            p_step = parse_float(self.fiss_p_step_var.get())
            if p_step <= 0:
                raise ValueError("Pressure step must be > 0")

        if t_mode == "single":
            t_in = parse_float(self.fiss_t_in_var.get())
            t_ini = t_fin = t_step = None
        else:
            t_in = None
            t_ini = parse_float(self.fiss_t_ini_var.get())
            t_fin = parse_float(self.fiss_t_fin_var.get())
            t_step = parse_float(self.fiss_t_step_var.get())
            if t_step <= 0:
                raise ValueError("Temperature step must be > 0")

        if p_mode != "single" and p_fin is not None and p_ini is not None and p_step is not None:
            nP = int(abs(p_fin - p_ini) / max(p_step, 1e-30)) + 1
            if nP > 5000:
                raise ValueError(f"Too many pressure steps ({nP}). Check P_ini/P_fin/P_step.")

        if t_mode != "single" and t_fin is not None and t_ini is not None and t_step is not None:
            nT = int(abs(t_fin - t_ini) / max(t_step, 1e-30)) + 1
            if nT > 5000:
                raise ValueError(f"Too many temperature steps ({nT}). Check T_ini/T_fin/T_step.")

        return FissSetup(
            model=model, gas=gas, cond=cond,
            rugo=rugo, rec=rec, fk=fk, fa=fa, fb=fb, fc=fc, fd=fd, fk_k=fk_k,
            temp_wall=temp_wall, p_aval=p_aval, psteam=psteam, num_elem_y=num_elem_y,
            p_mode=p_mode, p_in=p_in, p_ini=p_ini, p_fin=p_fin, p_step=p_step,
            t_mode=t_mode, t_in=t_in, t_ini=t_ini, t_fin=t_fin, t_step=t_step,
        )

    def _next_calcul_dir(self, base: Path) -> Path:
        base.mkdir(parents=True, exist_ok=True)
        existing = [p for p in base.glob("Calcul*") if p.is_dir()]
        idx = 0
        for p in existing:
            m = re.match(r"Calcul(\d+)$", p.name)
            if m:
                idx = max(idx, int(m.group(1)))
        new_dir = base / f"Calcul{idx+1}"
        new_dir.mkdir(parents=True, exist_ok=False)
        return new_dir

    # ----------------------------
    # PATCH 1/2 applied: _run_fiss with streaming log
    # ----------------------------

    def _run_fiss(self):
        try:
            fiss_tpl = Path(self.fiss_dgibi_var.get().strip())
            if not fiss_tpl.exists():
                raise FileNotFoundError("FISS dgibi template not found.")

            workdir = ensure_dir(self.workdir_var.get().strip())
            castem_exe = resolve_castem_exe(self.castem_version_var.get())

            csv_x = Path(self.csv_x_var.get().strip())
            csv_y = Path(self.csv_y_var.get().strip())
            csv_zmax = Path(self.csv_zmax_var.get().strip())
            csv_zmin = Path(self.csv_zmin_var.get().strip())
            for f in [csv_x, csv_y, csv_zmax, csv_zmin]:
                if not f.exists():
                    raise FileNotFoundError(f"CSV not found:\n{f}")

            p = self._read_params()
            self._validate_params(p)
            fiss = self._read_fiss_setup()

        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        model_dir = workdir / fiss.model
        try:
            calc_dir = self._next_calcul_dir(model_dir)
        except Exception as e:
            messagebox.showerror("Directory error", str(e))
            return

        self._log("\n===== FISS RUN START =====\n")
        self._log(f"Model: {fiss.model}\n")
        self._log(f"Calc dir: {calc_dir}\n")

        names = self._expected_csv_names(p)
        safe_copy(csv_x, calc_dir / names["xrange"])
        safe_copy(csv_y, calc_dir / names["yrange"])
        safe_copy(csv_zmax, calc_dir / names["zfit_zmax"])
        safe_copy(csv_zmin, calc_dir / names["zfit_zmin"])

        template_text = fiss_tpl.read_text(encoding="utf-8", errors="ignore")
        patched = patch_dgibi_main_program(template_text, p)
        patched = self._patch_fiss_vars(patched, fiss)

        out_dgibi = calc_dir / (
            f"{fiss_tpl.stem}_{fiss.model}_ti{p.re_ti}_crpa{p.re_crpa}_smfa{p.re_smfa_int}_"
            f"numsp{p.re_numspa}_opmin{p.re_opmin_int}.dgibi"
        )
        out_dgibi.write_text(patched, encoding="utf-8")
        self._log(f"Generated FISS DGIBI: {out_dgibi.name}\n")

        cmd = ["cmd.exe", "/c", str(castem_exe), str(out_dgibi)]
        self._log("Running CASTEM (FISS)...\n")

        def after_castem(rc: int):
            if rc != 0:
                messagebox.showerror("CASTEM error", f"CASTEM failed, return code {rc}")
                self._log("===== FISS RUN END (FAILED) =====\n")
                return
            self._log("===== FISS RUN END =====\n")

        self._stream_process_to_log(cmd, calc_dir, on_done=after_castem)



    # --- ADD these helper methods INSIDE class App (put them near the post-process methods) ---

    def _find_any_txt_inputs(self, folder: Path) -> bool:
        # geometry txt?
        geo = (
            list(folder.glob("xi*_ti*.txt")) or
            list(folder.glob("yi*_ti*.txt")) or
            list(folder.glob("zi*_ti*.txt")) or
            list(folder.glob("ouvi*_ti*.txt")) or
            list(folder.glob("etendi*_ti*.txt"))
        )
        if geo:
            return True

        # result-grid txt?
        pat = re.compile(
            r"^(P|PV|TF|U|H|RE|Q|QA|QE|F)_P\d+_\d+_T\d+_\d+_ti.*\.txt$"
        )
        for f in folder.glob("*.txt"):
            if pat.match(f.name):
                return True
        return False


    def _find_existing_h5(self, folder: Path) -> Path | None:
        # support your naming: result.h (if it is actually an HDF5), and common .h5 names
        candidates = [
            folder / "results.h5",
            folder / "result.h5",
            folder / "result.h",
            folder / "results.h",
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                return c
        return None


    def _quarantine_files(self, folder: Path, files: list[Path], log) -> int:
        if not files:
            return 0
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        qdir = folder / f"_txt_quarantine_{stamp}"
        qdir.mkdir(parents=True, exist_ok=True)

        moved = 0
        for src in files:
            try:
                if not src.exists():
                    continue
                dst = qdir / src.name
                # avoid overwrite
                if dst.exists():
                    dst = qdir / f"{src.stem}_{moved}{src.suffix}"
                shutil.move(str(src), str(dst))
                moved += 1
            except Exception as e:
                log(f"[Post] Could not move {src.name}: {e}\n")
        return moved


    def _collect_known_txt_outputs(self, folder: Path) -> list[Path]:
        out: list[Path] = []

        # geometry outputs
        for gpat in ["xi*_ti*.txt", "yi*_ti*.txt", "zi*_ti*.txt", "ouvi*_ti*.txt", "etendi*_ti*.txt"]:
            out.extend(folder.glob(gpat))

        # result outputs
        pat = re.compile(
            r"^(P|PV|TF|U|H|RE|Q|QA|QE|F|X)_P\d+_\d+_T\d+_\d+_ti.*\.txt$"
        )
        for f in folder.glob("*.txt"):
            if pat.match(f.name):
                out.append(f)

        # unique
        uniq = []
        seen = set()
        for p in out:
            rp = str(p.resolve())
            if rp not in seen:
                seen.add(rp)
                uniq.append(p)
        return uniq


    def _convert_txt_to_h5(self, folder: Path, h5_path: Path, log) -> Path:
        if h5py is None:
            raise RuntimeError("h5py is not installed. Install it with: pip install h5py")

        # load geometry + scan results using your existing functions
        line_ids, Xi, Yi, Zi, Ouv, Eten = self._load_geometry(folder)
        store, Ps, Ts, _lines_from_scan = self._scan_result_grid(folder)

        # backup existing h5 if present
        if h5_path.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            bak = h5_path.with_suffix(h5_path.suffix + f".bak_{stamp}")
            try:
                h5_path.replace(bak)
                log(f"[Post] Existing {h5_path.name} backed up -> {bak.name}\n")
            except Exception:
                pass

        log(f"[Post] Writing HDF5: {h5_path.name}\n")

        # helper: read vector col2 from txt (fast+robust enough)
        def _read_col2(fp: Path) -> np.ndarray:
            data = np.genfromtxt(str(fp), delimiter=";", dtype=float, invalid_raise=False)
            data = np.atleast_2d(data)
            if data.shape[1] < 2:
                # fallback: whitespace
                data2 = np.loadtxt(str(fp))
                data2 = np.atleast_2d(data2)
                return data2[:, 1].astype(float)
            return data[:, 1].astype(float)

        with h5py.File(str(h5_path), "w") as h5:
            # meta
            meta = h5.create_group("meta")
            meta.create_dataset("line_ids", data=np.asarray(line_ids, dtype=np.int32))
            meta.create_dataset("Ps", data=np.asarray(Ps, dtype=np.int32))
            meta.create_dataset("Ts", data=np.asarray(Ts, dtype=np.int32))

            # geometry
            geo = h5.create_group("geometry")
            geo.create_dataset("Xi", data=np.asarray(Xi, dtype=np.float64))
            geo.create_dataset("Yi", data=np.asarray(Yi, dtype=np.float64))
            geo.create_dataset("Zi", data=np.asarray(Zi, dtype=np.float64))
            geo.create_dataset("Ouv", data=np.asarray(Ouv, dtype=np.float64))
            geo.create_dataset("Eten", data=np.asarray(Eten, dtype=np.float64))

            # results
            res = h5.create_group("results")
            vars_found = sorted(store.keys())
            for var in vars_found:
                gv = res.create_group(var)
                for (p, t), files_by_line in store[var].items():
                    # read all lines, allow missing lines -> NaN padded
                    vecs: list[np.ndarray | None] = []
                    maxlen = 0
                    mask = np.zeros((len(line_ids),), dtype=np.uint8)

                    for j, i in enumerate(line_ids):
                        fp = files_by_line.get(i)
                        if fp is None or not Path(fp).exists():
                            vecs.append(None)
                            continue
                        v = _read_col2(Path(fp))
                        vecs.append(v)
                        mask[j] = 1
                        if v.size > maxlen:
                            maxlen = int(v.size)

                    if maxlen <= 0:
                        continue

                    arr = np.full((len(line_ids), maxlen), np.nan, dtype=np.float64)
                    for j, v in enumerate(vecs):
                        if v is None:
                            continue
                        arr[j, : v.size] = v

                    name = f"P{int(p)}_T{int(t)}"
                    gv.create_dataset(name, data=arr)
                    gv.create_dataset(name + "_mask", data=mask)

        log("[Post] HDF5 write done.\n")
        return h5_path


    # ----------------------------
    # Post-process
    # ----------------------------

    def _read_two_col_txt(self, path: Path) -> np.ndarray:
        # If there are weird spaces, genfromtxt handles it better than loadtxt
        data = np.genfromtxt(str(path), delimiter=";", dtype=float, invalid_raise=True)
        data = np.atleast_2d(data)
        return data[:, 1]

    def _load_geometry(self, folder: Path):
        ouvis = sorted(folder.glob("ouvi*_ti*.txt"))
        if not ouvis:
            raise FileNotFoundError("No ouvi*_ti*.txt found in folder")

        def get_i(p: Path) -> int:
            m = re.match(r"ouvi(\d+)_ti", p.name)
            if not m:
                m = re.search(r"ouvi(\d+)", p.name)
            return int(m.group(1))

        line_ids = sorted({get_i(p) for p in ouvis})

        Xi, Yi, Zi, Ouv, Eten = [], [], [], [], []
        for i in line_ids:
            fx = next(folder.glob(f"xi{i}_ti*.txt"))
            fy = next(folder.glob(f"yi{i}_ti*.txt"))
            fz = next(folder.glob(f"zi{i}_ti*.txt"))
            fo = next(folder.glob(f"ouvi{i}_ti*.txt"))
            fe = next(folder.glob(f"etendi{i}_ti*.txt"))

            x = self._read_two_col_txt(fx)
            y = self._read_two_col_txt(fy)
            z = self._read_two_col_txt(fz)
            ou = self._read_two_col_txt(fo)
            et = self._read_two_col_txt(fe)

            Xi.append(x); Yi.append(y); Zi.append(z); Ouv.append(ou); Eten.append(et)

        return line_ids, np.vstack(Xi), np.vstack(Yi), np.vstack(Zi), np.vstack(Ouv), np.vstack(Eten)

    # ============================================================
    # PATCH 2/2: scan regex includes F
    # ============================================================
    def _scan_result_grid(self, folder: Path):
        pattern = re.compile(
            r"^(?P<var>P|PV|TF|U|H|RE|Q|QA|QE|F|X)_P(?P<i>\d+)_(?P<p>\d+)_T(?P<i2>\d+)_(?P<t>\d+)_ti.*\.txt$"
        )

        store = {}
        Ps = set()
        Ts = set()
        lines = set()

        for f in folder.glob("*.txt"):
            m = pattern.match(f.name)
            if not m:
                continue
            var = m.group("var")
            i = int(m.group("i"))
            p = int(m.group("p"))
            t = int(m.group("t"))

            Ps.add(p); Ts.add(t); lines.add(i)
            store.setdefault(var, {}).setdefault((p, t), {})[i] = f

        return store, sorted(Ps), sorted(Ts), sorted(lines)

    # --- REPLACE your _postprocess_picker with this version (INSIDE class App) ---

    def _postprocess_picker(self):
        d = filedialog.askdirectory()
        if not d:
            return
        folder = Path(d)

        self._log("\n===== POST-PROCESS START =====\n")
        self._log(f"Folder: {folder}\n")

        h5_path_default = folder / "results.h5"

        try:
            if self._find_any_txt_inputs(folder):
                self._log("[Post] TXT results found -> converting to one HDF5 file...\n")
                h5_path = self._convert_txt_to_h5(folder, h5_path_default, self._log)

                # delete safely AFTER successful conversion
                txt_files = self._collect_known_txt_outputs(folder)
                moved = self._quarantine_files(folder, txt_files, self._log)
                self._log(f"[Post] Quarantined {moved} txt files.\n")

            else:
                self._log("[Post] No TXT results found. Searching for existing result.h5 / result.h...\n")
                existing = self._find_existing_h5(folder)
                if existing is None:
                    raise FileNotFoundError(
                        "No TXT files found, and no result.h5/result.h found.\n"
                        "=> No results available in this folder."
                    )
                h5_path = existing
                self._log(f"[Post] Using existing HDF5: {h5_path.name}\n")

            # load from HDF5
            h5store = H5ResultStore(h5_path)
            Xi, Yi, Zi, Ouv, Eten = h5store.geometry()
            line_ids = h5store.line_ids
            Ps = h5store.Ps
            Ts = h5store.Ts
            lines = list(line_ids)

        except Exception as e:
            messagebox.showerror("Post-process error", str(e))
            self._log(f"ERROR: {e}\n")
            self._log("===== POST-PROCESS END (FAILED) =====\n")
            return

        self._log("Opening post-processing window...\n")
        self._open_postprocess_window(folder, line_ids, Xi, Yi, Zi, Ouv, Eten, h5store, Ps, Ts, lines)
        self._log("===== POST-PROCESS WINDOW OPENED =====\n")

    # ----------------------------
    # PATCH 2/2: Replace _open_postprocess_window entirely
    # + EXTRA: log post-processing actions to main log
    # ----------------------------

    def _open_postprocess_window(self, folder, line_ids, Xi, Yi, Zi, Ouv, Eten, store, Ps, Ts, lines):
        log = self._log
        win = tk.Toplevel(self)
        win.title("FISS Post-processing (dynamic)")
        win.geometry("1400x900")
        is_h5 = hasattr(store, "load") and callable(getattr(store, "load", None))

        def _on_close():
            try:
                if is_h5:
                    store.close()
            finally:
                win.destroy()

        win.protocol("WM_DELETE_WINDOW", _on_close)



        # --------- build geometry grids once
        order = np.argsort(Xi[:, 0])
        x_line = Xi[order, 0]
        Y_sorted = Yi[order, :]
        Z_sorted = Zi[order, :]
        O_sorted = Ouv[order, :]

        y_vec = Y_sorted[0, :]
        Xg, Yg = np.meshgrid(x_line, y_vec, indexing="ij")

        # units
        Xg_cm = Xg * 1e2
        Yg_cm = Yg * 1e2
        Zg_cm = Z_sorted * 1e2
        O_um = O_sorted * 1e6

        x_min, x_max = float(np.nanmin(Xg_cm)), float(np.nanmax(Xg_cm))
        y_min, y_max = float(np.nanmin(Yg_cm)), float(np.nanmax(Yg_cm))
        z_min, z_max = float(np.nanmin(Zg_cm)), float(np.nanmax(Zg_cm))
        dx = max(x_max - x_min, 1e-30)
        dy = max(y_max - y_min, 1e-30)
        dz = max(z_max - z_min, 1e-30)

        cmap_name = "jet"

        def read_col2_txt(fp: Path, delimiter=";") -> np.ndarray:
            data = np.loadtxt(str(fp), delimiter=delimiter)
            return np.array([float(data[1])], dtype=float) if data.ndim == 1 else data[:, 1].astype(float)

        # --------- LAZY loading: do NOT build full data_grid for all (P,T)
        vars_to_load = ["P", "PV", "TF", "U", "H", "RE", "Q", "QA", "QE", "F","X"]

        available: dict[tuple[int, int], dict[str, bool]] = {}
        log("[Post] Building availability map...\n")

        for pp in Ps:
            for tt in Ts:
                key = (pp, tt)
                available[key] = {}
                for var in vars_to_load:
                    if is_h5:
                        # "available" means: dataset exists AND is complete for all line_ids
                        available[key][var] = bool(store.has(var, pp, tt) and store.complete(var, pp, tt))
                    else:
                        if var not in store or key not in store[var]:
                            available[key][var] = False
                            continue
                        files_by_line = store[var][key]
                        available[key][var] = all((i in files_by_line) for i in line_ids)

        log("[Post] Availability map ready.\n")

        # ---------- small LRU-like cache for loaded arrays
        # cache key: (var, p, t) -> np.ndarray (n_lines, n_points)
        _cache: dict[tuple[str, int, int], np.ndarray] = {}
        _cache_order: list[tuple[str, int, int]] = []
        _CACHE_MAX = 24  # tune (e.g. 8, 16, 24). Keeps memory bounded.

        def _cache_put(k, arr):
            if k in _cache:
                return
            _cache[k] = arr
            _cache_order.append(k)
            if len(_cache_order) > _CACHE_MAX:
                old = _cache_order.pop(0)
                _cache.pop(old, None)

        def read_col2_vector(fp: Path, delimiter=";") -> np.ndarray:
            # full profile vector (used for 3D surfaces)
            data = np.loadtxt(str(fp), delimiter=delimiter)
            return np.array([float(data[1])], dtype=float) if data.ndim == 1 else data[:, 1].astype(float)

        def read_col2_last(fp: Path, delimiter=";") -> float:
            # fast: read last non-empty line only (used for Q/QA/QE last column use)
            with fp.open("r", encoding="utf-8", errors="ignore") as f:
                last = ""
                for line in f:
                    if line.strip():
                        last = line
            if not last:
                raise ValueError(f"Empty file: {fp.name}")
            parts = [p.strip() for p in last.split(delimiter)]
            if len(parts) < 2:
                # fallback: whitespace split
                parts = last.split()
            return float(parts[1].replace(",", "."))

        # --- PATCH inside _open_postprocess_window ---
        # 3) Replace load_case_var() with this version (it supports both TXT-store and H5-store):

        def load_case_var(pp: int, tt: int, var: str) -> np.ndarray | None:
            """
            Returns array shape (n_lines, n_points) for this (P,T,var),
            lazily loaded and cached. Returns None if missing.
            """
            key = (pp, tt)
            if not available.get(key, {}).get(var, False):
                return None

            ck = (var, pp, tt)
            if ck in _cache:
                return _cache[ck]

            if is_h5:
                arr = store.load(var, pp, tt)
                if arr is None:
                    return None
                arr = np.asarray(arr)
                _cache_put(ck, arr)
                return arr

            # TXT mode (your original)
            files_by_line = store[var][key]
            profiles = []
            for i in line_ids:
                fp = files_by_line.get(i)
                if fp is None:
                    return None
                profiles.append(read_col2_vector(fp, delimiter=";"))

            arr = np.vstack(profiles)
            _cache_put(ck, arr)
            return arr

        # --------- UI controls
        top = ttk.Frame(win)
        top.pack(fill="x", padx=10, pady=8)

        Ps_bar = [float(p) * 1e-5 for p in Ps]  # Pa -> bar
        Ts_val = [float(t) for t in Ts]

        ttk.Label(top, text="Pressure (bar):").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        p_combo = ttk.Combobox(top, values=[f"{v:.6g}" for v in Ps_bar], width=16, state="readonly")
        p_combo.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        if Ps_bar:
            p_combo.current(0)

        ttk.Label(top, text="Temperature (°C):").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        t_combo = ttk.Combobox(top, values=[f"{v:.6g}" for v in Ts_val], width=16, state="readonly")
        t_combo.grid(row=0, column=3, sticky="w", padx=6, pady=4)
        if Ts_val:
            t_combo.current(0)

        ttk.Label(top, text="Field:").grid(row=0, column=4, sticky="w", padx=6, pady=4)
        field_var = tk.StringVar(value="OPENING")
        field_combo = ttk.Combobox(
            top,
            textvariable=field_var,
            values=[
                "OPENING",
                "P", "PV", "U", "RE", "TF", "H", "F","X",
                "FLOW_VS_X",
                "PT_TOTAL_FLOW",
            ],
            width=16,
            state="readonly",
        )
        field_combo.grid(row=0, column=5, sticky="w", padx=6, pady=4)

        plot_mode = tk.StringVar(value="XYZ_SURFACE")
        ttk.Radiobutton(top, text="XYZ surface", value="XYZ_SURFACE", variable=plot_mode).grid(row=0, column=6, padx=6, pady=4)
        ttk.Radiobutton(top, text="XY colored lines", value="XY_LINES", variable=plot_mode).grid(row=0, column=7, padx=6, pady=4)

        ttk.Label(top, text="Flow key:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        flow_key_var = tk.StringVar(value="Q")
        flow_combo = ttk.Combobox(top, textvariable=flow_key_var, values=["Q", "QA", "QE"], width=16, state="readonly")
        flow_combo.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(top, text="P_atm (Pa):").grid(row=1, column=2, sticky="w", padx=6, pady=4)
        patm_var = tk.StringVar(value="101325.0")
        ttk.Entry(top, textvariable=patm_var, width=18).grid(row=1, column=3, sticky="w", padx=6, pady=4)

        ttk.Label(top, text="rho_ref:").grid(row=1, column=4, sticky="w", padx=6, pady=4)
        rho_var = tk.StringVar(value="1.2")
        ttk.Entry(top, textvariable=rho_var, width=10).grid(row=1, column=5, sticky="w", padx=6, pady=4)

        def _get_user_patm_rho() -> tuple[float, float]:
            """
            Read P_atm and rho_ref from the GUI.
            No silent defaults: invalid values raise and stop plotting/export.
            """
            try:
                P_atm = float(str(patm_var.get()).strip().replace(",", "."))
            except Exception:
                raise ValueError("Invalid P_atm (Pa). Please enter a numeric value (example: 101325).")

            try:
                rho_ref = float(str(rho_var.get()).strip().replace(",", "."))
            except Exception:
                raise ValueError("Invalid rho_ref. Please enter a numeric value (example: 1.2).")

            if rho_ref <= 0.0:
                raise ValueError("rho_ref must be > 0.")

            if P_atm <= 0.0:
                raise ValueError("P_atm must be > 0.")

            return P_atm, rho_ref


        # --- Matplotlib area in a dedicated frame (clean layout)
        plot_frame = ttk.Frame(win)
        plot_frame.pack(fill="both", expand=True, padx=10, pady=10)
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        dpi_screen = win.winfo_fpixels('1i')  # real screen DPI
        dpi = dpi_screen  # pick a dpi you like (100 is common)
        w_px = int(sw * 0.80)            # take 80% of screen width
        h_px = int(sh * 0.65)            # take 65% of screen height
        fig = mpl.figure.Figure(figsize=(w_px / dpi, h_px / dpi), dpi=dpi, facecolor="white")
        # fig = mpl.figure.Figure(figsize=(11.5, 7.5), facecolor="white")
        # fig.subplots_adjust(left=0.06, right=0.86, bottom=0.08, top=0.92)  # leave room for cbar

        canvas = FigureCanvasTkAgg(fig, master=plot_frame)
        canvas.get_tk_widget().pack(fill="both", expand=True)

        # --- Create ONE fixed colorbar axes (never recreated unless it got detached)
        # tighter colorbar position
        _CAX_POS = [0.57, 0.18, 0.025, 0.64]  # [left, bottom, width, height]
        _CAX_GAP = 0.000010                       # gap between main axes and cbar

        cax_ref = {"ax": fig.add_axes(_CAX_POS)}
        cax_ref["ax"].set_visible(False)

        cbar_ref = {"obj": None}
        ax_ref = {"ax": None, "kind": None}  # kind: "3d" or "2d"

        def _ensure_cax():
            ax = cax_ref.get("ax")
            if ax is None or ax.figure is None or ax.figure is not fig:
                ax = fig.add_axes(_CAX_POS)
                cax_ref["ax"] = ax
            ax.set_position(_CAX_POS)
            return ax

        def _remove_colorbar():
            cb = cbar_ref.get("obj")
            if cb is not None:
                try:
                    cb.remove()
                except Exception:
                    pass
            cbar_ref["obj"] = None

            ax = _ensure_cax()
            try:
                ax.cla()
            except Exception:
                # if cla still fails for any reason, recreate cax
                ax = fig.add_axes(_CAX_POS)
                cax_ref["ax"] = ax
            ax.set_visible(False)


        def _get_ax(kind: str):
            if ax_ref["ax"] is None or ax_ref["kind"] != kind:
                cax = _ensure_cax()

                for a in list(fig.axes):
                    if a is not cax:
                        try:
                            a.remove()
                        except Exception:
                            pass

                _remove_colorbar()

                ax = fig.add_subplot(111, projection="3d") if kind == "3d" else fig.add_subplot(111)
                ax_ref["ax"] = ax
                ax_ref["kind"] = kind

            fig.subplots_adjust(left=0.06, right=_CAX_POS[0] - _CAX_GAP, bottom=0.08, top=0.92)

            return ax_ref["ax"]



        def selected_case():
            ip = p_combo.current()
            it = t_combo.current()
            if ip < 0 or it < 0:
                return None, None
            p_val = Ps[ip]
            t_val = Ts[it]
            return p_val, t_val

        def get_field_array(p_val, t_val, field: str):
            # Geometry opening
            if field == "OPENING":
                return O_um, "Crack opening (µm)"

            arr0 = load_case_var(p_val, t_val, field)
            if arr0 is None:
                return None, None
            arr = arr0.astype(float)[order, :]


            # Unit conversions
            if field in ("P", "PV"):
                arr = 1e-5 * arr
                label = "Pressure (bar)" if field == "P" else "Steam Pressure (bar)"
            elif field == "TF":
                label = "Temperature (°C)"
            elif field == "U":
                label = "Velocity (m/s)"
            elif field == "RE":
                label = "Reynolds"
            elif field == "H":
                label = "Heat transfer coefficient (W/m2/K)"
            elif field == "F":
                label = "Heat flux density (W/m2)"
            else:
                label = field

            return arr, label


        # ============================================================
        # FIGURE STYLE: Times New Roman + Bold + White background
        # ============================================================

        def _apply_tnr_bold_global():
            # Make matplotlib default to Times New Roman + bold
            mpl.rcParams["font.family"] = "Times New Roman"
            mpl.rcParams["font.weight"] = "bold"
            mpl.rcParams["axes.labelweight"] = "bold"
            mpl.rcParams["axes.titleweight"] = "bold"
            mpl.rcParams["figure.facecolor"] = "white"
            mpl.rcParams["axes.facecolor"] = "white"
            mpl.rcParams["savefig.facecolor"] = "white"
            mpl.rcParams["savefig.edgecolor"] = "white"
            mpl.rcParams["mathtext.fontset"] = "custom"
            mpl.rcParams["mathtext.rm"] = "Times New Roman"
            mpl.rcParams["mathtext.it"] = "Times New Roman"
            mpl.rcParams["mathtext.bf"] = "Times New Roman"


            mpl.rcParams["xtick.color"] = "black"
            mpl.rcParams["ytick.color"] = "black"
            mpl.rcParams["axes.labelcolor"] = "black"
            mpl.rcParams["text.color"] = "black"

        def _style_axes_2d(ax, ticksize=14, labelsize=16, titlesize=18):
            ax.set_facecolor("white")
            ax.figure.set_facecolor("white")

            # labels + title
            ax.xaxis.label.set_fontname("Times New Roman")
            ax.yaxis.label.set_fontname("Times New Roman")
            ax.xaxis.label.set_fontweight("bold")
            ax.yaxis.label.set_fontweight("bold")

            ax.title.set_fontname("Times New Roman")
            ax.title.set_fontweight("bold")
            ax.title.set_fontsize(titlesize)

            # ticks (bold + TNR)
            ax.tick_params(axis="both", which="both", labelsize=ticksize, width=1.2)
            for lab in ax.get_xticklabels() + ax.get_yticklabels():
                lab.set_fontname("Times New Roman")
                lab.set_fontweight("bold")

            # spines
            for sp in ax.spines.values():
                sp.set_linewidth(1.2)

        def _style_axes_3d(ax, ticksize=12, labelsize=16, titlesize=18):
            # ---- Guard: only apply to real 3D axes
            if not hasattr(ax, "zaxis"):
                return

            ax.set_facecolor("white")
            ax.figure.set_facecolor("white")

            # Title
            ax.set_title(
                ax.get_title(),
                fontname="Times New Roman",
                fontweight="bold",
                fontsize=titlesize
            )

            # Axis labels
            ax.xaxis.label.set_fontname("Times New Roman")
            ax.yaxis.label.set_fontname("Times New Roman")
            ax.zaxis.label.set_fontname("Times New Roman")

            ax.xaxis.label.set_fontweight("bold")
            ax.yaxis.label.set_fontweight("bold")
            ax.zaxis.label.set_fontweight("bold")

            ax.xaxis.label.set_fontsize(labelsize)
            ax.yaxis.label.set_fontsize(labelsize)
            ax.zaxis.label.set_fontsize(labelsize)

            # Tick labels
            for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
                try:
                    for lab in axis.get_ticklabels():
                        lab.set_fontname("Times New Roman")
                        lab.set_fontweight("bold")
                except Exception:
                    pass

        def _style_colorbar(cb, ticksize=14, labelsize=18):
            if cb is None:
                return
            cb.ax.set_facecolor("white")

            # tick labels
            cb.ax.tick_params(labelsize=ticksize, width=1.2)
            for lab in cb.ax.get_yticklabels():
                lab.set_fontname("Times New Roman")
                lab.set_fontweight("bold")

            # label (already set elsewhere sometimes)
            cb.set_label(cb.ax.get_ylabel(), fontsize=labelsize, fontweight="bold", fontname="Times New Roman")

        # call once when opening the window
        _apply_tnr_bold_global()


        def _axes_clean_3d(a):
            a.set_facecolor("white")
            a.xaxis.pane.set_facecolor((1, 1, 1, 1))
            a.yaxis.pane.set_facecolor((1, 1, 1, 1))
            a.zaxis.pane.set_facecolor((1, 1, 1, 1))

            a.xaxis.line.set_color((1, 1, 1, 0))
            a.yaxis.line.set_color((1, 1, 1, 0))
            a.zaxis.line.set_color((1, 1, 1, 0))

        def draw_xyz_surface(field_arr, cbar_label, title_text):
            ax = _get_ax("3d")
            ax.clear()
            _remove_colorbar()
            _axes_clean_3d(ax)

            norm = mpl.colors.Normalize(vmin=float(np.nanmin(field_arr)), vmax=float(np.nanmax(field_arr)))
            cmap = mpl.colormaps[cmap_name]
            facecolors = cmap(norm(field_arr))

            ax.plot_surface(
                Xg_cm, Yg_cm, Zg_cm,
                facecolors=facecolors,
                rstride=1, cstride=1,
                linewidth=0,
                antialiased=True,
                shade=False
            )

            ax.set_zticks([])
            ax.set_title(title_text)
            ax.set_xlabel("X (cm)", labelpad=12, fontweight="bold")
            ax.set_ylabel("Y (cm)", labelpad=12, fontweight="bold")
            ax.set_xlim(x_min, x_max)
            ax.set_ylim(y_min, y_max)
            ax.set_zlim(z_min, z_max)
            ax.set_box_aspect((dx, dy, dz))
            ax.view_init(elev=30, azim=225)

            mappable = mpl.cm.ScalarMappable(norm=norm, cmap=cmap_name)
            mappable.set_array(field_arr)
            cax = _ensure_cax()
            cax.set_visible(True)
            cb = fig.colorbar(mappable, cax=cax)
            cb.set_label(cbar_label, fontsize=18, fontweight="bold", fontname="Times New Roman")
            cb.ax.tick_params(labelsize=14)

            _style_axes_3d(ax)
            _style_colorbar(cb)

            cbar_ref["obj"] = cb



        def draw_xy_colored_lines(field_arr, z_label, title_text):
            ax = _get_ax("3d")
            ax.clear()
            _remove_colorbar()
            _axes_clean_3d(ax)

            vmin = float(np.nanmin(field_arr))
            vmax = float(np.nanmax(field_arr))
            norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
            cmap = mpl.colormaps[cmap_name]

            for i in range(field_arr.shape[0]):
                pts = np.column_stack((Xg_cm[i, :], Yg_cm[i, :], field_arr[i, :]))
                if pts.shape[0] < 2:
                    continue
                segs = np.stack([pts[:-1], pts[1:]], axis=1)
                lc = Line3DCollection(segs, cmap=cmap, norm=norm, linewidth=1.2)
                lc.set_array(field_arr[i, :-1])
                ax.add_collection3d(lc)

            ax.set_title(title_text)
            ax.set_xlabel("X (cm)", labelpad=12, fontweight="bold")
            ax.set_ylabel("Y (cm)", labelpad=12, fontweight="bold")
            ax.set_zlabel(z_label, labelpad=14, fontweight="bold")

            ax.set_xlim(x_min, x_max)
            ax.set_ylim(y_min, y_max)
            ax.set_zlim(vmin, vmax)
            ax.set_box_aspect((dx, dy, dz))
            ax.view_init(elev=30, azim=225)

            mappable = mpl.cm.ScalarMappable(norm=norm, cmap=cmap_name)
            mappable.set_array(field_arr)
            cax = _ensure_cax()
            cax.set_visible(True)
            cb = fig.colorbar(mappable, cax=cax)
            cb.set_label(z_label, fontsize=18, fontweight="bold")
            cb.ax.tick_params(labelsize=14)
            _style_axes_3d(ax)
            _style_colorbar(cb)

            cbar_ref["obj"] = cb

        def draw_flow_vs_x(p_val, t_val):
            ax = _get_ax("2d")
            ax.clear()
            _remove_colorbar()

            if not (available.get((p_val, t_val), {}).get("Q", False) and
                    available.get((p_val, t_val), {}).get("QA", False) and
                    available.get((p_val, t_val), {}).get("QE", False)):
                ax.set_title("FLOW_VS_X: missing Q/QA/QE files for this (P,T)")
                return

            X_uniq = np.asarray(Xg[:, 0]).astype(float)

            try:
                _, rho_ref = _get_user_patm_rho()
            except Exception as e:
                messagebox.showerror("Input error", str(e))
                return

            conv_factor = 3600.0 / rho_ref  # Nm^3/h from kg/s (or your convention)
            Q_arr  = load_case_var(p_val, t_val, "Q")
            QA_arr = load_case_var(p_val, t_val, "QA")
            QE_arr = load_case_var(p_val, t_val, "QE")
            if Q_arr is None or QA_arr is None or QE_arr is None:
                ax.set_title("FLOW_VS_X: missing Q/QA/QE for this (P,T)")
                return

            Qm  = conv_factor * Q_arr[:,  -1].astype(float)
            QAm = conv_factor * QA_arr[:, -1].astype(float)
            QEm = conv_factor * QE_arr[:, -1].astype(float)



            order_x = np.argsort(X_uniq)
            Xcm = X_uniq[order_x] * 1e2
            Qm  = Qm[order_x]
            QAm = QAm[order_x]
            QEm = QEm[order_x]

            sum_Q  = float(np.nansum(Qm))
            sum_QA = float(np.nansum(QAm))
            sum_QE = float(np.nansum(QEm))
            ax.plot(Qm,  Xcm, color="black", linewidth=6, marker="o", markersize=15, label=f"Q   (Σ = {sum_Q:.3g})")
            ax.plot(QAm, Xcm, color="red",   linewidth=3, marker="s", markersize=6,  label=f"QA (Σ = {sum_QA:.3g})")
            ax.plot(QEm, Xcm, color="blue",  linewidth=3, marker="^", markersize=6,  label=f"QE (Σ = {sum_QE:.3g})")

            ax.set_xlabel("Flow (Nm$^3$/h)")
            ax.set_ylabel("X (cm)")
            ax.set_title(f"03 Flow distribution (P={p_val} Pa, T={t_val})")
            ax.grid(True, alpha=0.3)
            leg = ax.legend(frameon=True)
            for txt in leg.get_texts():
                txt.set_fontname("Times New Roman")
                txt.set_fontweight("bold")
            _style_axes_2d(ax)

        def draw_pt_total_flow(flow_key: str):
            ax = _get_ax("3d")
            
            ax.clear()
            _remove_colorbar()
            _axes_clean_3d(ax)

            try:
                P_atm, rho_ref = _get_user_patm_rho()
            except Exception as e:
                messagebox.showerror("Input error", str(e))
                return

            conv_factor = 3600.0 / rho_ref

            L = float(np.nanmax(Yi) - np.nanmin(Yi))
            if abs(L) < 1e-30:
                L = 1.0

            X_plot, Y_T, Z_sumQ = [], [], []
            for pp in Ps:
                for tt in Ts:
                    # LAZY LOAD (cached)
                    arr = load_case_var(pp, tt, flow_key)
                    if arr is None:
                        continue

                    profile = arr[:, -1] if (arr.ndim == 2 and arr.shape[1] >= 1) else arr
                    profile = conv_factor * profile.astype(float)
                    sum_Q = float(np.nansum(profile))

                    P1 = float(pp)
                    P2 = float(P_atm)
                    gradP2 = (P1**2 - P2**2) / L  # Pa^2/m

                    X_plot.append(gradP2 * 1e-10)  # bar^2/m
                    Y_T.append(float(tt))
                    Z_sumQ.append(sum_Q)

            X_plot = np.asarray(X_plot)
            Y_T = np.asarray(Y_T)
            Z_sumQ = np.asarray(Z_sumQ)

            ax.scatter(X_plot, Y_T, Z_sumQ, s=80, marker="o")

            # if you truly don't want interpolation, REMOVE trisurf completely
            # (keeping it here as optional)
            try:
                ax.plot_trisurf(X_plot, Y_T, Z_sumQ, linewidth=0.01, alpha=0.5)
            except Exception:
                pass

            ax.set_xlabel(r"$\nabla (P^2)\;(\mathrm{bar}^2/\mathrm{m}$)", labelpad=15)
            ax.set_ylabel("Temperature (°C)", labelpad=15)
            ax.set_zlabel("Q (Nm$^3$/h)", labelpad=15)
            ax.set_title(f"18 PT Total Flow ({flow_key})")
            _style_axes_3d(ax)
            ax.view_init(elev=30, azim=225)


        def refresh_plot(*_):
            if not Ps or not Ts:
                return
            p_val, t_val = selected_case()
            if p_val is None or t_val is None:
                return

            p_bar = float(p_val) * 1e-5
            field = field_var.get().strip()
            title = f"(P={p_bar:.6g} bar, T={t_val})"

            if field == "FLOW_VS_X":
                draw_flow_vs_x(p_val, t_val)
                canvas.draw_idle()
                return

            if field == "PT_TOTAL_FLOW":
                fk = flow_key_var.get().strip()
                if fk not in ("Q", "QA", "QE"):
                    fk = "Q"
                draw_pt_total_flow(fk)
                canvas.draw_idle()
                return

            arr, label = get_field_array(p_val, t_val, field)
            if arr is None:
                messagebox.showwarning("Missing data", f"No data for field {field} at P={p_val}, T={t_val}")
                log(f"[Post] Missing field {field} for P={p_val}, T={t_val}\n")
                return

            if plot_mode.get() == "XYZ_SURFACE":
                draw_xyz_surface(arr, label, title)
            else:
                draw_xy_colored_lines(arr, label, title)

            canvas.draw_idle()

        def export_current():
            if not Ps or not Ts:
                return
            p_val, t_val = selected_case()
            if p_val is None or t_val is None:
                return

            field = field_var.get().strip()
            fk = flow_key_var.get().strip()
            if fk not in ("Q", "QA", "QE"):
                fk = "Q"

            # Numbering mapping (two digits, starting at 01)
            # OPENING: 01/02, FLOW_VS_X: 03, fields: 04..17, PT surface: 18
            num_map = {
                "OPENING_XYZ": "01",
                "OPENING_XY": "02",
                "FLOW_VS_X": "03",
                "P_XYZ": "04",
                "P_XY": "05",
                "U_XYZ": "06",
                "U_XY": "07",
                "RE_XYZ": "08",
                "RE_XY": "09",
                "TF_XYZ": "10",
                "TF_XY": "11",
                "PV_XYZ": "12",
                "PV_XY": "13",
                "H_XYZ": "14",
                "H_XY": "15",
                "F_XYZ": "16",
                "F_XY": "17",
                "PT_TOTAL_FLOW": "18",
            }

            if field == "PT_TOTAL_FLOW":
                # Plot it (ensure current canvas shows it) then export
                draw_pt_total_flow(fk)
                out = folder / f"{num_map['PT_TOTAL_FLOW']}_PT_TotalFlow_{fk}.pdf"
                _save_like_screen(fig, out)
                messagebox.showinfo("Export", f"Wrote:\n{out}")
                return

            if field == "FLOW_VS_X":
                draw_flow_vs_x(p_val, t_val)
                out = folder / f"{num_map['FLOW_VS_X']}_Flow_vs_X_P{p_val}_T{t_val}_Q_QA_QE.pdf"
                _save_like_screen(fig, out)
                messagebox.showinfo("Export", f"Wrote:\n{out}")
                return

            # OPENING or regular fields
            if field == "OPENING":
                if plot_mode.get() == "XYZ_SURFACE":
                    out = folder / f"{num_map['OPENING_XYZ']}_XYZ_opening_{cmap_name}.pdf"
                else:
                    out = folder / f"{num_map['OPENING_XY']}_XY_opening_lines_{cmap_name}.pdf"
                refresh_plot()
                _save_like_screen(fig, out)
                messagebox.showinfo("Export", f"Wrote:\n{out}")
                return

            # regular fields
            key = f"{field}_{'XYZ' if plot_mode.get()=='XYZ_SURFACE' else 'XY'}"
            n = num_map.get(key, "XX")
            tag = field
            out = folder / f"{n}_{'XYZ' if plot_mode.get()=='XYZ_SURFACE' else 'XY'}_{tag}_P{p_val}_T{t_val}_{cmap_name}.pdf"
            refresh_plot()
            _save_like_screen(fig, out)
            messagebox.showinfo("Export", f"Wrote:\n{out}")
            log(f"[Post] Export current -> {out.name}\n")

        def add_fixed_cbar(fig, left=0.855, bottom=0.18, width=0.025, height=0.64, gap=0.010):
            cax = fig.add_axes([left, bottom, width, height])
            fig.subplots_adjust(left=0.06, right=left - gap, bottom=0.08, top=0.92)
            return cax

        def _save_like_screen(fig_obj, out_path: Path, dpi: int = 300):
            """
            Save with the same background as on-screen (white) and avoid gray PDF backgrounds.
            """
            # Ensure figure/axes patches are white
            try:
                fig_obj.set_facecolor("white")
            except Exception:
                pass

            for a in getattr(fig_obj, "axes", []):
                try:
                    a.set_facecolor("white")
                except Exception:
                    pass

            fig_obj.savefig(
                out_path,
                dpi=dpi,
                facecolor=fig_obj.get_facecolor(),  # important
                edgecolor=fig_obj.get_edgecolor(),  # important
                transparent=False,
                bbox_inches="tight",
                pad_inches=0.05,
            )


        def export_all_for_case(show_popup: bool = True):
            """
            Export using the SAME live figure + SAME draw_* functions as on-screen.
            This guarantees identical configuration between live view, Export current, and Export ALL.
            """
            if not Ps or not Ts:
                return

            p_val, t_val = selected_case()
            if p_val is None or t_val is None:
                return

            p_bar = float(p_val) * 1e-5
            log(f"[Post] Export ALL for selected (P={p_val}, T={t_val})\n")

            # --- save current UI state so we can restore it
            prev_field = field_var.get()
            prev_mode = plot_mode.get()
            prev_fk = flow_key_var.get()
            prev_p_idx = p_combo.current()
            prev_t_idx = t_combo.current()

            def _set_and_export(field: str, mode: str | None, out_name: str, fk: str | None = None):
                # Optional flow key selection
                if fk is not None:
                    flow_key_var.set(fk)

                # Set field and mode
                field_var.set(field)
                if mode is not None:
                    plot_mode.set(mode)

                win.update_idletasks()

                # Draw using the SAME pipeline as the screen
                refresh_plot()

                # Save the SAME live figure
                out_path = folder / out_name
                _save_like_screen(fig, out_path)
                log(f"[Post] Wrote {out_path.name}\n")

            def _case_has(var: str) -> bool:
                return bool(available.get((p_val, t_val), {}).get(var, False))

            try:
                # 01 Opening XYZ (screen-style)
                _set_and_export(
                    field="OPENING",
                    mode="XYZ_SURFACE",
                    out_name=f"01_XYZ_opening_{cmap_name}.pdf"
                )

                # 02 Opening XY colored lines (screen-style)
                _set_and_export(
                    field="OPENING",
                    mode="XY_LINES",
                    out_name=f"02_XY_opening_lines_{cmap_name}.pdf"
                )

                # 03 Flow vs X (only if Q/QA/QE exist)
                if all(_case_has(v) for v in ["Q", "QA", "QE"]):
                    _set_and_export(
                        field="FLOW_VS_X",
                        mode=None,  # mode not used here
                        out_name=f"03_Flow_vs_X_P{p_val}_T{t_val}_Q_QA_QE.pdf"
                    )
                else:
                    log("[Post] Skipped 03 (missing Q/QA/QE for this case)\n")

                # Helper: export a normal field in both modes
                def _export_field(var: str, n_xyz: str, n_xy: str, tag: str):
                    if not _case_has(var):
                        log(f"[Post] Skipped {var} (missing for this case)\n")
                        return
                    _set_and_export(
                        field=var,
                        mode="XYZ_SURFACE",
                        out_name=f"{n_xyz}_XYZ_{tag}_P{p_val}_T{t_val}_{cmap_name}.pdf"
                    )
                    _set_and_export(
                        field=var,
                        mode="XY_LINES",
                        out_name=f"{n_xy}_XY_{tag}_P{p_val}_T{t_val}_{cmap_name}.pdf"
                    )

                # 04..17 (match your numbering)
                _export_field("P",  "04", "05", "pressure")
                _export_field("U",  "06", "07", "velocity")
                _export_field("RE", "08", "09", "Reynolds")
                _export_field("TF", "10", "11", "Temperature")
                _export_field("PV", "12", "13", "Steam_Pressure")
                _export_field("H",  "14", "15", "H")
                _export_field("F",  "16", "17", "F")

                # 18 PT Total Flow (use currently selected flow key)
                fk = flow_key_var.get().strip()
                if fk not in ("Q", "QA", "QE"):
                    fk = "Q"
                _set_and_export(
                    field="PT_TOTAL_FLOW",
                    mode=None,  # mode not used here
                    out_name=f"18_PT_TotalFlow_{fk}.pdf",
                    fk=fk
                )

            finally:
                # Restore UI state
                try:
                    if prev_p_idx >= 0:
                        p_combo.current(prev_p_idx)
                    if prev_t_idx >= 0:
                        t_combo.current(prev_t_idx)
                except Exception:
                    pass

                field_var.set(prev_field)
                plot_mode.set(prev_mode)
                flow_key_var.set(prev_fk)
                win.update_idletasks()
                refresh_plot()

            if show_popup:
                messagebox.showinfo("Export", f"Exported all PDFs for P={p_bar:.6g} bar, T={t_val}.")
            log("[Post] Export ALL done for selected case.\n")

        def export_all_all_cases():
            log("[Post] Export ALL for ALL (P,T) started...\n")

            # validate user inputs once
            try:
                _get_user_patm_rho()
            except Exception as e:
                messagebox.showerror("Input error", str(e))
                return

            total = len(Ps) * len(Ts)
            if total <= 0:
                messagebox.showinfo("Export", "No (P,T) cases to export.")
                return

            # reset progress UI
            prog.configure(maximum=total)
            prog_var.set(0)
            prog_label_var.set(f"0 / {total}")
            win.update_idletasks()

            processed = 0
            step_idx = 0

            # optional: disable buttons during long export
            for child in btns.winfo_children():
                try:
                    if isinstance(child, ttk.Button):
                        child.configure(state="disabled")
                except Exception:
                    pass

            try:
                for pp in Ps:
                    for tt in Ts:
                        step_idx += 1
                        key = (pp, tt)

                        # update progress UI
                        prog_var.set(step_idx)
                        prog_label_var.set(f"{step_idx} / {total}   (P={pp}, T={tt})")
                        win.update_idletasks()

                        # skip empty cases quickly
                        if key not in available:
                            continue
                        if not any(available[key].get(v, False) for v in ["P","PV","TF","U","H","RE","Q","QA","QE","F"]):
                            continue

                        # set selection in combos (so the exported filenames keep same style)
                        try:
                            p_combo.current(Ps.index(pp))
                            t_combo.current(Ts.index(tt))
                        except Exception:
                            pass

                        # export silently
                        export_all_for_case(show_popup=False)
                        processed += 1

                        # periodic log
                        if step_idx == 1 or step_idx == total or (step_idx % max(total // 10, 1) == 0):
                            log(f"[Post] Export progress: {step_idx}/{total} (exported {processed})\n")

            finally:
                # re-enable buttons
                for child in btns.winfo_children():
                    try:
                        if isinstance(child, ttk.Button):
                            child.configure(state="normal")
                    except Exception:
                        pass

            log(f"[Post] Export ALL for ALL (P,T) finished. Cases exported: {processed}\n")
            prog_label_var.set(f"Done: exported {processed} / {total}")
            messagebox.showinfo("Export", f"Exported ALL cases (exported {processed} (P,T) cases).")


        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=10, pady=6)

        ttk.Button(btns, text="Refresh", command=refresh_plot).pack(side="left", padx=6)
        ttk.Button(btns, text="Export current", command=export_current).pack(side="left", padx=6)
        ttk.Button(btns, text="Export ALL (selected P,T)", command=lambda: export_all_for_case(show_popup=True)).pack(side="left", padx=6)
        ttk.Button(btns, text="Export ALL (all P,T)", command=export_all_all_cases).pack(side="left", padx=6)

        # --- Progress UI (right side)
        prog_frame = ttk.Frame(btns)
        prog_frame.pack(side="right", fill="x", expand=True, padx=10)

        prog_label_var = tk.StringVar(value="")
        prog_label = ttk.Label(prog_frame, textvariable=prog_label_var)
        prog_label.pack(side="top", anchor="e")

        prog_var = tk.IntVar(value=0)
        prog = ttk.Progressbar(prog_frame, orient="horizontal", mode="determinate", maximum=100, variable=prog_var)
        prog.pack(side="top", fill="x", expand=True)


        p_combo.bind("<<ComboboxSelected>>", refresh_plot)
        t_combo.bind("<<ComboboxSelected>>", refresh_plot)
        field_combo.bind("<<ComboboxSelected>>", refresh_plot)
        flow_combo.bind("<<ComboboxSelected>>", refresh_plot)

        refresh_plot()

    # ----------------------------
    # Main run 
    # ----------------------------
    # ============================================================
    # PATCH 1/2: _run with live log
    # ============================================================
    def _run(self):
        try:
            dgibi = Path(self.dgibi_var.get().strip())
            if not dgibi.exists():
                raise FileNotFoundError("DGIBI template not found.")

            workdir = ensure_dir(self.workdir_var.get().strip())
            castem_exe = resolve_castem_exe(self.castem_version_var.get())

            csv_x = Path(self.csv_x_var.get().strip())
            csv_y = Path(self.csv_y_var.get().strip())
            csv_zmax = Path(self.csv_zmax_var.get().strip())
            csv_zmin = Path(self.csv_zmin_var.get().strip())
            for f in [csv_x, csv_y, csv_zmax, csv_zmin]:
                if not f.exists():
                    raise FileNotFoundError(f"CSV not found:\n{f}")

            p = self._read_params()
            self._validate_params(p)

        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        self._log("\n===== RUN START =====\n")
        self._log(f"Workdir: {workdir}\n")

        names = self._expected_csv_names(p)
        dst_x = workdir / names["xrange"]
        dst_y = workdir / names["yrange"]
        dst_zmax = workdir / names["zfit_zmax"]
        dst_zmin = workdir / names["zfit_zmin"]
        safe_copy(csv_x, dst_x)
        safe_copy(csv_y, dst_y)
        safe_copy(csv_zmax, dst_zmax)
        safe_copy(csv_zmin, dst_zmin)

        template_text = dgibi.read_text(encoding="utf-8", errors="ignore")
        patched = patch_dgibi_main_program(template_text, p)

        out_dgibi = workdir / (
            f"{dgibi.stem}_ti{p.re_ti}_crpa{p.re_crpa}_smfa{p.re_smfa_int}_"
            f"numsp{p.re_numspa}_opmin{p.re_opmin_int}.dgibi"
        )
        out_dgibi.write_text(patched, encoding="utf-8")
        self._log(f"Generated DGIBI: {out_dgibi.name}\n")

        cmd = ["cmd.exe", "/c", str(castem_exe), str(out_dgibi)]

        def after_castem(rc: int):
            if rc != 0:
                messagebox.showerror("CASTEM error", f"CASTEM failed, return code {rc}")
                self._log("===== RUN END (FAILED) =====\n")
                return

            final_bdf = None

            if self.do_merge_var.get():
                combined = merge_bdfs(workdir, self._log)
                if combined is not None:
                    combined_named = workdir / (
                        f"combined_ti{p.re_ti}_crpa{p.re_crpa}_smfa{p.re_smfa_int}_"
                        f"numsp{p.re_numspa}_opmin{p.re_opmin_int}.bdf"
                    )
                    if combined_named.exists():
                        combined_named.unlink()
                    combined.replace(combined_named)
                    final_bdf = combined_named
                    self._log(f"Final combined: {combined_named.name}\n")
            else:
                vol = workdir / "castem_mesh_v.bdf"
                if vol.exists():
                    final_bdf = vol
                    self._log("Merge disabled. Using castem_mesh_v.bdf for visualization.\n")
                else:
                    self._log("Warning: castem_mesh_v.bdf not found.\n")

            if p.opti_visu == 1 and final_bdf and final_bdf.exists():
                try:
                    gmsh_exe = resolve_gmsh_exe()
                    self._log(f"Opening in Gmsh: {final_bdf.name}\n")
                    subprocess.Popen([str(gmsh_exe), str(final_bdf)], cwd=str(workdir))
                except Exception as e:
                    messagebox.showwarning("Gmsh", str(e))

            self._log("===== RUN END =====\n")

        self._log("Running CASTEM...\n")
        self._stream_process_to_log(cmd, workdir, on_done=after_castem)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
