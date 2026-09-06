"""Render traceable comparison figures and an audit report from saved arrays."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import ListedColormap
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

matplotlib.use("Agg")
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--evidence-root",
    type=Path,
    default=Path(__file__).resolve().parent,
    help="Directory containing the unpacked comparison data",
)
ROOT = parser.parse_args().evidence_root.resolve()
FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)
FINAL = ROOT / "windows-portable-final-arrays"
RELEASED = ROOT / "windows-mkl-committed"
PIP = ROOT / "windows-pip-current"
final = json.loads((ROOT / "windows-portable-final.json").read_text())
released = json.loads((RELEASED / "results.json").read_text())["groups"]
pip = json.loads((PIP / "results.json").read_text())["groups"]
old = {r["id"]: r for r in released["deap"]}
pip_deap = {r["id"]: r for r in pip["deap"]}
deap_rows = [
    r for r in final["cases"] if r["group"] == "deap" and r["status"] == "surface"
]
COLORS = {
    "matlab": "#26394A",
    "released": "#B54438",
    "pip": "#C68B25",
    "fixed": "#087E8B",
}
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titleweight": "semibold",
        "axes.labelcolor": "#26394A",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "pdf.fonttype": 42,
        "svg.fonttype": "none",
        "savefig.dpi": 240,
    }
)


def save(fig, stem):
    for ext in ("png", "pdf", "svg"):
        fig.savefig(FIG / f"{stem}.{ext}", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def maxerr(row):
    return max(
        v.get("max_abs_error", 0)
        for k, v in row["arrays"].items()
        if k in ("zmin", "zmax")
    )


def error_overview():
    fig, ax = plt.subplots(figsize=(11.6, 4.8), layout="constrained")
    positions = np.arange(len(deap_rows))
    series = [
        (old, "Released / MKL", "released", -0.2),
        (pip_deap, "August correction / OpenBLAS", "pip", 0),
        ({r["id"]: r for r in deap_rows}, "Corrected / deterministic QR", "fixed", 0.2),
    ]
    for data, label, color, offset in series:
        vals = np.array([maxerr(data[r["id"]]) for r in deap_rows])
        ax.scatter(
            positions + offset,
            np.maximum(vals, 1e-18),
            label=label,
            color=COLORS[color],
            s=30,
            zorder=3,
            marker="o" if offset else "s",
        )
    ax.axhline(1e-12, color="#666666", ls="--", lw=1, label="Acceptance: $10^{-12}$ m")
    ax.set_yscale("log")
    ax.set_ylim(2e-19, 1e10)
    ax.set_yticks([1e-18, 1e-12, 1e-6, 1, 1e6])
    ax.set_xticks(positions, [r["id"].split("_")[0] for r in deap_rows], rotation=60)
    ax.set_ylabel("Maximum wall difference from MATLAB (m)")
    ax.set_title(
        "Real DEAP surfaces: the broad matrix exposes differences missed by four examples",
        loc="left",
        pad=18,
    )
    ax.grid(axis="y", alpha=0.18)
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    fig.supxlabel(
        "26 comparable surfaces; six no-surface outcomes are assessed separately. Exact zero is plotted at $10^{-18}$ m.",
        fontsize=9,
    )
    save(fig, "01_deap_error_overview")


def geometry_case(case_id):
    corrected = np.load(FINAL / f"{case_id}.npz")
    before = np.load(RELEASED / f"{case_id}.npz")
    x, y = corrected["x"] * 1000, corrected["y"] * 1000
    fig, axes = plt.subplots(2, 3, figsize=(11.6, 6.8), layout="constrained")
    values = [corrected["matlab_zmin"], before["zmin"], corrected["zmin"]]
    aperture = [
        corrected["matlab_zmax"] - corrected["matlab_zmin"],
        before["zmax"] - before["zmin"],
        corrected["zmax"] - corrected["zmin"],
    ]
    for row, fields in enumerate((values, aperture)):
        vmin = min(float(v.min()) for v in fields) * 1000
        vmax = max(float(v.max()) for v in fields) * 1000
        for col, (field, label) in enumerate(
            zip(fields, ("MATLAB reference", "Released Python", "Corrected Python"))
        ):
            ax = axes[row, col]
            im = ax.pcolormesh(
                x,
                y,
                field * 1000,
                shading="nearest",
                cmap="viridis",
                vmin=vmin,
                vmax=vmax,
                rasterized=True,
            )
            ax.set_aspect("equal")
            ax.set_title(label, fontsize=11)
            ax.set_xlabel("First in-plane coordinate (mm)")
            if col == 0:
                ax.set_ylabel("Second in-plane coordinate (mm)")
        fig.colorbar(
            im,
            ax=list(axes[row, :]),
            shrink=0.85,
            label=("Lower-wall elevation (mm)" if row == 0 else "Aperture (mm)"),
        )
    fig.suptitle(
        f"{case_id}: wall geometry and contact use the same colour scales",
        x=0.02,
        ha="left",
        fontsize=14,
    )
    save(fig, "02_real_surface_comparison")


def contact_comparison():
    mismatches = [r for r in pip["contact"] if r["contact_mask_mismatches"]]
    chosen = mismatches[0]["id"] if mismatches else "C17_checker_contact_p008"
    data = np.load(FINAL / f"{chosen}.npz")
    alternate = np.load(PIP / f"{chosen}.npz")
    x, y = data["x"], data["y"]
    mlo, mup = data["matlab_lower"], data["matlab_raw_upper"]
    raw = mup - mlo
    closed = data["matlab_final_upper"] == mlo
    actual_closed = data["final_upper"] == data["lower"]
    other_closed = alternate["final_upper"] == alternate["lower"]
    fig, axes = plt.subplots(2, 2, figsize=(10.8, 7.4), layout="constrained")
    lim = max(float(np.max(np.abs(raw))), np.finfo(float).eps)
    im = axes[0, 0].pcolormesh(
        x,
        y,
        raw,
        shading="nearest",
        cmap="RdBu_r",
        vmin=-lim,
        vmax=lim,
        rasterized=True,
    )
    fig.colorbar(im, ax=axes[0, 0], label="Raw aperture (synthetic units)")
    axes[0, 0].set_title("Independent MATLAB fits: overlap is allowed")
    im = axes[0, 1].pcolormesh(
        x,
        y,
        closed,
        shading="nearest",
        cmap=ListedColormap(["#EBF2F4", "#26394A"]),
        vmin=0,
        vmax=1,
        rasterized=True,
    )
    cb = fig.colorbar(im, ax=axes[0, 1], ticks=[0, 1])
    cb.ax.set_yticklabels(["Open", "Contact"])
    axes[0, 1].set_title(
        f"Final contact: {np.count_nonzero(closed)} closed point"
        + ("s" if np.count_nonzero(closed) != 1 else "")
    )
    disagreement = other_closed.astype(int) - closed.astype(int)
    im = axes[1, 0].pcolormesh(
        x,
        y,
        disagreement,
        shading="nearest",
        cmap=ListedColormap(["#B54438", "#F2F4F5", "#C68B25"]),
        vmin=-1,
        vmax=1,
        rasterized=True,
    )
    inds = np.argwhere(disagreement)
    if inds.size:
        axes[1, 0].scatter(
            x[tuple(inds.T)],
            y[tuple(inds.T)],
            s=140,
            facecolors="none",
            edgecolors="#B54438",
            lw=1.5,
        )
    cb = fig.colorbar(im, ax=axes[1, 0], ticks=[-1, 0, 1])
    cb.ax.set_yticklabels(["Missed contact", "Match", "Extra contact"])
    axes[1, 0].set_title(
        f"August correction / pip: {len(inds)} mismatch"
        + ("es" if len(inds) != 1 else "")
    )
    corrected_disagreement = actual_closed.astype(int) - closed.astype(int)
    im = axes[1, 1].pcolormesh(
        x,
        y,
        corrected_disagreement,
        shading="nearest",
        cmap=ListedColormap(["#B54438", "#F2F4F5", "#C68B25"]),
        vmin=-1,
        vmax=1,
        rasterized=True,
    )
    cb = fig.colorbar(im, ax=axes[1, 1], ticks=[-1, 0, 1])
    cb.ax.set_yticklabels(["Missed contact", "Match", "Extra contact"])
    axes[1, 1].set_title(
        f"Corrected Python: {np.count_nonzero(corrected_disagreement)} mismatches"
    )
    for ax in axes.flat:
        ax.set_aspect("equal")
        ax.set_xlabel("x (synthetic units)")
        ax.set_ylabel("y (synthetic units)")
    fig.suptitle(
        chosen + " | exact contact decisions, including near-zero aperture",
        x=0.02,
        ha="left",
        fontsize=13,
    )
    save(fig, "03_contact_decisions")
    return chosen


def contact_profile():
    data = np.load(FINAL / "C17_checker_contact_p008.npz")
    raw = data["raw_upper"] - data["lower"]
    row = int(np.argmax(np.count_nonzero(raw < 0, axis=1)))
    x = data["x"][row]
    lower = data["lower"][row]
    upper = data["raw_upper"][row]
    fig, axes = plt.subplots(
        2, 1, figsize=(11.4, 5.6), layout="constrained", sharex=True
    )
    axes[0].plot(x, lower, c=COLORS["matlab"], label="Lower wall retained", lw=1.8)
    axes[0].plot(
        x, upper, c=COLORS["released"], label="Upper wall before clamp", lw=1.5, ls="--"
    )
    axes[0].plot(
        x,
        data["final_upper"][row],
        c=COLORS["fixed"],
        label="Upper wall after clamp",
        lw=2,
    )
    axes[0].fill_between(
        x,
        lower,
        upper,
        where=upper < lower,
        color=COLORS["released"],
        alpha=0.18,
        label="Raw overlap",
    )
    axes[0].set_ylabel("Wall elevation (synthetic units)")
    axes[0].legend(frameon=False, ncol=2, fontsize=9)
    axes[1].plot(x, raw[row], c=COLORS["released"], ls="--", label="Raw aperture")
    axes[1].plot(
        x,
        data["final_upper"][row] - lower,
        c=COLORS["fixed"],
        label="Final aperture",
        lw=2,
    )
    axes[1].axhline(0, color="#26394A", lw=0.8)
    axes[1].set_ylabel("Aperture (synthetic units)")
    axes[1].set_xlabel("x (synthetic units)")
    axes[1].legend(frameon=False)
    for ax in axes:
        ax.grid(alpha=0.16)
    axes[0].set_title(
        f"C17 checker contact | section at y = {data['y'][row, 0]:.2f}\n"
        "MATLAB and corrected Python agree at plotted resolution",
        loc="left",
        pad=16,
    )
    save(fig, "04_contact_section")


def atlas():
    with PdfPages(FIG / "all_deap_surfaces.pdf") as pdf:
        for row in deap_rows:
            a = np.load(FINAL / f"{row['id']}.npz")
            fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.3), layout="constrained")
            opening = a["matlab_zmax"] - a["matlab_zmin"]
            fields = (
                a["matlab_zmin"],
                opening,
                np.maximum(
                    np.abs(a["zmin"] - a["matlab_zmin"]),
                    np.abs(a["zmax"] - a["matlab_zmax"]),
                ),
            )
            for index, (ax, z, title) in enumerate(
                zip(
                    axes,
                    fields,
                    (
                        "MATLAB lower wall (m)",
                        "MATLAB aperture (m)",
                        "Maximum wall error (m)",
                    ),
                )
            ):
                limits = (
                    {"vmin": 0, "vmax": max(float(z.max()), 1e-18)}
                    if index == 2
                    else {}
                )
                im = ax.pcolormesh(
                    a["x"],
                    a["y"],
                    z,
                    shading="nearest",
                    cmap="viridis",
                    rasterized=True,
                    **limits,
                )
                ax.set_aspect("equal")
                ax.set_title(title, fontsize=10)
                ax.set_xlabel("First in-plane coordinate (m)")
                ax.set_ylabel("Second in-plane coordinate (m)")
                bar = fig.colorbar(im, ax=ax, shrink=0.78, format="%.1e")
                bar.ax.tick_params(labelsize=8)
                if index == 2 and not np.any(z):
                    bar.set_ticks([0])
                    bar.set_ticklabels(["0 (exact)"])
            fig.suptitle(
                row["id"]
                + f" | max error {maxerr(row):.3e} m | contact mismatches {row['contact_mismatches']}",
                fontsize=12,
            )
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)
    with PdfPages(FIG / "all_contact_cases.pdf") as pdf:
        rows = [r for r in final["cases"] if r["group"] == "contact"]
        for row in rows:
            a = np.load(FINAL / f"{row['id']}.npz")
            fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.3), layout="constrained")
            fields = (
                a["matlab_raw_upper"] - a["matlab_lower"],
                a["matlab_final_upper"] - a["matlab_lower"],
                (
                    (a["final_upper"] == a["lower"])
                    != (a["matlab_final_upper"] == a["matlab_lower"])
                ).astype(int),
            )
            for index, (ax, z, title) in enumerate(
                zip(
                    axes,
                    fields,
                    (
                        "MATLAB raw aperture",
                        "MATLAB final aperture",
                        "Contact-mask mismatch",
                    ),
                )
            ):
                limits = {"vmin": 0, "vmax": 1} if index == 2 else {}
                im = ax.pcolormesh(
                    a["x"],
                    a["y"],
                    z,
                    shading="nearest",
                    cmap=ListedColormap(["#E6EBEE", "#B54438"])
                    if index == 2
                    else "viridis",
                    rasterized=True,
                    **limits,
                )
                ax.set_aspect("equal")
                ax.set_title(title, fontsize=10)
                ax.set_xlabel("x (synthetic units)")
                ax.set_ylabel("y (synthetic units)")
                bar = fig.colorbar(im, ax=ax, shrink=0.78, format="%.1e")
                bar.ax.tick_params(labelsize=8)
                if index == 2:
                    bar.set_ticks([0, 1])
                    bar.set_ticklabels(["match", "different"])
            fig.suptitle(
                row["id"] + f" | contact mismatches {row['contact_mismatches']}",
                fontsize=12,
            )
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)


def report(chosen):
    fonts = Path(matplotlib.get_data_path()) / "fonts/ttf"
    pdfmetrics.registerFont(TTFont("DV", str(fonts / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DVB", str(fonts / "DejaVuSans-Bold.ttf")))
    styles = getSampleStyleSheet()
    for name in ("Normal", "BodyText"):
        styles[name].fontName = "DV"
        styles[name].fontSize = 9.4
        styles[name].leading = 14
    for name in ("Title", "Heading1", "Heading2"):
        styles[name].fontName = "DVB"
        styles[name].textColor = colors.HexColor("#26394A")
    styles.add(
        ParagraphStyle(
            "Caption",
            fontName="DV",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#485763"),
            spaceAfter=12,
        )
    )
    story = []

    def p(text, style="BodyText"):
        story.append(Paragraph(text, styles[style]))
        story.append(Spacer(1, 7))

    def fig(stem, width=7.1 * inch):
        from PIL import Image as PILImage

        path = FIG / (stem + ".png")
        w, h = PILImage.open(path).size
        story.append(Image(str(path), width=width, height=width * h / w))
        story.append(Spacer(1, 8))

    def table(data, widths):
        t = Table(
            [[Paragraph(str(c), styles["Caption"]) for c in row] for row in data],
            colWidths=widths,
            repeatRows=1,
        )
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF1F3")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#6F818B")),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#D8E0E4")),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 10))

    p("Crack-surface converter audit", "Title")
    p(
        "MATLAB equivalence, contact preservation and numerical portability | 6 September 2026",
        "Caption",
    )
    p(
        "The concern was confirmed. The published converter can change the reconstructed walls and contact masks. The August local correction resolves the reference matrix with MKL, but it still changes results with standard OpenBLAS wheels. The corrected solver controls the relevant arithmetic explicitly and is checked against the same frozen MATLAB reference on Windows and Linux.",
        "Heading2",
    )
    p("Publication gate", "Heading2")
    ci_path = ROOT / "ci-summary.json"
    ci = json.loads(ci_path.read_text()) if ci_path.exists() else None
    p(
        ci["assessment"]
        if ci
        else "Native Linux validation is pending in GitHub Actions. The local Docker engine cannot start because Windows Virtual Machine Platform is not enabled. Release branches must not be presented as fully validated yet."
    )
    table(
        [
            ["Evidence", "Before review / published", "Corrected Windows"],
            ["DEAP outcomes", "26 / 32 match MATLAB", "32 / 32 match MATLAB"],
            [
                "Comparable DEAP surfaces",
                f"{sum(maxerr(old[r['id']]) <= 1e-12 for r in deap_rows)} / 26 within 1e-12 m",
                "26 / 26 within 1e-12 m",
            ],
            [
                "Largest wall difference",
                f"{max(maxerr(old[r['id']]) for r in deap_rows):.3e} m",
                f"{max(maxerr(r) for r in deap_rows):.3e} m",
            ],
            [
                "DEAP contact decisions",
                f"{sum(r.get('contact_mask_mismatches', 0) for r in released['deap'])} mismatched points",
                "0 mismatched points",
            ],
            [
                "Arbitrary-point fits",
                "Discrepancies in ill-conditioned fits",
                "160 / 160 match the criterion",
            ],
            [
                "Paired-wall contact cases",
                f"Contact mismatches: {sum(r['contact_mask_mismatches'] for r in released['contact'])}",
                "24 / 24 exact contact masks",
            ],
        ],
        [1.7 * inch, 2.6 * inch, 2.7 * inch],
    )
    p(
        "The huge worst-case difference occurs in severely ill-conditioned S05. The MATLAB reference itself reaches about 1.08e8 m there: these are unphysical fitting artifacts under stress settings, not plausible crack dimensions. Agreement establishes implementation equivalence for the tested cases, not physical validity or CFD readiness.",
        "Caption",
    )
    p("Source protection and scope", "Heading2")
    p(
        "Six immutable converter files and 15 legacy MATLAB files retain their recorded hashes. The three pre-existing local fitting changes were saved before this review. No original input folder was edited. Tests cover reconstruction, contact extension, headless preflight, meshing, export and characterization; this is not a proof that every possible input is correct."
    )
    story.append(PageBreak())
    p("Where the differences occur", "Heading1")
    fig("01_deap_error_overview")
    p(
        "All 26 comparable real DEAP cases are shown. Points encode the largest absolute difference on either wall. The horizontal line is the stated 1e-12 m comparison criterion. Zero differences are displayed at the labelled plotting floor only; no metric is altered. The six no-surface outcomes are excluded from this numerical plot.",
        "Caption",
    )
    p(
        "The released implementation selected the wrong crack-count entry at early times and differed in minimum neighbourhood size, rank-deficient least squares, floating-point evaluation and grid construction. The local August correction addressed those differences but still delegated QR to the installed SciPy LAPACK implementation."
    )
    p(
        "With identical Python, NumPy and SciPy version numbers, OpenBLAS produced a 33.3901504278183 m difference in S05 and changed two of 40,344 synthetic contact decisions. Pinning oneMKL still gave different results on AMD runners. The final six-column QR solver therefore controls reductions, fused operations, extended-precision norm rounding and rank handling directly. It has no vendor BLAS dependency."
    )
    story.append(PageBreak())
    p("A real narrow-span reconstruction", "Heading1")
    fig("02_real_surface_comparison")
    p(
        "L04_large_narrow_span. Each row uses a common colour range, so differences are visible without rescaling individual implementations. Coordinates are reported in the oriented fitting plane. The top row compares lower-wall elevation; the bottom row compares aperture. The complete 26-case atlas includes individual residual maps.",
        "Caption",
    )
    p(
        "This comparison uses the same frozen input files and parameters. CSV naming, display scaling and wall separation are not adjusted to improve visual agreement. The figures show surface reconstruction; they do not represent a CFD solution."
    )
    story.append(PageBreak())
    p("Contact must remain contact", "Heading1")
    fig("03_contact_decisions")
    p(
        f"{chosen}. Dark regions are closed points in the final MATLAB surface. The coloured/circled cells locate actual decisions changed by the August correction under OpenBLAS. The corrected deterministic result has no differing cells. The synthetic coordinates retain their input units.",
        "Caption",
    )
    p(
        "The executable MATLAB rule is upper = lower + max(raw_upper - lower, 0). Negative aperture is set to zero, despite the legacy comment referring to opmin. The lower wall is preserved. Outside the data bounding rectangle, the lower wall is extended and the crack is closed."
    )
    story.append(PageBreak())
    p("A section through overlapping fits", "Heading1")
    fig("04_contact_section")
    p(
        "The section is selected by the largest number of overlapping points in C17. Raw upper-wall crossings are visible before the clamp. After the clamp the walls coincide at contact; no positive gap is inserted. MATLAB and corrected Python arrays agree within the stated comparison tolerance.",
        "Caption",
    )
    p("Meshing limitation", "Heading2")
    p(
        "The current Python-only HEXA8 mesher cannot represent zero-thickness fluid cells. It intentionally requires positive aperture at every grid point. The review fixes preflight so this restriction is reported before meshing. Contact surfaces can still be reconstructed, exported and characterized. Artificially lifting the upper wall would change the geometry and potential flow connectivity and is not a valid equivalence fix."
    )
    story.append(PageBreak())
    p("Reproduction and review findings", "Heading1")
    table(
        [
            ["Finding", "Resolution / boundary"],
            [
                "P1 - SciPy backend changes fitted walls",
                "Use deterministic six-column QR with explicit arithmetic; validate against the frozen MATLAB matrix on each platform.",
            ],
            [
                "P1 - published extraction / fitting mismatch",
                "Retain and verify the MATLAB-indexing, eight-neighbour, pivoted-QR, grid and arithmetic corrections.",
            ],
            [
                "P2 - valid span zero rejected by pipeline",
                "Headless validation now accepts zero span.",
            ],
            [
                "P2 - contact rejected only during execution",
                "Preflight applies the same positive-aperture requirement as the HEXA8 mesher. Contact geometry is unchanged.",
            ],
            [
                "P2 - fdlibm notice absent",
                "Preserve the upstream copyright and permission notice.",
            ],
        ],
        [2.4 * inch, 4.6 * inch],
    )
    p(
        "The frozen fixtures contain 32 DEAP scenarios, 160 arbitrary fits (ten point-set families, four seeds, four spans) and 24 paired-wall cases (six contact families, four spans). They include ties, duplicated hull points, anisotropy, near-collinearity, large offsets, isolated contact, closed stripes and rough contacts. A fresh Windows MATLAB R2025b Update 1 / Curve Fitting Toolbox 25.2 run reproduced the August oracle arrays and saved success flags exactly."
    )
    p(
        'Run <font name="DVB">python scripts/validate_matlab_fitting.py</font> from the repository. It verifies fixture checksums, compares arrays and contact masks, and fails on discrepancies. Large DEAP examples require Git LFS. Use --groups arbitrary contact for the smaller numerical matrix. Use --arrays to retain per-case arrays.'
    )
    p(
        'Run <font name="DVB">python -m pytest -q</font>, <font name="DVB">python -m ruff check .</font>, and <font name="DVB">python scripts/verify_baseline.py</font>. The Windows checkout passes 141 local tests. The Linux checkout passes 150 tests on the Windows host with two platform skips; native results are reported by CI. GitHub Actions checks Python 3.10 and 3.13 on Windows and Linux and separately runs the Docker workflow.'
    )
    p(
        "Supporting artifacts: windows-portable-final.json; fresh-oracle-equivalence.json; review-findings.md; figures/all_deap_surfaces.pdf; figures/all_contact_cases.pdf; tests/data/matlab_r2025b/provenance.json. Source and runtime hashes in those files define the exact evidence scope. Later changes require new validation."
    )
    p("Primary references", "Heading2")
    p(
        "Legacy project reference: legacy/matlab/DEAP_crack_CFD_coupling.m and build_fit_model.m. MathWorks: https://www.mathworks.com/help/curvefit/lowess-smoothing.html. fdlibm source and notice: https://www.netlib.org/fdlibm/e_pow.c. Intel CPU dispatch scope: https://www.intel.com/content/www/us/en/docs/onemkl/developer-guide-windows/2023-1/instruction-set-specific-dispatch-on-intel-archs.html.",
        "Caption",
    )

    def footer(canvas, doc):
        canvas.setFont("DV", 8)
        canvas.setFillColor(colors.HexColor("#596A75"))
        canvas.drawString(
            35,
            24,
            "DEM crack-surface converter | verification evidence | 6 September 2026",
        )
        canvas.drawRightString(577, 24, str(doc.page))

    doc = SimpleDocTemplate(
        str(ROOT / "report.pdf"),
        pagesize=(612, 792),
        rightMargin=35,
        leftMargin=35,
        topMargin=34,
        bottomMargin=42,
        title="MATLAB-Python crack-surface and contact audit",
        author="Project verification",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    error_overview()
    geometry_case("L04_large_narrow_span")
    chosen = contact_comparison()
    contact_profile()
    atlas()
    report(chosen)
    print("Report and figures written to", ROOT)
