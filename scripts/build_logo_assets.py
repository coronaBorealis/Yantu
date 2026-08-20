"""Build deterministic Yantu web and Windows icon assets from the generated base."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SIZES = (512, 192, 64, 32, 16)


def _font_path() -> Path:
    candidates = (
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        Path(r"C:\Windows\Fonts\Dengb.ttf"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("A Chinese font (Microsoft YaHei or DengXian) is required")


def build(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        base = image.convert("RGBA")
    side = min(base.size)
    left = (base.width - side) // 2
    top = (base.height - side) // 2
    master = base.crop((left, top, left + side, top + side)).resize(
        (1024, 1024), Image.Resampling.LANCZOS
    )

    # The generated artwork intentionally contains no text. Overlaying a local
    # CJK font makes the product name accurate and reproducible on every build.
    draw = ImageDraw.Draw(master)
    font = ImageFont.truetype(str(_font_path()), 330)
    glyph = "研"
    box = draw.textbbox((0, 0), glyph, font=font, stroke_width=3)
    width, height = box[2] - box[0], box[3] - box[1]
    x = (1024 - width) / 2 - box[0]
    y = 370 - height / 2 - box[1]
    draw.text(
        (x, y),
        glyph,
        font=font,
        fill="#07583f",
        stroke_width=5,
        stroke_fill="#f7f1df",
    )

    master.save(output / "logo-master.png", optimize=True)
    rendered: dict[int, Image.Image] = {}
    for size in SIZES:
        icon = master.resize((size, size), Image.Resampling.LANCZOS)
        icon.save(output / f"logo-{size}.png", optimize=True)
        rendered[size] = icon
    rendered[512].save(
        output / "yantu.ico",
        format="ICO",
        sizes=[(size, size) for size in (16, 32, 64, 192, 256)],
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == "__main__":
    main()
