"""Scientific workbench UI for the preserved Cast3M crack-meshing pipeline.

This is the single supported launcher for the enhanced workflow. It reuses the
baseline's execution, FISS, and BDF merge code without modifying immutable
baseline sources. Users can choose the original Cast3M reference workflow or
the vectorized, bulk-file Python hole workflow for the same inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import os
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk

import castem_pipeline_gui_t13 as baseline
from castem_pipeline_gui_python_holes import (
    PythonHoleInterpolationApp,
    archive_existing_mesh_outputs,
    existing_mesh_outputs,
    missing_mesh_outputs,
)
from python_hole_interpolation import (
    HoleGeometry,
    detect_hole_rings,
    hole_boundary_vertices,
    load_surface_csvs,
    normalize_hole_geometry,
    radial_layer_fractions,
)


ROOT = Path(__file__).resolve().parent
DOCUMENTED_INPUT = ROOT / "examples" / "input"
DOCUMENTED_CONFIG = ROOT / "examples" / "multiple-holes" / "parameters.json"
COMPARISON_IMAGE = ROOT / "docs" / "assets" / "mesh-comparison-r2-conformal.png"
SHAPE_GALLERY = (
    HoleGeometry("circle", -0.25, 0.25, radius=0.045),
    HoleGeometry("rectangle", 0.23, 0.25, width=0.10, height=0.06, rotation_degrees=15.0),
    HoleGeometry("triangle", -0.25, -0.23, side_length=0.10, rotation_degrees=-10.0),
    HoleGeometry("regular_polygon", 0.23, -0.23, radius=0.055, sides=6, rotation_degrees=30.0),
)


@dataclass
class HoleShapeRow:
    shape: tk.StringVar
    cx: tk.StringVar
    cy: tk.StringVar
    primary: tk.StringVar
    secondary: tk.StringVar
    rotation: tk.StringVar
    proxy_radius: tk.StringVar
    shape_widget: ttk.Combobox
    cx_entry: ttk.Entry
    cy_entry: ttk.Entry
    primary_label: ttk.Label
    primary_entry: ttk.Entry
    secondary_label: ttk.Label
    secondary_entry: ttk.Entry
    rotation_label: ttk.Label
    rotation_entry: ttk.Entry
    widgets: tuple[tk.Widget, ...]


class ScientificApp(PythonHoleInterpolationApp):
    """A task-oriented Tk workbench built on the established solver backend."""

    COLORS = {
        "navy": "#0f2742",
        "blue": "#1668a8",
        "teal": "#0f766e",
        "teal_dark": "#0b5b55",
        "amber": "#b45309",
        "surface": "#f4f7fb",
        "card": "#ffffff",
        "ink": "#10233f",
        "muted": "#5d6d82",
        "line": "#d8e1ec",
        "success": "#087e6b",
        "danger": "#b42318",
    }

    def __init__(self) -> None:
        super().__init__()
        self.title("Cast3M Crack Meshing Workbench")
        self.geometry("1440x900")
        self.minsize(1120, 720)
        # A scientific workbench should not open a separate viewer unexpectedly.
        self.opti_visu_var.set(False)
        self._set_status("Ready for input", "neutral")

    # ------------------------------------------------------------------
    # Theme and layout
    # ------------------------------------------------------------------

    def _configure_theme(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        c = self.COLORS
        self.configure(background=c["surface"])
        style.configure("Scientific.TFrame", background=c["surface"])
        style.configure("Card.TFrame", background=c["card"])
        style.configure("Header.TFrame", background=c["navy"])
        style.configure("Scientific.TLabel", background=c["surface"], foreground=c["ink"], font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=c["card"], foreground=c["ink"], font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=c["surface"], foreground=c["muted"], font=("Segoe UI", 9))
        style.configure("CardMuted.TLabel", background=c["card"], foreground=c["muted"], font=("Segoe UI", 9))
        style.configure("Hero.TLabel", background=c["navy"], foreground="#ffffff", font=("Segoe UI Semibold", 21))
        style.configure("HeroSub.TLabel", background=c["navy"], foreground="#d7e7f7", font=("Segoe UI", 10))
        style.configure("Status.TLabel", background=c["navy"], foreground="#ffffff", font=("Segoe UI Semibold", 10))
        style.configure("Section.TLabelframe", background=c["card"], bordercolor=c["line"], relief="solid")
        style.configure("Section.TLabelframe.Label", background=c["card"], foreground=c["navy"], font=("Segoe UI Semibold", 10))
        style.configure("Scientific.TEntry", fieldbackground="#ffffff", foreground=c["ink"], padding=6)
        style.configure("Scientific.TCombobox", fieldbackground="#ffffff", foreground=c["ink"], padding=5)
        style.configure("Primary.TButton", background=c["teal"], foreground="#ffffff", borderwidth=0, padding=(14, 8), font=("Segoe UI Semibold", 10))
        style.map("Primary.TButton", background=[("active", c["teal_dark"]), ("disabled", "#95bcb8")])
        style.configure("Accent.TButton", background=c["blue"], foreground="#ffffff", borderwidth=0, padding=(12, 7), font=("Segoe UI Semibold", 9))
        style.map("Accent.TButton", background=[("active", "#125587")])
        style.configure("Quiet.TButton", background=c["card"], foreground=c["blue"], bordercolor=c["line"], padding=(10, 6))
        style.map("Quiet.TButton", background=[("active", "#e8f1f8")])
        style.configure("Scientific.TNotebook", background=c["surface"], borderwidth=0)
        style.configure("Scientific.TNotebook.Tab", background="#e7edf5", foreground=c["muted"], padding=(17, 9), font=("Segoe UI Semibold", 10))
        style.map("Scientific.TNotebook.Tab", background=[("selected", c["card"]), ("active", "#dce8f3")], foreground=[("selected", c["navy"])])
        style.configure("Scientific.Horizontal.TProgressbar", troughcolor="#e5edf4", background=c["teal"], bordercolor="#e5edf4", lightcolor=c["teal"], darkcolor=c["teal"])

    def _build_ui(self, parent) -> None:  # called by baseline.App.__init__
        self._configure_theme()
        c = self.COLORS
        self._suspend_dirty = True
        self._active_operation: str | None = None
        self._process_started = False
        self._active_mesh_params = None
        self.status_var = tk.StringVar(value="Initializing")
        self.status_tone = "neutral"
        self.solver_mode_var = tk.StringVar(value="python")
        self.context_var = tk.StringVar(value="Active mode: bulk inflated holes")
        self.input_summary_var = tk.StringVar(value="Select the four structured CSV grids, then validate the configuration.")
        self.method_summary_var = tk.StringVar()
        self.run_summary_var = tk.StringVar(value="No run has been started in this session.")

        shell = ttk.Frame(parent, style="Scientific.TFrame")
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="Header.TFrame", padding=(24, 17))
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Crack Meshing Workbench", style="Hero.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Structured crack surfaces → Cast3M volume mesh → CFD-ready BDF",
            style="HeroSub.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.status_label = ttk.Label(header, textvariable=self.status_var, style="Status.TLabel", padding=(12, 6))
        self.status_label.grid(row=0, column=1, rowspan=2, sticky="e")

        toolbar = ttk.Frame(shell, style="Scientific.TFrame", padding=(20, 12, 20, 0))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Load documented example", style="Accent.TButton", command=self._load_documented_example).pack(side="left")
        ttk.Button(toolbar, text="Load all shape examples", style="Quiet.TButton", command=self._load_shape_gallery).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Validate inputs", style="Quiet.TButton", command=self._validate_inputs).pack(side="left", padx=(8, 0))
        ttk.Label(toolbar, textvariable=self.context_var, style="Muted.TLabel").pack(side="right")

        self.notebook = ttk.Notebook(shell, style="Scientific.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=20, pady=(10, 14))
        self.input_tab = ttk.Frame(self.notebook, style="Scientific.TFrame", padding=14)
        self.mesh_tab = ttk.Frame(self.notebook, style="Scientific.TFrame", padding=14)
        self.run_tab = ttk.Frame(self.notebook, style="Scientific.TFrame", padding=14)
        self.fiss_tab = ttk.Frame(self.notebook, style="Scientific.TFrame", padding=14)
        self.notebook.add(self.input_tab, text="1  Geometry & inputs")
        self.notebook.add(self.mesh_tab, text="2  Mesh & holes")
        self.notebook.add(self.run_tab, text="3  Run & results")
        self.notebook.add(self.fiss_tab, text="FISS flow")

        self._build_input_tab()
        self._build_mesh_tab()
        self._build_run_tab()
        self._build_fiss_tab()
        self._update_method_summary()
        self._install_change_tracking()
        self._suspend_dirty = False

    def _card(self, parent, title: str, *, padding: int = 14) -> ttk.LabelFrame:
        return ttk.LabelFrame(parent, text=title, style="Section.TLabelframe", padding=padding)

    def _field(self, parent, row: int, column: int, label: str, variable, *, width: int = 14, note: str | None = None):
        ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=column, sticky="w", padx=(0, 7), pady=5)
        entry = ttk.Entry(parent, textvariable=variable, width=width, style="Scientific.TEntry")
        entry.grid(row=row, column=column + 1, sticky="we", pady=5)
        if note:
            ttk.Label(parent, text=note, style="CardMuted.TLabel").grid(row=row + 1, column=column, columnspan=2, sticky="w")
        return entry

    def _path_row(self, parent, row: int, label: str, variable, browse_command) -> None:
        ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 9), pady=6)
        ttk.Entry(parent, textvariable=variable, style="Scientific.TEntry").grid(row=row, column=1, sticky="we", pady=6)
        ttk.Button(parent, text="Browse", style="Quiet.TButton", command=browse_command).grid(row=row, column=2, padx=(8, 0), pady=6)

    def _build_input_tab(self) -> None:
        tab = self.input_tab
        tab.columnconfigure(0, weight=4)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(1, weight=1)

        setup = self._card(tab, "Run context")
        setup.grid(row=0, column=0, sticky="ew", padx=(0, 10), pady=(0, 10))
        setup.columnconfigure(1, weight=1)
        self._path_row(setup, 0, "Cast3M DGIBI template", self.dgibi_var, self._browse_dgibi)
        self._path_row(setup, 1, "Working directory", self.workdir_var, self._browse_workdir)
        self._field(setup, 2, 0, "Cast3M launcher version", self.castem_version_var, width=11)
        metadata = ttk.LabelFrame(setup, text="Dataset naming metadata", style="Section.TLabelframe", padding=10)
        metadata.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        for column in (1, 3, 5):
            metadata.columnconfigure(column, weight=1)
        self._field(metadata, 0, 0, "re_ti", self.re_ti_var, width=9)
        self._field(metadata, 0, 2, "re_crpa", self.re_crpa_var, width=9)
        self._field(metadata, 0, 4, "re_smfa", self.re_smfa_var, width=9)
        self._field(metadata, 1, 0, "re_numspa", self.re_numspa_var, width=9)
        self._field(metadata, 1, 2, "re_opmin", self.re_opmin_var, width=9)

        grids = self._card(tab, "Structured surface grids")
        grids.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        grids.columnconfigure(1, weight=1)
        self._path_row(grids, 0, "X coordinate grid — xrange", self.csv_x_var, self._browse_csv_x)
        self._path_row(grids, 1, "Y coordinate grid — yrange", self.csv_y_var, self._browse_csv_y)
        self._path_row(grids, 2, "Upper surface — zfit_zmax", self.csv_zmax_var, self._browse_csv_zmax)
        self._path_row(grids, 3, "Lower surface — zfit_zmin", self.csv_zmin_var, self._browse_csv_zmin)
        ttk.Label(
            grids,
            text="All files must be equally sized, headerless comma-delimited numeric matrices.",
            style="CardMuted.TLabel",
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(11, 0))

        quality = self._card(tab, "Input quality")
        quality.grid(row=0, column=1, rowspan=2, sticky="nsew")
        quality.columnconfigure(0, weight=1)
        ttk.Label(quality, text="Pre-flight summary", style="Card.TLabel", font=("Segoe UI Semibold", 11)).grid(row=0, column=0, sticky="w")
        ttk.Separator(quality, orient="horizontal").grid(row=1, column=0, sticky="ew", pady=10)
        ttk.Label(quality, textvariable=self.input_summary_var, style="CardMuted.TLabel", wraplength=300, justify="left").grid(row=2, column=0, sticky="nw")
        ttk.Button(quality, text="Validate inputs", style="Accent.TButton", command=self._validate_inputs).grid(row=3, column=0, sticky="ew", pady=(18, 8))
        ttk.Button(quality, text="Preview XY geometry", style="Quiet.TButton", command=self._preview_geometry).grid(row=4, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(
            quality,
            text="Pre-flight reads inputs and resolves the selected Cast3M launcher; it does not run Cast3M or change files.",
            style="CardMuted.TLabel",
            wraplength=300,
            justify="left",
        ).grid(row=5, column=0, sticky="sw")

    def _build_mesh_tab(self) -> None:
        tab = self.mesh_tab
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(1, weight=1)

        mesh = self._card(tab, "Volume discretization")
        mesh.grid(row=0, column=0, sticky="ew", padx=(0, 9), pady=(0, 10))
        for column in (1, 3):
            mesh.columnconfigure(column, weight=1)
        self._field(mesh, 0, 0, "Elements in X", self.nelem_x_var)
        self._field(mesh, 0, 2, "Elements in Y", self.nelem_y_var)
        self._field(mesh, 1, 0, "Elements through Z", self.nelem_z_var)
        self._field(mesh, 1, 2, "Z inflation factor", self.re_fact_z_var)
        self._field(mesh, 2, 0, "Geometric tolerance", self.re_tol_var, width=15)

        exports = self._card(tab, "Outputs and solver mode")
        exports.grid(row=0, column=1, sticky="ew", pady=(0, 10))
        ttk.Checkbutton(exports, text="Merge BDF boundary and volume cards", variable=self.do_merge_var).grid(row=0, column=0, sticky="w", pady=3)
        ttk.Checkbutton(exports, text="Open completed mesh in Gmsh", variable=self.opti_visu_var).grid(row=1, column=0, sticky="w", pady=3)
        ttk.Checkbutton(exports, text="Export MED volume mesh", variable=self.opti_med_var).grid(row=2, column=0, sticky="w", pady=3)
        ttk.Checkbutton(exports, text="Export STL surfaces", variable=self.opti_stl_var).grid(row=3, column=0, sticky="w", pady=3)
        ttk.Separator(exports, orient="horizontal").grid(row=4, column=0, sticky="ew", pady=10)
        ttk.Radiobutton(exports, text="Original T13 workflow — reference", value="baseline", variable=self.solver_mode_var, command=self._on_solver_mode_change).grid(row=5, column=0, sticky="w", pady=3)
        ttk.Radiobutton(exports, text="Bulk Python hole mesh — fast + inflated", value="python", variable=self.solver_mode_var, command=self._on_solver_mode_change).grid(row=6, column=0, sticky="w", pady=3)

        holes = self._card(tab, "Hole shapes / internal boundaries")
        holes.grid(row=1, column=0, columnspan=2, sticky="nsew")
        holes.columnconfigure(7, weight=1)
        ttk.Checkbutton(holes, text="Enable holes", variable=self.holes_enabled_var, command=self._on_holes_toggle).grid(row=0, column=0, sticky="w", pady=(0, 7))
        ttk.Button(holes, text="Add hole", style="Quiet.TButton", command=self._add_hole_row).grid(row=0, column=1, padx=(8, 0), pady=(0, 7))
        ttk.Button(holes, text="Remove last", style="Quiet.TButton", command=self._remove_hole_row).grid(row=0, column=2, padx=(8, 0), pady=(0, 7))
        ttk.Label(holes, textvariable=self.method_summary_var, style="CardMuted.TLabel", wraplength=620, justify="left").grid(row=0, column=3, columnspan=5, sticky="e", padx=(20, 0), pady=(0, 7))
        ttk.Separator(holes, orient="horizontal").grid(row=1, column=0, columnspan=8, sticky="ew", pady=(0, 10))
        self._field(holes, 2, 0, "Radial fill cells", self.num_el_fill_var)
        self._field(holes, 2, 2, "Outer / inner cell ratio", self.re_fact_hole_var)
        ttk.Label(
            holes,
            text="Inflation definition: Δr outer / Δr hole = ratio. Hole coordinates use the CSV coordinate units.",
            style="CardMuted.TLabel",
        ).grid(row=3, column=0, columnspan=7, sticky="w", pady=(4, 0))
        ttk.Label(holes, text="Hole", style="CardMuted.TLabel").grid(row=4, column=0, sticky="w", pady=(10, 2))
        ttk.Label(holes, text="Shape", style="CardMuted.TLabel").grid(row=4, column=1, sticky="w", pady=(10, 2))
        ttk.Label(holes, text="Center X", style="CardMuted.TLabel").grid(row=4, column=2, sticky="w", pady=(10, 2))
        ttk.Label(holes, text="Center Y", style="CardMuted.TLabel").grid(row=4, column=3, sticky="w", pady=(10, 2))
        ttk.Label(holes, text="Shape parameters", style="CardMuted.TLabel").grid(row=4, column=4, columnspan=3, sticky="w", pady=(10, 2))
        profile = ttk.Frame(holes, style="Card.TFrame")
        profile.grid(row=2, column=7, rowspan=8, sticky="ne", padx=(22, 6), pady=(0, 4))
        ttk.Label(profile, text="Normalized inflation profile", style="Card.TLabel", font=("Segoe UI Semibold", 10)).pack(anchor="w")
        self.inflation_canvas = tk.Canvas(
            profile,
            width=330,
            height=176,
            background=self.COLORS["card"],
            highlightthickness=0,
        )
        self.inflation_canvas.pack(anchor="w", pady=(3, 0))
        self.num_el_fill_var.trace_add("write", lambda *_args: self.after_idle(self._draw_inflation_preview))
        self.re_fact_hole_var.trace_add("write", lambda *_args: self.after_idle(self._draw_inflation_preview))
        self.holes_container = holes
        self.holes_rows_start = 5
        self.hole_shape_rows: list[HoleShapeRow] = []
        self.hole_row_widgets = []
        self._toggle_holes()
        self._draw_inflation_preview()

    def _draw_inflation_preview(self) -> None:
        """Render the configured radial grading as a normalized ring schematic."""

        if not hasattr(self, "inflation_canvas"):
            return
        canvas = self.inflation_canvas
        canvas.delete("all")
        try:
            count = int(self.num_el_fill_var.get())
            factor = float(self.re_fact_hole_var.get())
            fractions = radial_layer_fractions(count, factor)
        except (TypeError, ValueError):
            canvas.create_text(
                165,
                78,
                text="Enter radial cells ≥ 1\nand a ratio > 0",
                fill=self.COLORS["danger"],
                font=("Segoe UI", 10),
                justify="center",
            )
            return

        center_x, center_y = 112, 80
        outer_radius, hole_radius = 68.0, 27.0
        ring_radii = outer_radius - fractions * (outer_radius - hole_radius)
        canvas.create_oval(
            center_x - outer_radius,
            center_y - outer_radius,
            center_x + outer_radius,
            center_y + outer_radius,
            fill="#eaf4f3",
            outline="",
        )
        for index, radius in enumerate(ring_radii):
            width = 2 if index in (0, len(ring_radii) - 1) else 1
            color = self.COLORS["teal_dark"] if index == len(ring_radii) - 1 else self.COLORS["teal"]
            canvas.create_oval(
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
                outline=color,
                width=width,
            )
        canvas.create_oval(
            center_x - hole_radius,
            center_y - hole_radius,
            center_x + hole_radius,
            center_y + hole_radius,
            fill="#ffffff",
            outline=self.COLORS["amber"],
            width=2,
        )
        canvas.create_text(center_x, center_y, text="HOLE", fill=self.COLORS["amber"], font=("Segoe UI Semibold", 8))
        canvas.create_line(196, 36, 218, 36, fill=self.COLORS["teal"], width=2)
        canvas.create_text(224, 36, text="radial cell edges", anchor="w", fill=self.COLORS["muted"], font=("Segoe UI", 9))
        canvas.create_line(196, 62, 218, 62, fill=self.COLORS["amber"], width=2)
        canvas.create_text(224, 62, text="hole wall", anchor="w", fill=self.COLORS["muted"], font=("Segoe UI", 9))
        canvas.create_text(
            165,
            163,
            text=f"{count} cells  •  Δr outer / Δr hole = {factor:g}",
            fill=self.COLORS["ink"],
            font=("Segoe UI Semibold", 9),
        )

    def _build_run_tab(self) -> None:
        tab = self.run_tab
        tab.columnconfigure(0, weight=2)
        tab.columnconfigure(1, weight=3)
        tab.rowconfigure(1, weight=1)

        action = self._card(tab, "Execution")
        action.grid(row=0, column=0, sticky="new", padx=(0, 10), pady=(0, 10))
        action.columnconfigure(0, weight=1)
        ttk.Label(action, text="Review the pre-flight summary before running Cast3M.", style="CardMuted.TLabel", wraplength=320, justify="left").grid(row=0, column=0, sticky="w")
        ttk.Button(action, text="Validate configuration", style="Accent.TButton", command=self._validate_inputs).grid(row=1, column=0, sticky="ew", pady=(15, 8))
        self.mesh_run_button = ttk.Button(action, text="Run mesh converter", style="Primary.TButton", command=self._run_from_workbench)
        self.mesh_run_button.grid(row=2, column=0, sticky="ew", pady=3)
        ttk.Button(action, text="Open working directory", style="Quiet.TButton", command=self._open_workdir).grid(row=3, column=0, sticky="ew", pady=(8, 3))
        self.gmsh_open_button = ttk.Button(action, text="Open generated mesh in Gmsh", style="Quiet.TButton", command=self._open_mesh_in_gmsh)
        self.gmsh_open_button.grid(row=4, column=0, sticky="ew", pady=3)
        ttk.Button(action, text="Open mesh comparison", style="Quiet.TButton", command=self._open_mesh_comparison).grid(row=5, column=0, sticky="ew", pady=3)
        ttk.Label(action, textvariable=self.run_summary_var, style="CardMuted.TLabel", wraplength=320, justify="left").grid(row=6, column=0, sticky="w", pady=(16, 0))

        progress = self._card(tab, "Run state")
        progress.grid(row=0, column=1, sticky="new", pady=(0, 10))
        progress.columnconfigure(0, weight=1)
        self.progress_var = tk.IntVar(value=0)
        self.progress = ttk.Progressbar(progress, style="Scientific.Horizontal.TProgressbar", mode="determinate", variable=self.progress_var, maximum=100)
        self.progress.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(progress, textvariable=self.status_var, style="Card.TLabel", font=("Segoe UI Semibold", 11)).grid(row=1, column=0, sticky="w")
        ttk.Label(progress, text="Solver output is streamed below. The GUI remains responsive while Cast3M runs.", style="CardMuted.TLabel", wraplength=620, justify="left").grid(row=2, column=0, sticky="w", pady=(5, 0))

        log_card = self._card(tab, "Live solver log")
        log_card.grid(row=1, column=0, columnspan=2, sticky="nsew")
        log_card.rowconfigure(0, weight=1)
        log_card.columnconfigure(0, weight=1)
        self.log = tk.Text(
            log_card,
            wrap="word",
            height=22,
            background="#0b1726",
            foreground="#d7e7f7",
            insertbackground="#ffffff",
            relief="flat",
            font=("Cascadia Mono", 9),
            padx=10,
            pady=10,
        )
        scroll = ttk.Scrollbar(log_card, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        ttk.Button(log_card, text="Clear log", style="Quiet.TButton", command=self._clear_log).grid(row=1, column=0, sticky="e", pady=(8, 0))
        self._log("Scientific workbench ready. Load inputs or use the documented example.\n")

    def _build_fiss_tab(self) -> None:
        tab = self.fiss_tab
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)

        context = self._card(tab, "FISS flow calculation")
        context.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        context.columnconfigure(1, weight=1)
        self._path_row(context, 0, "FISS DGIBI template", self.fiss_dgibi_var, self._browse_fiss_dgibi)
        ttk.Label(context, text="FISS uses the same four surface CSV grids but is a separate Cast3M calculation.", style="CardMuted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        model = self._card(tab, "Flow model")
        model.grid(row=1, column=0, sticky="new", padx=(0, 9))
        model.columnconfigure(0, weight=1)
        model_names = (
            "POISEU_BLASIUS", "POISEU_COLEBROOK", "POISEU_GELAIN_2008", "POISEU_GELAIN_2012",
            "POISEU_RIZKALLA", "FROTTEMENT1", "FROTTEMENT2", "FROTTEMENT3", "FROTTEMENT4",
        )
        combo = ttk.Combobox(model, textvariable=self.fiss_model_var, values=model_names, state="readonly", style="Scientific.TCombobox")
        combo.grid(row=0, column=0, sticky="ew", pady=(0, 9))
        combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_fiss_model_inputs())
        self.frm_fiss_dyn = ttk.LabelFrame(model, text="Model-specific parameters", style="Section.TLabelframe", padding=10)
        self.frm_fiss_dyn.grid(row=1, column=0, sticky="ew")

        boundary = self._card(tab, "Gas and boundary conditions")
        boundary.grid(row=1, column=1, sticky="new")
        for column in (1, 3):
            boundary.columnconfigure(column, weight=1)
        ttk.Label(boundary, text="Gas", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(boundary, text="Perfect (PARF)", value="PARF", variable=self.fiss_gas_var).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(boundary, text="Real (REEL)", value="REEL", variable=self.fiss_gas_var).grid(row=0, column=2, sticky="w")
        ttk.Label(boundary, text="Condensation", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Radiobutton(boundary, text="MASS", value="MASS", variable=self.fiss_cond_var).grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Radiobutton(boundary, text="FILM", value="FILM", variable=self.fiss_cond_var).grid(row=1, column=2, sticky="w", pady=(8, 0))
        self._field(boundary, 2, 0, "Downstream P (Pa)", self.fiss_p_aval_var)
        self._field(boundary, 2, 2, "Wall temperature (°C)", self.fiss_temp_wall_var)
        self._field(boundary, 3, 0, "Steam pressure (Pa)", self.fiss_psteam_var)
        self._field(boundary, 3, 2, "Line subdivisions", self.fiss_num_elem_y_var)
        ttk.Separator(boundary, orient="horizontal").grid(row=4, column=0, columnspan=4, sticky="ew", pady=10)
        ttk.Label(boundary, text="Pressure", style="Card.TLabel").grid(row=5, column=0, sticky="w")
        ttk.Radiobutton(boundary, text="Single", value="single", variable=self.fiss_p_mode_var, command=self._refresh_fiss_bc_inputs).grid(row=5, column=1, sticky="w")
        ttk.Radiobutton(boundary, text="Range", value="range", variable=self.fiss_p_mode_var, command=self._refresh_fiss_bc_inputs).grid(row=5, column=2, sticky="w")
        p_in = self._field(boundary, 6, 0, "P in (Pa)", self.fiss_p_in_var)
        p_ini = self._field(boundary, 7, 0, "P start (Pa)", self.fiss_p_ini_var)
        p_fin = self._field(boundary, 7, 2, "P end (Pa)", self.fiss_p_fin_var)
        p_step = self._field(boundary, 8, 0, "P step (Pa)", self.fiss_p_step_var)
        ttk.Label(boundary, text="Temperature", style="Card.TLabel").grid(row=9, column=0, sticky="w", pady=(10, 0))
        ttk.Radiobutton(boundary, text="Single", value="single", variable=self.fiss_t_mode_var, command=self._refresh_fiss_bc_inputs).grid(row=9, column=1, sticky="w", pady=(10, 0))
        ttk.Radiobutton(boundary, text="Range", value="range", variable=self.fiss_t_mode_var, command=self._refresh_fiss_bc_inputs).grid(row=9, column=2, sticky="w", pady=(10, 0))
        t_in = self._field(boundary, 10, 0, "T in (°C)", self.fiss_t_in_var)
        t_ini = self._field(boundary, 11, 0, "T start (°C)", self.fiss_t_ini_var)
        t_fin = self._field(boundary, 11, 2, "T end (°C)", self.fiss_t_fin_var)
        t_step = self._field(boundary, 12, 0, "T step (°C)", self.fiss_t_step_var)
        self._p_entries = {"P_in": p_in, "P_ini": p_ini, "P_fin": p_fin, "P_step": p_step}
        self._t_entries = {"T_in": t_in, "T_ini": t_ini, "T_fin": t_fin, "T_step": t_step}
        buttons = ttk.Frame(tab, style="Scientific.TFrame")
        buttons.grid(row=2, column=0, columnspan=2, sticky="w", pady=(14, 0))
        self.fiss_run_button = ttk.Button(buttons, text="Run FISS calculation", style="Primary.TButton", command=self._run_fiss_from_workbench)
        self.fiss_run_button.pack(side="left")
        ttk.Button(buttons, text="Post-process results", style="Quiet.TButton", command=self._postprocess_picker).pack(side="left", padx=(8, 0))
        self._refresh_fiss_model_inputs()
        self._refresh_fiss_bc_inputs()

    # ------------------------------------------------------------------
    # User actions and status
    # ------------------------------------------------------------------

    def _install_change_tracking(self) -> None:
        variables = (
            self.dgibi_var,
            self.workdir_var,
            self.castem_version_var,
            self.csv_x_var,
            self.csv_y_var,
            self.csv_zmax_var,
            self.csv_zmin_var,
            self.re_ti_var,
            self.re_crpa_var,
            self.re_smfa_var,
            self.re_numspa_var,
            self.re_opmin_var,
            self.nelem_x_var,
            self.nelem_y_var,
            self.nelem_z_var,
            self.re_tol_var,
            self.re_fact_z_var,
            self.num_el_fill_var,
            self.re_fact_hole_var,
            self.opti_visu_var,
            self.opti_med_var,
            self.opti_stl_var,
            self.holes_enabled_var,
            self.do_merge_var,
            self.solver_mode_var,
            self.fiss_dgibi_var,
            self.fiss_model_var,
            self.fiss_rugo_var,
            self.fiss_rec_var,
            self.fiss_fk_var,
            self.fiss_fa_var,
            self.fiss_fb_var,
            self.fiss_fc_var,
            self.fiss_fd_var,
            self.fiss_fk_k_var,
            self.fiss_gas_var,
            self.fiss_cond_var,
            self.fiss_temp_wall_var,
            self.fiss_p_aval_var,
            self.fiss_psteam_var,
            self.fiss_p_mode_var,
            self.fiss_p_in_var,
            self.fiss_p_ini_var,
            self.fiss_p_fin_var,
            self.fiss_p_step_var,
            self.fiss_t_mode_var,
            self.fiss_t_in_var,
            self.fiss_t_ini_var,
            self.fiss_t_fin_var,
            self.fiss_t_step_var,
            self.fiss_num_elem_y_var,
        )
        for variable in variables:
            variable.trace_add("write", self._mark_dirty)

    def _mark_dirty(self, *_args) -> None:
        if self._suspend_dirty or self._active_operation is not None:
            return
        self._set_status("Modified — validation required", "neutral")

    def _add_hole_row(self) -> None:
        row_index = self.holes_rows_start + len(self.hole_shape_rows)
        shape = tk.StringVar(value="Circle")
        cx = tk.StringVar(value="0.0")
        cy = tk.StringVar(value="0.0")
        primary = tk.StringVar(value="0.07")
        secondary = tk.StringVar(value="0.07")
        rotation = tk.StringVar(value="0.0")
        proxy_radius = tk.StringVar(value="0.07")

        number = ttk.Label(self.holes_container, text=f"H{len(self.hole_shape_rows) + 1}")
        shape_widget = ttk.Combobox(
            self.holes_container,
            textvariable=shape,
            values=("Circle", "Rectangle", "Equilateral triangle", "Regular polygon"),
            state="readonly",
            width=17,
            style="Scientific.TCombobox",
        )
        cx_entry = ttk.Entry(self.holes_container, textvariable=cx, width=10, style="Scientific.TEntry")
        cy_entry = ttk.Entry(self.holes_container, textvariable=cy, width=10, style="Scientific.TEntry")

        primary_frame = ttk.Frame(self.holes_container, style="Card.TFrame")
        primary_label = ttk.Label(primary_frame, text="Radius", style="CardMuted.TLabel")
        primary_entry = ttk.Entry(primary_frame, textvariable=primary, width=11, style="Scientific.TEntry")
        primary_label.pack(anchor="w")
        primary_entry.pack(anchor="w")

        secondary_frame = ttk.Frame(self.holes_container, style="Card.TFrame")
        secondary_label = ttk.Label(secondary_frame, text="—", style="CardMuted.TLabel")
        secondary_entry = ttk.Entry(secondary_frame, textvariable=secondary, width=10, style="Scientific.TEntry")
        secondary_label.pack(anchor="w")
        secondary_entry.pack(anchor="w")

        rotation_frame = ttk.Frame(self.holes_container, style="Card.TFrame")
        rotation_label = ttk.Label(rotation_frame, text="Rotation (°)", style="CardMuted.TLabel")
        rotation_entry = ttk.Entry(rotation_frame, textvariable=rotation, width=10, style="Scientific.TEntry")
        rotation_label.pack(anchor="w")
        rotation_entry.pack(anchor="w")

        number.grid(row=row_index, column=0, sticky="w", padx=(7, 4), pady=5)
        shape_widget.grid(row=row_index, column=1, sticky="w", padx=4, pady=5)
        cx_entry.grid(row=row_index, column=2, sticky="w", padx=4, pady=5)
        cy_entry.grid(row=row_index, column=3, sticky="w", padx=4, pady=5)
        primary_frame.grid(row=row_index, column=4, sticky="w", padx=4, pady=3)
        secondary_frame.grid(row=row_index, column=5, sticky="w", padx=4, pady=3)
        rotation_frame.grid(row=row_index, column=6, sticky="w", padx=4, pady=3)

        row = HoleShapeRow(
            shape=shape,
            cx=cx,
            cy=cy,
            primary=primary,
            secondary=secondary,
            rotation=rotation,
            proxy_radius=proxy_radius,
            shape_widget=shape_widget,
            cx_entry=cx_entry,
            cy_entry=cy_entry,
            primary_label=primary_label,
            primary_entry=primary_entry,
            secondary_label=secondary_label,
            secondary_entry=secondary_entry,
            rotation_label=rotation_label,
            rotation_entry=rotation_entry,
            widgets=(
                number,
                shape_widget,
                cx_entry,
                cy_entry,
                primary_frame,
                secondary_frame,
                rotation_frame,
            ),
        )
        self.hole_shape_rows.append(row)
        # The baseline parameter patcher still receives conservative circular
        # selectors; the bulk Python mesh contains the actual selected shape.
        self.hole_rows.append((cx, cy, proxy_radius))
        for variable in (shape, cx, cy, primary, secondary, rotation):
            variable.trace_add("write", self._mark_dirty)
            variable.trace_add("write", lambda *_args, current=row: self._sync_hole_proxy(current))
        shape.trace_add("write", lambda *_args, current=row: self._refresh_hole_shape_row(current))
        self._refresh_hole_shape_row(row)
        self._mark_dirty()

    def _remove_hole_row(self) -> None:
        if not self.hole_shape_rows:
            return
        row = self.hole_shape_rows.pop()
        self.hole_rows.pop()
        for widget in row.widgets:
            widget.destroy()
        self._mark_dirty()

    def _hole_geometry_from_row(self, row: HoleShapeRow, index: int) -> HoleGeometry:
        shape = self._shape_key(row.shape.get())
        cx = baseline.parse_float(row.cx.get())
        cy = baseline.parse_float(row.cy.get())
        primary = baseline.parse_float(row.primary.get())
        rotation = baseline.parse_float(row.rotation.get())
        if shape == "circle":
            geometry = HoleGeometry(shape, cx, cy, radius=primary)
        elif shape == "rectangle":
            geometry = HoleGeometry(
                shape,
                cx,
                cy,
                width=primary,
                height=baseline.parse_float(row.secondary.get()),
                rotation_degrees=rotation,
            )
        elif shape == "triangle":
            geometry = HoleGeometry(
                shape,
                cx,
                cy,
                side_length=primary,
                rotation_degrees=rotation,
            )
        elif shape == "regular_polygon":
            geometry = HoleGeometry(
                shape,
                cx,
                cy,
                radius=primary,
                sides=int(row.secondary.get().strip()),
                rotation_degrees=rotation,
            )
        else:
            raise ValueError(f"Hole {index}: unsupported shape '{shape}'.")
        return normalize_hole_geometry(geometry, index)

    @staticmethod
    def _shape_key(value: str) -> str:
        key = value.strip().lower().replace("-", "_").replace(" ", "_")
        return "triangle" if key == "equilateral_triangle" else key

    def _sync_hole_proxy(self, row: HoleShapeRow) -> None:
        try:
            index = self.hole_shape_rows.index(row) + 1
            radius = self._hole_geometry_from_row(row, index).selection_radius
            row.proxy_radius.set(f"{radius:.12g}")
        except (TypeError, ValueError):
            row.proxy_radius.set("0")

    def _refresh_hole_shape_row(self, row: HoleShapeRow) -> None:
        shape = self._shape_key(row.shape.get())
        labels = {
            "circle": ("Radius", "—", False, False),
            "rectangle": ("Width", "Height", True, True),
            "triangle": ("Side length", "—", False, True),
            "regular_polygon": ("Circumradius", "Sides", True, True),
        }
        primary_label, secondary_label, uses_secondary, uses_rotation = labels.get(
            shape, ("Size", "—", False, False)
        )
        row.primary_label.configure(text=primary_label)
        row.secondary_label.configure(text=secondary_label)
        enabled = self.holes_enabled_var.get()
        row.shape_widget.configure(state="readonly" if enabled else "disabled")
        row.cx_entry.configure(state="normal" if enabled else "disabled")
        row.cy_entry.configure(state="normal" if enabled else "disabled")
        row.primary_entry.configure(state="normal" if enabled else "disabled")
        row.secondary_entry.configure(
            state="normal" if enabled and uses_secondary else "disabled"
        )
        row.rotation_entry.configure(
            state="normal" if enabled and uses_rotation else "disabled"
        )
        self._sync_hole_proxy(row)

    def _read_params(self) -> baseline.CastemMainParams:
        params = super()._read_params()
        geometries: list[HoleGeometry] = []
        if params.holes_enabled:
            geometries = [
                self._hole_geometry_from_row(row, index)
                for index, row in enumerate(self.hole_shape_rows, start=1)
            ]
            params.holes = [
                baseline.Hole(hole.cx, hole.cy, hole.selection_radius)
                for hole in geometries
            ]
        params.hole_shapes = geometries
        return params

    def _set_hole_row_geometry(self, row: HoleShapeRow, geometry: HoleGeometry) -> None:
        geometry = normalize_hole_geometry(geometry)
        display_names = {
            "circle": "Circle",
            "rectangle": "Rectangle",
            "triangle": "Equilateral triangle",
            "regular_polygon": "Regular polygon",
        }
        row.shape.set(display_names[geometry.shape])
        row.cx.set(f"{geometry.cx:.12g}")
        row.cy.set(f"{geometry.cy:.12g}")
        row.rotation.set(f"{geometry.rotation_degrees:.12g}")
        if geometry.shape in {"circle", "regular_polygon"}:
            row.primary.set(f"{float(geometry.radius):.12g}")
        elif geometry.shape == "rectangle":
            row.primary.set(f"{float(geometry.width):.12g}")
            row.secondary.set(f"{float(geometry.height):.12g}")
        else:
            row.primary.set(f"{float(geometry.side_length):.12g}")
        if geometry.shape == "regular_polygon":
            row.secondary.set(str(geometry.sides))
        self._refresh_hole_shape_row(row)

    def _load_documented_example(self) -> None:
        try:
            config = json.loads(DOCUMENTED_CONFIG.read_text(encoding="utf-8"))
            inputs = config["inputs"]
            params = config["parameters"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            messagebox.showerror("Documented example", f"Could not load {DOCUMENTED_CONFIG}:\n{exc}")
            return

        def repository_path(value: str) -> str:
            return str((ROOT / value).resolve())

        self._suspend_dirty = True
        try:
            self.dgibi_var.set(repository_path(config["template"]))
            self.fiss_dgibi_var.set(str((ROOT / "source_codes" / "fuite_fissure.dgibi").resolve()))
            self.workdir_var.set(str((ROOT / "_runtime" / "scientific-run").resolve()))
            self.castem_version_var.set(str(config["castem_version"]))
            self.csv_x_var.set(repository_path(inputs["xrange"]))
            self.csv_y_var.set(repository_path(inputs["yrange"]))
            self.csv_zmax_var.set(repository_path(inputs["zfit_zmax"]))
            self.csv_zmin_var.set(repository_path(inputs["zfit_zmin"]))

            variable_map = {
                "re_ti": self.re_ti_var,
                "re_crpa": self.re_crpa_var,
                "re_smfa": self.re_smfa_var,
                "re_numspa": self.re_numspa_var,
                "re_opmin": self.re_opmin_var,
                "nelem_x": self.nelem_x_var,
                "nelem_y": self.nelem_y_var,
                "nelem_z": self.nelem_z_var,
                "re_tol": self.re_tol_var,
                "re_fact_z": self.re_fact_z_var,
                "num_el_fill": self.num_el_fill_var,
                "re_fact_hole": self.re_fact_hole_var,
            }
            for name, variable in variable_map.items():
                variable.set(str(params[name]))
            self.opti_med_var.set(bool(params["opti_med"]))
            self.opti_stl_var.set(bool(params["opti_stl"]))
            self.opti_visu_var.set(bool(params["opti_visu"]))
            self.do_merge_var.set(bool(params["merge_bdfs"]))
            while self.hole_shape_rows:
                self._remove_hole_row()
            self.holes_enabled_var.set(bool(params["holes_enabled"]))
            for hole in params["holes"]:
                self._add_hole_row()
                self._set_hole_row_geometry(
                    self.hole_shape_rows[-1],
                    HoleGeometry(
                        shape=hole.get("shape", "circle"),
                        cx=float(hole["cx"]),
                        cy=float(hole["cy"]),
                        radius=float(hole["r"]),
                    ),
                )
            self.solver_mode_var.set("python")
            self._toggle_holes()
            self._update_method_summary()
        finally:
            self._suspend_dirty = False
        self._validate_inputs(operation="mesh")

    def _load_shape_gallery(self) -> None:
        """Load one real, separated example of every supported hole shape."""

        self._load_documented_example()
        self._suspend_dirty = True
        try:
            self.workdir_var.set(str((ROOT / "_runtime" / "shape-gallery-run").resolve()))
            while self.hole_shape_rows:
                self._remove_hole_row()
            self.holes_enabled_var.set(True)
            for geometry in SHAPE_GALLERY:
                self._add_hole_row()
                self._set_hole_row_geometry(self.hole_shape_rows[-1], geometry)
            self.solver_mode_var.set("python")
            self._toggle_holes()
            self._update_method_summary()
            self.notebook.select(self.mesh_tab)
        finally:
            self._suspend_dirty = False
        self._validate_inputs(operation="mesh")

    def _on_holes_toggle(self) -> None:
        self._toggle_holes()
        self._update_method_summary()
        self._mark_dirty()

    def _toggle_holes(self) -> None:
        if not hasattr(self, "hole_shape_rows"):
            return
        for row in self.hole_shape_rows:
            self._refresh_hole_shape_row(row)

    def _on_solver_mode_change(self) -> None:
        self._update_method_summary()
        self._mark_dirty()

    def _update_method_summary(self) -> None:
        if not self.holes_enabled_var.get():
            self.method_summary_var.set("No holes: both modes use the preserved baseline mesh path.")
        elif self.solver_mode_var.get() == "python":
            self.method_summary_var.set("Bulk mode supports circles, rectangles, equilateral triangles, and regular polygons with conformal inflated CQUAD4 fills.")
        else:
            self.method_summary_var.set("Reference mode retains the original circle-only Cast3M interpolation and displacement workflow.")
        mode = "bulk inflated holes" if self.solver_mode_var.get() == "python" else "T13 reference"
        self.context_var.set(f"Active mode: {mode}")

    def _preflight_workdir(self) -> Path:
        raw = self.workdir_var.get().strip()
        if not raw:
            raise ValueError("Select a dedicated working directory.")
        workdir = Path(raw).expanduser().resolve()
        if workdir == ROOT:
            raise ValueError("The repository root cannot be used as the working directory; choose a dedicated run folder.")
        if workdir.exists() and not workdir.is_dir():
            raise NotADirectoryError(f"Working path is not a directory: {workdir}")
        writable_parent = workdir
        while not writable_parent.exists() and writable_parent != writable_parent.parent:
            writable_parent = writable_parent.parent
        if not writable_parent.is_dir() or not os.access(writable_parent, os.W_OK):
            raise PermissionError(f"Working directory parent is not writable: {writable_parent}")
        return workdir

    def _validate_inputs(self, operation: str = "mesh") -> bool:
        if operation not in {"mesh", "fiss"}:
            raise ValueError(f"Unknown validation operation: {operation}")
        try:
            template_raw = (
                self.dgibi_var.get().strip()
                if operation == "mesh"
                else self.fiss_dgibi_var.get().strip()
            )
            if not template_raw:
                raise ValueError("Select the DGIBI template for this operation.")
            template = Path(template_raw).expanduser()
            if not template.is_file():
                raise FileNotFoundError(f"Missing DGIBI template: {template}")
            workdir = self._preflight_workdir()
            castem_exe = baseline.resolve_castem_exe(self.castem_version_var.get())
            csv_x = Path(self.csv_x_var.get().strip())
            csv_y = Path(self.csv_y_var.get().strip())
            csv_zmax = Path(self.csv_zmax_var.get().strip())
            csv_zmin = Path(self.csv_zmin_var.get().strip())
            for source in (csv_x, csv_y, csv_zmax, csv_zmin):
                if not source.is_file():
                    raise FileNotFoundError(f"Missing CSV: {source}")
            x, y, zmin, zmax = load_surface_csvs(csv_x, csv_y, csv_zmin, csv_zmax)
            if (zmax < zmin).any():
                raise ValueError("zfit_zmax is below zfit_zmin at one or more grid points.")
            params = self._read_params()
            if operation == "mesh":
                self._validate_params(params)
            else:
                baseline.App._validate_params(self, params)
                if any(hole.shape != "circle" for hole in params.hole_shapes):
                    raise ValueError("The preserved FISS workflow currently supports circular holes only.")
                fiss = self._read_fiss_setup()
            details = [
                f"Grid: {x.shape[1]} × {x.shape[0]} points",
                f"X range: {x.min():.5g} to {x.max():.5g}",
                f"Y range: {y.min():.5g} to {y.max():.5g}",
                f"Opening: {(zmax - zmin).min():.3g} to {(zmax - zmin).max():.3g}",
                f"Cast3M launcher: {castem_exe.name}",
            ]
            if operation == "mesh" and params.holes_enabled:
                if not params.holes:
                    raise ValueError("Enable holes only after adding at least one shape.")
                if self.solver_mode_var.get() == "python":
                    rings = detect_hole_rings(
                        x,
                        y,
                        params.hole_shapes,
                        tolerance=params.re_tol,
                        nelem_x=params.nelem_x,
                        nelem_y=params.nelem_y,
                    )
                    details.append(
                        "Conformal edges (hole wall = square interface): "
                        + ", ".join(
                            f"{ring.geometry.shape} {len(ring.xy)}={len(ring.outer_xy)}"
                            for ring in rings
                        )
                    )
                else:
                    if any(hole.shape != "circle" for hole in params.hole_shapes):
                        raise ValueError(
                            "Rectangle, triangle, and regular-polygon holes require the Bulk Python mode."
                        )
                    details.append(f"Reference holes: {len(params.holes)}")
            elif operation == "mesh":
                details.append("No holes enabled")
            if operation == "mesh":
                details.append("Solver mode: " + ("Bulk Python inflated holes" if self.solver_mode_var.get() == "python" else "Original T13 baseline"))
                stale_count = len(existing_mesh_outputs(workdir)) if workdir.is_dir() else 0
                if stale_count:
                    details.append(f"Prior mesh artifacts: {stale_count} (archived automatically before run)")
            else:
                details.append(f"FISS model: {fiss.model}")
        except Exception as exc:
            self.input_summary_var.set("Validation issue:\n" + str(exc))
            self._set_status("Configuration needs attention", "error")
            return False

        self.input_summary_var.set("\n".join(details))
        self._set_status("Mesh pre-flight passed" if operation == "mesh" else "FISS pre-flight passed", "success")
        return True

    def _preview_geometry(self) -> None:
        """Open a real XY-grid preview from the selected source CSVs."""

        try:
            csv_x = Path(self.csv_x_var.get().strip())
            csv_y = Path(self.csv_y_var.get().strip())
            csv_zmax = Path(self.csv_zmax_var.get().strip())
            csv_zmin = Path(self.csv_zmin_var.get().strip())
            x, y, _zmin, _zmax = load_surface_csvs(csv_x, csv_y, csv_zmin, csv_zmax)
            params = self._read_params()
            self._validate_params(params)
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
            from matplotlib.figure import Figure
            from matplotlib.patches import Polygon
        except Exception as exc:
            messagebox.showerror("XY preview", str(exc))
            return

        window = tk.Toplevel(self)
        window.title("XY source-grid preview")
        window.geometry("900x720")
        figure = Figure(figsize=(8.6, 6.5), dpi=100, facecolor="#ffffff")
        axes = figure.add_subplot(111)
        step = max(1, max(x.shape) // 55)
        axes.plot(x[::step, :].T, y[::step, :].T, color="#6d8195", linewidth=0.35, alpha=0.72)
        axes.plot(x[:, ::step], y[:, ::step], color="#6d8195", linewidth=0.35, alpha=0.72)
        for number, hole in enumerate(
            params.hole_shapes if params.holes_enabled else (), start=1
        ):
            axes.add_patch(
                Polygon(
                    hole_boundary_vertices(hole),
                    closed=True,
                    fill=False,
                    linewidth=2.0,
                    edgecolor="#d97706",
                )
            )
            axes.annotate(
                f"H{number}\n{hole.shape}",
                (hole.cx, hole.cy),
                color="#9a4d05",
                ha="center",
                va="center",
                fontsize=8,
                weight="bold",
            )
        axes.set_title("Structured XY source grid and configured hole shapes", color="#10233f", pad=13, weight="bold")
        axes.set_xlabel("X coordinate")
        axes.set_ylabel("Y coordinate")
        axes.set_aspect("equal", adjustable="box")
        axes.grid(False)
        figure.tight_layout()
        canvas = FigureCanvasTkAgg(figure, master=window)
        canvas.draw()
        toolbar = NavigationToolbar2Tk(canvas, window, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side="bottom", fill="x")
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def _run_from_workbench(self) -> None:
        if self._active_operation is not None:
            messagebox.showwarning("Solver busy", "Wait for the active Cast3M operation to finish.")
            return
        if not self._validate_inputs(operation="mesh"):
            messagebox.showerror("Validation", "Correct the configuration issues before launching Cast3M.")
            return
        self._active_mesh_params = self._read_params()
        self._active_merge_requested = bool(self.do_merge_var.get())
        self._begin_operation("mesh")
        self._set_status("Preparing Cast3M run", "running")
        self.run_summary_var.set("The solver is being prepared. Follow detailed output in the live log.")
        try:
            self._run()
        except Exception as exc:
            self._log(f"Mesh preparation failed: {exc}\n")
            messagebox.showerror("Mesh preparation", str(exc))
        if not self._process_started and self._active_operation == "mesh":
            self._finish_operation(False, "Mesh preparation failed", "No Cast3M process was started. Review the validation message and log.")

    def _run_fiss_from_workbench(self) -> None:
        if self._active_operation is not None:
            messagebox.showwarning("Solver busy", "Wait for the active Cast3M operation to finish.")
            return
        if not self._validate_inputs(operation="fiss"):
            messagebox.showerror("Validation", "Correct the FISS configuration before launching Cast3M.")
            return
        self._begin_operation("fiss")
        self._set_status("Preparing FISS calculation", "running")
        try:
            self._run_fiss()
        except Exception as exc:
            self._log(f"FISS preparation failed: {exc}\n")
            messagebox.showerror("FISS preparation", str(exc))
        if not self._process_started and self._active_operation == "fiss":
            self._finish_operation(False, "FISS preparation failed", "No Cast3M process was started. Review the validation message and log.")

    def _begin_operation(self, operation: str) -> None:
        self._active_operation = operation
        self._process_started = False
        self._set_run_controls(busy=True)
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress_var.set(8)
        self.update_idletasks()

    def _set_run_controls(self, *, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        if hasattr(self, "mesh_run_button"):
            self.mesh_run_button.configure(state=state)
        if hasattr(self, "fiss_run_button"):
            self.fiss_run_button.configure(state=state)
        if hasattr(self, "gmsh_open_button"):
            self.gmsh_open_button.configure(state=state)

    def _finish_operation(self, successful: bool, status: str, summary: str) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress_var.set(100 if successful else 0)
        self._active_operation = None
        self._process_started = False
        self._set_run_controls(busy=False)
        self._set_status(status, "success" if successful else "error")
        self.run_summary_var.set(summary)

    def _run(self) -> None:
        if self.solver_mode_var.get() == "baseline":
            workdir = baseline.ensure_dir(self.workdir_var.get().strip())
            archive_existing_mesh_outputs(workdir, self._log)
            return baseline.App._run(self)
        else:
            return super()._run()

    def _stream_process_to_log(self, cmd, cwd: Path, on_done=None):
        operation = self._active_operation or "mesh"
        self.progress.configure(mode="indeterminate")
        self.progress.start(10)
        self._set_status("Cast3M mesh run in progress" if operation == "mesh" else "Cast3M FISS run in progress", "running")

        def completed(return_code: int) -> None:
            callback_error = None
            try:
                if on_done is not None:
                    on_done(return_code)
            except Exception as exc:
                callback_error = exc
                self._log(f"Post-run processing failed: {exc}\n")

            if return_code != 0:
                self._finish_operation(False, "Cast3M failed", f"Cast3M returned {return_code}. Inspect the live log for details.")
                return
            if callback_error is not None:
                self._finish_operation(False, "Post-run processing failed", str(callback_error))
                messagebox.showerror("Post-run processing", str(callback_error))
                return
            if operation == "mesh":
                params = self._active_mesh_params
                missing = missing_mesh_outputs(Path(cwd), params)
                if missing:
                    self._finish_operation(
                        False,
                        "Mesh outputs incomplete",
                        "Cast3M returned 0, but fresh expected files are missing: " + ", ".join(missing),
                    )
                    return
                combined = None
                if self._active_merge_requested:
                    combined = Path(cwd) / (
                        f"combined_ti{params.re_ti}_crpa{params.re_crpa}_smfa{params.re_smfa_int}_"
                        f"numsp{params.re_numspa}_opmin{params.re_opmin_int}.bdf"
                    )
                    if not combined.is_file():
                        self._finish_operation(False, "BDF merge incomplete", "Fresh Cast3M meshes exist, but the requested combined BDF was not created.")
                        return
                result = combined if combined is not None else Path(cwd) / "castem_mesh_v.bdf"
                self._finish_operation(True, "Mesh run verified", f"Fresh expected outputs verified. Primary result: {result.name}")
            else:
                self._finish_operation(True, "FISS run completed", f"Cast3M returned 0 for FISS. Review results under {Path(cwd).name}.")

        try:
            process = super()._stream_process_to_log(cmd, cwd, on_done=completed)
        except Exception as exc:
            self._log(f"Could not start Cast3M: {exc}\n")
            self._finish_operation(False, "Cast3M could not start", str(exc))
            messagebox.showerror("Cast3M launch", str(exc))
            return None
        self._process_started = process is not None
        return process

    def _set_status(self, message: str, tone: str) -> None:
        self.status_tone = tone
        self.status_var.set(message)
        if not hasattr(self, "status_label"):
            return
        colors = {
            "success": "#baf0df",
            "error": "#ffd2cf",
            "running": "#d7eaff",
            "neutral": "#ffffff",
        }
        self.status_label.configure(foreground=colors.get(tone, "#ffffff"))

    def _open_mesh_comparison(self) -> None:
        if not COMPARISON_IMAGE.is_file():
            messagebox.showinfo(
                "Mesh comparison",
                "No comparison image is available yet. Run scripts\\render_hole_mesh_comparison.py after completing both mesh runs.",
            )
            return
        try:
            os.startfile(str(COMPARISON_IMAGE))
        except OSError as exc:
            messagebox.showerror("Mesh comparison", str(exc))

    def _open_mesh_in_gmsh(self) -> None:
        """Open the preferred existing run artifact without launching Cast3M."""

        try:
            raw_workdir = self.workdir_var.get().strip()
            if not raw_workdir:
                raise ValueError("Select a working directory first.")
            workdir = Path(raw_workdir).expanduser().resolve()
            if not workdir.is_dir():
                raise FileNotFoundError(f"Working directory does not exist: {workdir}")

            candidates: list[Path] = []
            try:
                params = self._read_params()
                candidates.append(
                    workdir
                    / (
                        f"combined_ti{params.re_ti}_crpa{params.re_crpa}_smfa{params.re_smfa_int}_"
                        f"numsp{params.re_numspa}_opmin{params.re_opmin_int}.bdf"
                    )
                )
            except (TypeError, ValueError):
                pass
            candidates.extend(
                sorted(workdir.glob("combined*.bdf"), key=lambda path: path.stat().st_mtime, reverse=True)
            )
            candidates.append(workdir / "castem_mesh_v.bdf")
            mesh = next((path for path in candidates if path.is_file()), None)
            if mesh is None:
                raise FileNotFoundError("No combined BDF or castem_mesh_v.bdf exists in the selected working directory.")

            gmsh_exe = baseline.resolve_gmsh_exe()
            subprocess.Popen([str(gmsh_exe), str(mesh)], cwd=str(workdir))
        except Exception as exc:
            messagebox.showerror("Open mesh in Gmsh", str(exc))
            return

        self._log(f"Opened in Gmsh: {mesh.name}\n")
        self.run_summary_var.set(f"Opened {mesh.name} in Gmsh.")


def main() -> None:
    app = ScientificApp()
    app.mainloop()


if __name__ == "__main__":
    main()
