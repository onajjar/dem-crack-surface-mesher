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
        default_output: Path,
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
        self.on_complete = on_complete
        self.continue_to_mesh = continue_to_mesh
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.messages: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.last_result: AnalysisResult | None = None
        self._build_variables(default_output)
        self._build_interface()
        self.after(100, self._poll_worker)

    def _build_variables(self, default_output: Path) -> None:
        self.aperture_method = tk.StringVar(value="local_normal")
        self.flow_direction = tk.StringVar(value="Y")
        self.custom_flow = tk.StringVar(value="1, 1, 0")
        self.tortuosity_direction = tk.StringVar(value="flow")
        self.custom_tortuosity = tk.StringVar(value="1, 1, 0")
        self.aperture_cutoff = tk.StringVar(value="1e-12")
        self.length_unit = tk.StringVar(value="m")
        self.normal_smoothing = tk.StringVar(value="0")
        self.interpolate_missing = tk.BooleanVar(value=False)
        self.allow_negative = tk.BooleanVar(value=False)
        self.hurst_min_lag = tk.StringVar(value="1")
        self.hurst_max_fraction = tk.StringVar(value="0.25")
        self.hurst_bootstrap = tk.StringVar(value="100")
        self.seed = tk.StringVar(value="20260723")
        self.formats = tk.StringVar(value="png")
        self.output_directory = tk.StringVar(value=str(default_output))
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
        self.synthetic_realizations = tk.StringVar(value="1")
        self.status = tk.StringVar(value="Ready. Review definitions, then calculate.")
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
        notebook.pack(fill="x", expand=False)
        analysis = ttk.Frame(notebook, style="Card.TFrame", padding=14)
        synthesis = ttk.Frame(notebook, style="Card.TFrame", padding=14)
        results = ttk.Frame(notebook, style="Card.TFrame", padding=14)
        notebook.add(analysis, text="Input & definitions")
        notebook.add(synthesis, text="Synthetic surface")
        notebook.add(results, text="Results & export")
        for tab in (analysis, synthesis, results):
            tab.columnconfigure(1, weight=1)

        definitions = ttk.LabelFrame(
            analysis,
            text="Aperture and directional definitions",
            style="Section.TLabelframe",
            padding=12,
        )
        definitions.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        definitions.columnconfigure(1, weight=1)
        diagnostics = ttk.LabelFrame(
            analysis,
            text="Numerical diagnostics",
            style="Section.TLabelframe",
            padding=12,
        )
        diagnostics.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        diagnostics.columnconfigure(1, weight=1)
        analysis.columnconfigure(0, weight=1)
        analysis.columnconfigure(1, weight=1)

        self._row(
            definitions,
            0,
            "Aperture definition",
            self.aperture_method,
            (
                "global_z uses upper minus lower Z at matching samples. local_normal "
                "projects that separation onto finite-difference mid-surface normals."
            ),
            values=("local_normal", "global_z"),
        )
        self._row(
            definitions,
            1,
            "Flow direction",
            self.flow_direction,
            (
                "The global vector is projected into the least-squares crack plane. "
                "A Z direction normal to a flat crack is undefined and will be rejected."
            ),
            values=("X", "Y", "Z", "custom", "auto"),
        )
        self._row(
            definitions,
            2,
            "Custom flow vector",
            self.custom_flow,
            "Three global Cartesian components used when Flow direction is custom.",
        )
        self._row(
            definitions,
            3,
            "Tortuosity direction",
            self.tortuosity_direction,
            "Geometrical profile-length/projected-length direction; never labeled hydraulic.",
            values=("flow", "transverse", "X", "Y", "Z", "custom"),
        )
        self._row(
            definitions,
            4,
            "Custom tortuosity vector",
            self.custom_tortuosity,
            "Three global Cartesian components used for custom tortuosity profiles.",
        )
        self._row(
            definitions,
            5,
            "Hydraulic aperture cutoff",
            self.aperture_cutoff,
            (
                "Samples at or below this physical opening are treated as closed in "
                "1/b³ resistance. They remain reported in opening statistics."
            ),
        )
        self._row(
            definitions,
            6,
            "Length unit",
            self.length_unit,
            "Metadata only. Input coordinates are preserved and never rescaled.",
        )
        self._row(
            diagnostics,
            0,
            "Normal smoothing σ [grid points]",
            self.normal_smoothing,
            "Optional Gaussian smoothing used only before estimating mid-surface normals.",
        )
        self._row(
            diagnostics,
            1,
            "Hurst minimum lag [samples]",
            self.hurst_min_lag,
            "Smallest structure-function separation; use at least one grid interval.",
        )
        self._row(
            diagnostics,
            2,
            "Hurst maximum scale fraction",
            self.hurst_max_fraction,
            "Largest fitted scale as a fraction of profile length; capped at 0.5.",
        )
        self._row(
            diagnostics,
            3,
            "Bootstrap resamples",
            self.hurst_bootstrap,
            "Profile-resampling count for 95% Hurst confidence intervals; zero disables.",
        )
        self._row(
            diagnostics,
            4,
            "Random seed",
            self.seed,
            "Reproducible seed for Hurst bootstrap and synthetic surface generation.",
        )
        ttk.Checkbutton(
            diagnostics,
            text="Interpolate missing wall heights (linear, nearest boundary fallback)",
            variable=self.interpolate_missing,
            style="Card.TCheckbutton",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(
            diagnostics,
            text="Permit negative geometrical aperture (still excluded hydraulically)",
            variable=self.allow_negative,
            style="Card.TCheckbutton",
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=4)

        ttk.Checkbutton(
            synthesis,
            text="Generate and verify a statistically representative synthetic surface",
            variable=self.synthetic_enabled,
            style="Card.TCheckbutton",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        synthetic_rows = (
            ("Grid points X", self.synthetic_points_x),
            ("Grid points Y", self.synthetic_points_y),
            ("Size X", self.synthetic_size_x),
            ("Size Y", self.synthetic_size_y),
            ("Mean aperture", self.synthetic_mean_aperture),
            ("Aperture standard deviation", self.synthetic_aperture_std),
            ("Mid-surface RMS roughness", self.synthetic_mid_rms),
            ("Hurst exponent X", self.synthetic_hurst_x),
            ("Hurst exponent Y", self.synthetic_hurst_y),
            ("Correlation length X (optional)", self.synthetic_correlation_x),
            ("Correlation length Y (optional)", self.synthetic_correlation_y),
            ("Minimum aperture", self.synthetic_minimum),
            ("Maximum aperture (optional)", self.synthetic_maximum),
            ("Contact-area fraction", self.synthetic_contact),
            ("Number of realizations", self.synthetic_realizations),
        )
        synthetic_geometry = ttk.LabelFrame(
            synthesis,
            text="Grid, aperture, and roughness",
            style="Section.TLabelframe",
            padding=12,
        )
        synthetic_geometry.grid(row=1, column=0, sticky="nsew", padx=(0, 7))
        synthetic_geometry.columnconfigure(1, weight=1)
        synthetic_statistics = ttk.LabelFrame(
            synthesis,
            text="Scaling, bounds, and ensemble",
            style="Section.TLabelframe",
            padding=12,
        )
        synthetic_statistics.grid(row=1, column=1, sticky="nsew", padx=(7, 0))
        synthetic_statistics.columnconfigure(1, weight=1)
        for index, (label, variable) in enumerate(synthetic_rows):
            target = synthetic_geometry if index < 8 else synthetic_statistics
            row = index if index < 8 else index - 8
            self._row(
                target,
                row,
                label,
                variable,
                "Synthetic spectral target; achieved values are recalculated and exported.",
            )

        output_frame = ttk.Frame(results, style="Card.TFrame")
        output_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        output_frame.columnconfigure(0, weight=1)
        ttk.Entry(
            output_frame,
            textvariable=self.output_directory,
            style="Scientific.TEntry",
        ).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(
            output_frame,
            text="Browse…",
            style="Quiet.TButton",
            command=self._browse_output,
        ).grid(
            row=0, column=1, padx=(7, 0)
        )
        self._row(
            results,
            1,
            "Figure formats",
            self.formats,
            "Comma-separated publication formats: png, pdf, svg.",
        )
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
            text="Save settings…",
            style="Quiet.TButton",
            command=self._save_settings,
        ).pack(
            side="right"
        )
        ttk.Button(
            buttons,
            text="Load settings…",
            style="Quiet.TButton",
            command=self._load_settings,
        ).pack(
            side="right", padx=(0, 7)
        )

    @staticmethod
    def _parse_vector(value: str) -> tuple[float, float, float]:
        parts = [part for part in value.replace(",", " ").split() if part]
        if len(parts) != 3:
            raise ValueError("Custom flow vector must contain exactly three components.")
        return tuple(float(part) for part in parts)

    def _config(self) -> CharacterizationConfig:
        return CharacterizationConfig(
            aperture_method=self.aperture_method.get(),
            flow_direction=self.flow_direction.get(),
            custom_flow_vector=self._parse_vector(self.custom_flow.get()),
            tortuosity_direction=self.tortuosity_direction.get(),
            custom_tortuosity_vector=self._parse_vector(
                self.custom_tortuosity.get()
            ),
            aperture_cutoff=float(self.aperture_cutoff.get()),
            allow_negative_aperture=self.allow_negative.get(),
            interpolate_missing=self.interpolate_missing.get(),
            length_unit=self.length_unit.get(),
            normal_smoothing_sigma=float(self.normal_smoothing.get()),
            hurst_min_lag=int(self.hurst_min_lag.get()),
            hurst_max_scale_fraction=float(self.hurst_max_fraction.get()),
            hurst_bootstrap_samples=int(self.hurst_bootstrap.get()),
            random_seed=int(self.seed.get()),
            publication_formats=tuple(
                item.strip().lower()
                for item in self.formats.get().split(",")
                if item.strip()
            ),
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
            random_seed=int(self.seed.get()),
            realizations=int(self.synthetic_realizations.get()),
        ).validated()

    def _settings(self) -> dict[str, Any]:
        return {
            key: variable.get()
            for key, variable in self.__dict__.items()
            if isinstance(variable, (tk.StringVar, tk.BooleanVar))
        }

    def _apply_settings(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            variable = getattr(self, key, None)
            if isinstance(variable, (tk.StringVar, tk.BooleanVar)):
                variable.set(value)

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(
            parent=self,
            title="Characterization output directory",
        )
        if selected:
            self.output_directory.set(selected)

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
            output = Path(self.output_directory.get()).expanduser().resolve()
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
        aperture = result.summary["aperture"]["statistics"]
        hydraulic = result.summary["hydraulic"]
        tortuosity = result.summary["tortuosity"]["mid"]
        text = (
            f"Arithmetic mean aperture: {aperture['arithmetic_mean']:.8g}\n"
            f"Cubic-mean aperture: {aperture['global_cubic_mean']:.8g}\n"
            f"Flow-path equivalent aperture: "
            f"{hydraulic['global_equivalent_hydraulic_aperture']:.8g}\n"
            f"Mean geometrical tortuosity: {tortuosity['mean']:.8g}\n"
            f"Warnings: {len(result.warnings)}\n\n"
            f"Report: {result.exported_files.get('characterization_report')}"
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
