"""Render the documented baseline workflow as a deterministic PNG."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "assets" / "workflow.png"
WIDTH, HEIGHT = 1800, 900


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"]
        if bold
        else ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"]
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def multiline_center(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    lines: list[str],
    title_color: str = "#10233f",
) -> None:
    x1, y1, x2, y2 = box
    title_size = 25
    title_font = font(title_size, bold=True)
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    while title_bbox[2] - title_bbox[0] > (x2 - x1 - 24) and title_size > 17:
        title_size -= 1
        title_font = font(title_size, bold=True)
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
    body_font = font(18)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((x1 + x2 - title_width) / 2, y1 + 27), title, font=title_font, fill=title_color)
    y = y1 + 70
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=body_font)
        line_width = bbox[2] - bbox[0]
        draw.text(((x1 + x2 - line_width) / 2, y), line, font=body_font, fill="#334965")
        y += 25


def node(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    lines: list[str],
    fill: str,
    outline: str,
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=20, fill="#b8c5d8", outline=None)
    draw.rounded_rectangle((x1, y1 - 5, x2, y2 - 5), radius=20, fill=fill, outline=outline, width=3)
    multiline_center(draw, (x1, y1 - 5, x2, y2 - 5), title, lines)


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: str = "#446481",
    dashed: bool = False,
) -> None:
    x1, y1 = start
    x2, y2 = end
    if dashed:
        segments = 12
        for index in range(segments):
            if index % 2:
                continue
            a = index / segments
            b = min((index + 1) / segments, 1)
            draw.line(
                (x1 + (x2 - x1) * a, y1 + (y2 - y1) * a, x1 + (x2 - x1) * b, y1 + (y2 - y1) * b),
                fill=color,
                width=5,
            )
    else:
        draw.line((x1, y1, x2, y2), fill=color, width=5)

    import math

    angle = math.atan2(y2 - y1, x2 - x1)
    length = 18
    spread = 0.58
    points = [
        (x2, y2),
        (x2 - length * math.cos(angle - spread), y2 - length * math.sin(angle - spread)),
        (x2 - length * math.cos(angle + spread), y2 - length * math.sin(angle + spread)),
    ]
    draw.polygon(points, fill=color)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (WIDTH, HEIGHT), "#f4f7fb")
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, WIDTH, 118), fill="#10233f")
    draw.text((55, 26), "Crack geometry to Cast3M mesh", font=font(40, bold=True), fill="white")
    draw.text(
        (56, 78),
        "Current baseline execution path, including the optional FISS flow branch",
        font=font(20),
        fill="#cbd9eb",
    )

    main_y = (305, 465)
    boxes = {
        "csv": (38, *main_y, 278),
        "gui": (330, *main_y, 570),
        "dgibi": (622, *main_y, 862),
        "castem": (914, *main_y, 1154),
        "mesh": (1206, *main_y, 1446),
        "cfd": (1498, *main_y, 1762),
    }
    # Reorder tuple construction from (x1, y1, y2, x2) to normal boxes.
    boxes = {key: (value[0], value[1], value[3], value[2]) for key, value in boxes.items()}

    node(draw, boxes["csv"], "4 CSV matrices", ["xrange · yrange", "zfit_zmin · zfit_zmax"], "#dff3ff", "#4795bd")
    node(draw, boxes["gui"], "Python / Tk GUI", ["paths · parameters", "validation · naming"], "#e5f5ec", "#4c9b70")
    node(draw, boxes["dgibi"], "Patched DGIBI", ["baseline template", "run-specific values"], "#fff1d8", "#c89236")
    node(draw, boxes["castem"], "Cast3M 25", ["geometry processing", "mesh generation"], "#fce7e8", "#bc5b60")
    node(draw, boxes["mesh"], "Mesh outputs", ["volume BDF", "surface BDF files"], "#eae7fb", "#7767b7")
    node(draw, boxes["cfd"], "Combined NASTRAN BDF", ["volume + named surfaces", "for downstream CFD import"], "#dceef7", "#3d82a2")

    for left, right in [("csv", "gui"), ("gui", "dgibi"), ("dgibi", "castem"), ("castem", "mesh"), ("mesh", "cfd")]:
        lbox = boxes[left]
        rbox = boxes[right]
        arrow(draw, (lbox[2] + 8, (lbox[1] + lbox[3]) // 2 - 3), (rbox[0] - 10, (rbox[1] + rbox[3]) // 2 - 3))

    template_box = (330, 145, 570, 270)
    node(
        draw,
        template_box,
        "Source templates",
        ["castem_tool.dgibi", "fuite_fissure.dgibi"],
        "#edf1f6",
        "#7890aa",
    )
    arrow(draw, (450, 275), (450, 295), color="#7890aa")

    fiss_boxes = {
        "setup": (622, 630, 862, 782),
        "operator": (914, 630, 1154, 782),
        "results": (1206, 630, 1446, 782),
    }
    node(draw, fiss_boxes["setup"], "Optional FISS setup", ["model · gas · BCs", "pressure / temperature"], "#fff1d8", "#c89236")
    node(draw, fiss_boxes["operator"], "Cast3M FISS", ["flow calculation", "along crack lines"], "#fce7e8", "#bc5b60")
    node(draw, fiss_boxes["results"], "Flow results", ["profiles · totals", "optional post-processing"], "#e5f5ec", "#4c9b70")
    arrow(draw, (450, 475), (612, 692), color="#71879e", dashed=True)
    arrow(draw, (870, 703), (904, 703), color="#71879e", dashed=True)
    arrow(draw, (1162, 703), (1196, 703), color="#71879e", dashed=True)

    draw.text((56, 838), "Solid path: mesh conversion", font=font(18, bold=True), fill="#446481")
    draw.text((340, 838), "Dashed path: optional FISS flow calculation", font=font(18), fill="#71879e")
    draw.text((1420, 838), "Pre-refactor baseline", font=font(18, bold=True), fill="#566b82")

    image.save(OUTPUT, optimize=True)
    print(f"Wrote {OUTPUT} ({WIDTH}x{HEIGHT}, {OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
