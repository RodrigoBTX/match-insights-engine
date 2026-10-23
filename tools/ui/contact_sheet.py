"""Tile several screenshots into one image so many can be reviewed at once.

    python tools/ui/contact_sheet.py <dir> <out.png> <scale> file1.png file2.png ...

Needs Pillow (pip install pillow). Example: python tools/ui/contact_sheet.py audit sheet.png 0.55 20_stage_m01.png 20_stage_m02.png
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw


def sheet(folder: Path, files: list[str], out: str, scale: float, cols: int = 2) -> Path:
    found = [f for f in files if (folder / f).exists()]
    if not found:
        raise SystemExit("none of the files exist")
    images = [Image.open(folder / f).convert("RGB") for f in found]
    images = [im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS) for im in images]
    w, h = max(i.width for i in images), max(i.height for i in images)
    rows = (len(images) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * w + (cols + 1) * 6, rows * (h + 18) + 6), (30, 30, 30))
    draw = ImageDraw.Draw(canvas)
    for n, (name, im) in enumerate(zip(found, images)):
        x, y = 6 + (n % cols) * (w + 6), 6 + (n // cols) * (h + 18)
        draw.text((x, y), name, fill=(200, 200, 200))
        canvas.paste(im, (x, y + 14))
    path = folder / out
    canvas.save(path)
    return path


if __name__ == "__main__":
    if len(sys.argv) < 5:
        raise SystemExit(__doc__)
    print(sheet(Path(sys.argv[1]), sys.argv[4:], sys.argv[2], float(sys.argv[3])))
