"""Embedded, non-blocking Tk workspace for advanced crack characterization."""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from crack_characterization import (
    AnalysisResult,
    CharacterizationConfig,
    SyntheticConfig,
    characterize_surface,
)
from surface_generation import SurfaceSource, build_surface_grid


class _Tooltip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event=None) -> None:
        if self.window is not None:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(
            f"+{self.widget.winfo_rootx() + 16}+{self.widget.winfo_rooty() + 24}"
        )
        ttk.Label(
            self.window,
            text=self.text,
            padding=7,
            justify="left",
            wraplength=390,
        ).pack()

    def _hide(self, _event=None) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None


class CharacterizationPanel(ttk.Frame):
    """Embedded characterization workspace that does not create another window."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        surface_source: Callable[[], SurfaceSource],
        output_directory_provider: Callable[[], Path],
        on_complete: Callable[[AnalysisResult], None] | None = None,
        continue_to_mesh: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, style="Scientific.TFrame")
        root = self.winfo_toplevel()
        self.colors = getattr(
            root,
            "COLORS",
            {
                "surface": "#f4f7fb",
                "card": "#ffffff",
                "ink": "#10233f",
                "muted": "#5d6d82",
                "line": "#d8e1ec",
            },
        )
        self.surface_source = surface_source
        self.output_directory_provider = output_directory_provider
        self.on_complete = on_complete
        self.continue_to_mesh = continue_to_mesh
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.messages: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.last_result: AnalysisResult | None = None
        self._build_variables()
        self._build_interface()
        self.refresh_output_directory()
        self.after(100, self._poll_worker)

    def _build_variables(self) -> None:
        self.seed = tk.StringVar(value="20260723")
        self.output_directory = tk.StringVar()
        self.synthetic_enabled = tk.BooleanVar(value=False)
        self.synthetic_points_x = tk.StringVar(value="64")
        self.synthetic_points_y = tk.StringVar(value="64")
        self.synthetic_size_x = tk.StringVar(value="1.0")
        self.synthetic_size_y = tk.StringVar(value="1.0")
        self.synthetic_mean_aperture = tk.StringVar(value="2e-4")
        self.synthetic_aperture_std = tk.StringVar(value="4e-5")
        self.synthetic_mid_rms = tk.StringVar(value="2e-5")
        self.synthetic_hurst_x = tk.StringVar(value="0.8")
        self.synthetic_hurst_y = tk.StringVar(value="0.8")
        self.synthetic_correlation_x = tk.StringVar(value="")
        self.synthetic_correlation_y = tk.StringVar(value="")
        self.synthetic_minimum = tk.StringVar(value="0")
        self.synthetic_maximum = tk.StringVar(value="")
        self.synthetic_contact = tk.StringVar(value="0")
        self.synthetic_slope_x = tk.StringVar(value="0")
        self.synthetic_slope_y = tk.StringVar(value="0")
        self.synthetic_positive = tk.BooleanVar(value=True)
        self.synthetic_realizations = tk.StringVar(value="1")
        self.synthetic_preset_note = tk.StringVar(
            value="Choose a preset or edit the synthetic targets."
        )
        self.status = tk.StringVar(
            value="Ready. Automatic X/Y characterization requires no analysis inputs."
        )
        self.progress = tk.DoubleVar(value=0.0)
        self.result_text: tk.Text

    def _row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.Variable,
        tooltip: str,
        *,
        values: tuple[str, ...] | None = None,
    ) -> None:
        label_widget = ttk.Label(parent, text=label, style="Card.TLabel")
        label_widget.grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        _Tooltip(label_widget, tooltip)
        if values is None:
            widget: tk.Widget = ttk.Entry(
                parent,
                textvariable=variable,
                style="Scientific.TEntry",
            )
        else:
            widget = ttk.Combobox(
                parent,
                textvariable=variable,
                values=values,
                state="readonly",
                style="Scientific.TCombobox",
            )
        widget.grid(row=row, column=1, sticky="ew", pady=5)
        _Tooltip(widget, tooltip)

    def _build_interface(self) -> None:
        shell = ttk.Frame(self, style="Scientific.TFrame")
        shell.pack(fill="both", expand=True)
        intro = ttk.Frame(shell, style="Scientific.TFrame")
        intro.pack(fill="x", pady=(0, 10))
        ttk.Label(
            intro,
            text="Advanced Crack Characterization",
            style="Scientific.TLabel",
            font=("Segoe UI Semibold", 16),
        ).pack(anchor="w")
        ttk.Label(
            intro,
            text=(
                "Uses the same reconstructed SurfaceGrid that is passed to Cast3M. "
                "Hydraulic values are cubic-law geometry proxies, not CFD solutions."
            ),
            style="Muted.TLabel",
            wraplength=900,
        ).pack(anchor="w", pady=(3, 0))
        body = ttk.Frame(shell, style="Scientific.TFrame")
        body.pack(fill="both", expand=True)
        notebook = ttk.Notebook(
            body,
            style="Scientific.TNotebook",
            height=430,
        )
        self.notebook = notebook
        notebook.pack(fill="x", expand=False)
        analysis = ttk.Frame(notebook, style="Card.TFrame", padding=14)
        synthesis = ttk.Frame(notebook, style="Card.TFrame", padding=14)
        results = ttk.Frame(notebook, style="Card.TFrame", padding=14)
        notebook.add(analysis, text="Automatic analysis")
        notebook.add(synthesis, text="Synthetic surface")
        notebook.add(results, text="Results & export")
        for tab in (analysis, synthesis, results):
            tab.columnconfigure(1, weight=1)

        automatic = ttk.LabelFrame(
            analysis,
            text="Always calculated — no parameters required",
            style="Section.TLabelframe",
            padding=12,
        )
        automatic.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        defaults = ttk.LabelFrame(
            analysis,
            text="Automatic numerical policy",
            style="Section.TLabelframe",
            padding=12,
        )
        defaults.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        analysis.columnconfigure(0, weight=1)
        analysis.columnconfigure(1, weight=1)

        automatic_items = (
            "✓ Global-Z and preferred local-normal aperture fields",
            "✓ Full classical, robust, percentile, area, and cubic statistics",
            "✓ X and Y path-equivalent cubic-law aperture",
            "✓ X and Y geometrical tortuosity for both walls and mid-surface",
            "✓ X and Y Hurst estimates: structure function and profile PSD",
            "✓ Roughness, slopes, orientation, area, volume, contact, and connectivity",
            "✓ Autocorrelation, bottlenecks, gradients, and conductance proxies",
            "✓ Additive 2D wavelet surfaces by scale and orientation",
        )
        for row, text in enumerate(automatic_items):
            ttk.Label(
                automatic,
                text=text,
                style="Card.TLabel",
                wraplength=540,
                justify="left",
            ).grid(row=row, column=0, sticky="w", pady=5)

        policy_items = (
            ("Coordinates", "Used exactly as reconstructed; reported in metres."),
            ("Directions", "Both global X and global Y; no Z choice is needed."),
            ("Local normals", "Mid-surface finite differences; no smoothing."),
            ("Closed opening", "b ≤ 1×10⁻¹² m is closed for cubic resistance."),
            ("Invalid values", "Reported explicitly; negative openings are rejected."),
            ("Hurst range", "Resolution-aware automatic range, ≤ 25% of profile."),
            ("Uncertainty", "100 deterministic bootstrap resamples and fit warnings."),
            ("Wavelets", "Automatic db2 decomposition, ≤ 5 levels, verified sum."),
        )
        for row, (name, value) in enumerate(policy_items):
            ttk.Label(
                defaults,
                text=name,
                style="Card.TLabel",
                font=("Segoe UI Semibold", 9),
            ).grid(row=row, column=0, sticky="nw", padx=(0, 9), pady=5)
            ttk.Label(
                defaults,
                text=value,
                style="CardMuted.TLabel",
                wraplength=360,
                justify="left",
            ).grid(row=row, column=1, sticky="nw", pady=5)

        ttk.Checkbutton(
            synthesis,
            text="Generate and verify a statistically representative synthetic surface",
            variable=self.synthetic_enabled,
            style="Card.TCheckbutton",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        presets = ttk.Frame(synthesis, style="Card.TFrame")
        presets.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Label(
            presets,
            text="Documented presets:",
            style="Card.TLabel",
        ).pack(side="left")
        for label, key in (
            ("Planar opening", "planar"),
            ("Anisotropic rough", "rough"),
            ("Bounded contact ensemble", "contact"),
        ):
            ttk.Button(
                presets,
                text=label,
                style="Quiet.TButton",
                command=lambda preset=key: self._apply_synthetic_preset(preset),
            ).pack(side="left", padx=(7, 0))
        ttk.Label(
            presets,
            textvariable=self.synthetic_preset_note,
            style="CardMuted.TLabel",
        ).pack(side="right")
        grid_rows = (
            ("Grid points X", self.synthetic_points_x),
            ("Grid points Y", self.synthetic_points_y),
            ("Size X", self.synthetic_size_x),
            ("Size Y", self.synthetic_size_y),
            ("Random seed", self.seed),
            ("Number of realizations", self.synthetic_realizations),
        )
        aperture_rows = (
            ("Mean aperture", self.synthetic_mean_aperture),
            ("Aperture standard deviation", self.synthetic_aperture_std),
            ("Mid-surface RMS roughness", self.synthetic_mid_rms),
            ("Minimum aperture", self.synthetic_minimum),
            ("Maximum aperture (optional)", self.synthetic_maximum),
            ("Contact-area fraction", self.synthetic_contact),
        )
        anisotropy_rows = (
            ("Hurst exponent X", self.synthetic_hurst_x),
            ("Hurst exponent Y", self.synthetic_hurst_y),
            ("Correlation length X (optional)", self.synthetic_correlation_x),
            ("Correlation length Y (optional)", self.synthetic_correlation_y),
            ("Mean-plane slope X", self.synthetic_slope_x),
            ("Mean-plane slope Y", self.synthetic_slope_y),
        )
        synthetic_groups = (
            ("Grid and ensemble", grid_rows),
            ("Aperture and roughness", aperture_rows),
            ("Anisotropy and mean plane", anisotropy_rows),
        )
        for column, (title, rows) in enumerate(synthetic_groups):
            group = ttk.LabelFrame(
                synthesis,
                text=title,
                style="Section.TLabelframe",
                padding=10,
            )
            padx = (0, 5) if column == 0 else ((5, 5) if column == 1 else (5, 0))
            group.grid(row=2, column=column, sticky="nsew", padx=padx)
            group.columnconfigure(1, weight=1)
            synthesis.columnconfigure(column, weight=1)
            for row, (label, variable) in enumerate(rows):
                self._row(
                    group,
                    row,
                    label,
                    variable,
                    (
                        "Synthetic spectral target; achieved values are "
                        "recalculated and exported."
                    ),
                )
        ttk.Checkbutton(
            synthesis,
            text="Enforce non-negative aperture",
            variable=self.synthetic_positive,
            style="Card.TCheckbutton",
        ).grid(row=3, column=1, sticky="w", padx=5, pady=(8, 0))

        output_frame = ttk.Frame(results, style="Card.TFrame")
        output_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        output_frame.columnconfigure(1, weight=1)
        ttk.Label(
            output_frame,
            text="Results folder",
            style="Card.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(0, 9))
        ttk.Entry(
            output_frame,
            textvariable=self.output_directory,
            style="Scientific.TEntry",
            state="readonly",
        ).grid(row=0, column=1, sticky="ew")
        ttk.Label(
            results,
            text=(
                "PNG figures and all JSON/CSV/Markdown results are stored "
                "automatically inside the selected working directory."
            ),
            style="CardMuted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.result_text = tk.Text(
            results,
            height=20,
            wrap="word",
            state="disabled",
            background=self.colors["card"],
            foreground=self.colors["ink"],
            highlightbackground=self.colors["line"],
            highlightthickness=1,
            relief="flat",
            font=("Segoe UI", 9),
        )
        self.result_text.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        results.rowconfigure(2, weight=1)

        ttk.Progressbar(
            body,
            variable=self.progress,
            maximum=100,
            mode="determinate",
            style="Scientific.Horizontal.TProgressbar",
        ).pack(fill="x", pady=(12, 4))
        ttk.Label(body, textvariable=self.status, style="Muted.TLabel").pack(anchor="w")
        buttons = ttk.Frame(body, style="Scientific.TFrame")
        buttons.pack(fill="x", pady=(10, 0))
        self.calculate_button = ttk.Button(
            buttons,
            text="Characterize only",
            style="Accent.TButton",
            command=lambda: self._start(continue_after=False),
        )
        self.calculate_button.pack(side="left")
        self.mesh_button = ttk.Button(
            buttons,
            text="Characterize and continue to mesh",
            style="Primary.TButton",
            command=lambda: self._start(continue_after=True),
        )
        self.mesh_button.pack(side="left", padx=(7, 0))
        self.cancel_button = ttk.Button(
            buttons,
            text="Cancel",
            command=self.cancel_event.set,
            state="disabled",
            style="Quiet.TButton",
        )
        self.cancel_button.pack(side="left", padx=(7, 0))
        ttk.Button(
            buttons,
            text="Save synthetic settings…",
            style="Quiet.TButton",
            command=self._save_settings,
        ).pack(
            side="right"
        )
        ttk.Button(
            buttons,
            text="Load synthetic settings…",
            style="Quiet.TButton",
            command=self._load_settings,
        ).pack(
            side="right", padx=(0, 7)
        )

    def _apply_synthetic_preset(self, preset: str) -> None:
        presets = {
            "planar": {
                "synthetic_points_x": "48",
                "synthetic_points_y": "40",
                "synthetic_size_x": "1.2",
                "synthetic_size_y": "0.9",
                "synthetic_mean_aperture": "2e-4",
                "synthetic_aperture_std": "0",
                "synthetic_mid_rms": "0",
                "synthetic_hurst_x": "0.8",
                "synthetic_hurst_y": "0.8",
                "synthetic_correlation_x": "",
                "synthetic_correlation_y": "",
                "synthetic_minimum": "2e-4",
                "synthetic_maximum": "2e-4",
                "synthetic_contact": "0",
                "synthetic_slope_x": "0",
                "synthetic_slope_y": "0",
                "seed": "20260723",
                "synthetic_realizations": "1",
            },
            "rough": {
                "synthetic_points_x": "96",
                "synthetic_points_y": "72",
                "synthetic_size_x": "1.2",
                "synthetic_size_y": "0.9",
                "synthetic_mean_aperture": "2e-4",
                "synthetic_aperture_std": "5e-5",
                "synthetic_mid_rms": "3e-5",
                "synthetic_hurst_x": "0.8",
                "synthetic_hurst_y": "0.6",
                "synthetic_correlation_x": "0.25",
                "synthetic_correlation_y": "0.08",
                "synthetic_minimum": "1e-6",
                "synthetic_maximum": "",
                "synthetic_contact": "0",
                "synthetic_slope_x": "0",
                "synthetic_slope_y": "0",
                "seed": "20260724",
                "synthetic_realizations": "1",
            },
            "contact": {
                "synthetic_points_x": "80",
                "synthetic_points_y": "80",
                "synthetic_size_x": "1.0",
                "synthetic_size_y": "1.0",
                "synthetic_mean_aperture": "1.5e-4",
                "synthetic_aperture_std": "6e-5",
                "synthetic_mid_rms": "4e-5",
                "synthetic_hurst_x": "0.75",
                "synthetic_hurst_y": "0.55",
                "synthetic_correlation_x": "0.18",
                "synthetic_correlation_y": "0.06",
                "synthetic_minimum": "0",
                "synthetic_maximum": "3e-4",
                "synthetic_contact": "0.08",
                "synthetic_slope_x": "0.01",
                "synthetic_slope_y": "-0.005",
                "seed": "20260725",
                "synthetic_realizations": "3",
            },
        }
        notes = {
            "planar": "Constant opening: analytical equality checks.",
            "rough": "Anisotropic Hurst and correlation targets.",
            "contact": "Bounds, contacts, slopes, and three realizations.",
        }
        self.synthetic_enabled.set(True)
        self.synthetic_positive.set(True)
        self._apply_settings(presets[preset])
        self.synthetic_preset_note.set(notes[preset])

    def _config(self) -> CharacterizationConfig:
        return CharacterizationConfig(
            aperture_method="local_normal",
            flow_direction="Y",
            tortuosity_direction="Y",
            aperture_cutoff=1.0e-12,
            allow_negative_aperture=False,
            interpolate_missing=False,
            length_unit="m",
            normal_smoothing_sigma=0.0,
            hurst_min_lag=1,
            hurst_max_scale_fraction=0.25,
            hurst_bootstrap_samples=100,
            random_seed=20260723,
            publication_formats=("png",),
        ).validated()

    @staticmethod
    def _optional_float(value: str) -> float | None:
        return float(value) if value.strip() else None

    def _synthetic_config(self) -> SyntheticConfig | None:
        if not self.synthetic_enabled.get():
            return None
        return SyntheticConfig(
            points_x=int(self.synthetic_points_x.get()),
            points_y=int(self.synthetic_points_y.get()),
            size_x=float(self.synthetic_size_x.get()),
            size_y=float(self.synthetic_size_y.get()),
            mean_aperture=float(self.synthetic_mean_aperture.get()),
            aperture_std=float(self.synthetic_aperture_std.get()),
            mid_surface_rms=float(self.synthetic_mid_rms.get()),
            hurst_x=float(self.synthetic_hurst_x.get()),
            hurst_y=float(self.synthetic_hurst_y.get()),
            correlation_length_x=self._optional_float(
                self.synthetic_correlation_x.get()
            ),
            correlation_length_y=self._optional_float(
                self.synthetic_correlation_y.get()
            ),
            minimum_aperture=float(self.synthetic_minimum.get()),
            maximum_aperture=self._optional_float(self.synthetic_maximum.get()),
            contact_fraction=float(self.synthetic_contact.get()),
            positive_aperture=self.synthetic_positive.get(),
            mean_plane_slopes=(
                float(self.synthetic_slope_x.get()),
                float(self.synthetic_slope_y.get()),
            ),
            random_seed=int(self.seed.get()),
            realizations=int(self.synthetic_realizations.get()),
        ).validated()

    def _settings(self) -> dict[str, Any]:
        names = (
            "synthetic_enabled",
            "synthetic_points_x",
            "synthetic_points_y",
            "synthetic_size_x",
            "synthetic_size_y",
            "synthetic_mean_aperture",
            "synthetic_aperture_std",
            "synthetic_mid_rms",
            "synthetic_hurst_x",
            "synthetic_hurst_y",
            "synthetic_correlation_x",
            "synthetic_correlation_y",
            "synthetic_minimum",
            "synthetic_maximum",
            "synthetic_contact",
            "synthetic_slope_x",
            "synthetic_slope_y",
            "synthetic_positive",
            "seed",
            "synthetic_realizations",
        )
        return {
            name: getattr(self, name).get()
            for name in names
        }

    def _apply_settings(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            variable = getattr(self, key, None)
            if isinstance(variable, (tk.StringVar, tk.BooleanVar)):
                variable.set(value)

    def refresh_output_directory(self, *_args) -> None:
        """Display the output derived from the current Workbench run folder."""

        try:
            output = self.output_directory_provider().expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            self.output_directory.set(
                "Select a working directory in 1 Geometry & inputs"
            )
        else:
            self.output_directory.set(str(output))

    def _resolved_output_directory(self) -> Path:
        """Resolve output at run time so a stale GUI value can never be used."""

        output = self.output_directory_provider().expanduser().resolve()
        self.output_directory.set(str(output))
        return output

    def _save_settings(self) -> None:
        selected = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".json",
            filetypes=[("JSON settings", "*.json")],
        )
        if selected:
            Path(selected).write_text(
                json.dumps(self._settings(), indent=2) + "\n",
                encoding="utf-8",
            )

    def _load_settings(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            filetypes=[("JSON settings", "*.json")],
        )
        if selected:
            self._apply_settings(json.loads(Path(selected).read_text(encoding="utf-8")))

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.calculate_button.configure(state=state)
        self.mesh_button.configure(state=state)
        self.cancel_button.configure(state="normal" if running else "disabled")

    def start(self, *, continue_after: bool) -> None:
        """Start a non-blocking run from the embedded Workbench tab."""

        self._start(continue_after=continue_after)

    def _start(self, *, continue_after: bool) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        try:
            config = self._config()
            synthetic = self._synthetic_config()
            output = self._resolved_output_directory()
            source = self.surface_source()
        except Exception as exc:
            messagebox.showerror("Characterization settings", str(exc), parent=self)
            return
        self.cancel_event.clear()
        self.progress.set(0)
        self.status.set("Preparing reconstructed crack surface…")
        self._set_running(True)

        def worker() -> None:
            try:
                grid = build_surface_grid(source)
                result = characterize_surface(
                    grid,
                    config,
                    output_directory=output,
                    synthetic_config=synthetic,
                    progress=lambda fraction, message: self.messages.put(
                        ("progress", (fraction, message))
                    ),
                    cancelled=self.cancel_event.is_set,
                )
                self.messages.put(("complete", (result, continue_after)))
            except Exception as exc:
                self.messages.put(("error", exc))

        self.worker = threading.Thread(
            target=worker,
            name="crack-characterization",
            daemon=True,
        )
        self.worker.start()

    def _poll_worker(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "progress":
                    fraction, message = payload
                    self.progress.set(100.0 * fraction)
                    self.status.set(message)
                elif kind == "complete":
                    result, continue_after = payload
                    self._complete(result, continue_after)
                else:
                    self._failed(payload)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll_worker)

    def _complete(self, result: AnalysisResult, continue_after: bool) -> None:
        self.last_result = result
        self._set_running(False)
        self.progress.set(100)
        self.status.set(f"Complete — {result.output_directory}")
        apertures = result.summary["apertures"]
        hydraulic = result.summary["hydraulic_by_aperture_and_direction"][
            "local_normal"
        ]
        tortuosity = result.summary["tortuosity"]["directions"]
        wavelet_fields = result.summary["wavelet_decomposition"]["field_results"]
        wavelet_error = max(
            field["reconstruction_maximum_absolute_error"]
            for field in wavelet_fields.values()
        )
        text = (
            "Automatic comprehensive analysis complete\n\n"
            "Mean aperture — global Z / local normal: "
            f"{apertures['global_z']['statistics']['arithmetic_mean']:.8g} / "
            f"{apertures['local_normal']['statistics']['arithmetic_mean']:.8g}\n"
            "Local-normal equivalent aperture — X / Y: "
            f"{hydraulic['X']['global_equivalent_hydraulic_aperture']:.8g} / "
            f"{hydraulic['Y']['global_equivalent_hydraulic_aperture']:.8g}\n"
            "Mid-surface geometrical tortuosity — X / Y: "
            f"{tortuosity['X']['mid']['mean']:.8g} / "
            f"{tortuosity['Y']['mid']['mean']:.8g}\n"
            "Hurst fits: X and Y × structure function and profile PSD\n"
            f"Wavelet fields: 5; maximum reconstruction error: {wavelet_error:.3e}\n"
            f"Warnings: {len(result.warnings)}\n\n"
            f"Report: {result.exported_files.get('characterization_report')}\n"
            "Wavelet folder: "
            f"{result.exported_files.get('wavelet_decomposition_directory')}"
        )
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")
        if self.on_complete is not None:
            self.on_complete(result)
        if continue_after and self.continue_to_mesh is not None:
            self.after(150, self.continue_to_mesh)

    def _failed(self, error: Exception) -> None:
        self._set_running(False)
        self.progress.set(0)
        if isinstance(error, InterruptedError):
            self.status.set("Characterization cancelled.")
        else:
            self.status.set("Characterization failed. Review the message.")
            messagebox.showerror("Crack characterization", str(error), parent=self)
