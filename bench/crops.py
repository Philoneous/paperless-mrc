# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bildausschnitte ausgewählter Kategorien nebeneinander: Vorlage, Scan, Varianten (je eine Spalte).

    python crops.py <pages> <dpi> <ziel.png> <kategorie-teil> <pdf>...
"""
import json
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

pages, dpi, target, cat = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
pdfs = [Path(p) for p in sys.argv[5:]]
meta = json.loads((pages / "blocks.json").read_text())
blocks = [b for b in meta["blocks"] if cat in b["cat"]][:2]


def render(pdf):
    with pymupdf.open(pdf) as d:
        pix = d[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


sources = [("Vorlage", Image.open(pages / f"clean_{dpi}.png").convert("RGB")),
           ("Scan", render(pages / f"scan_{dpi}.pdf"))] + [(p.stem, render(p)) for p in pdfs]
crops = []
for name, img in sources:
    parts = []
    for b in blocks:
        x0, y0, x1, y1 = [round(v * dpi / meta["hi"]) for v in b["box"]]
        parts.append(img.crop((x0, y0, min(x1, x0 + round(2.2 * dpi)), y1)))
    w = max(p.width for p in parts)
    col = Image.new("RGB", (w, sum(p.height for p in parts) + 24), "white")
    ImageDraw.Draw(col).text((2, 2), name, fill=(200, 0, 0))
    y = 24
    for p in parts:
        col.paste(p, (0, y))
        y += p.height
    crops.append(col)
sheet = Image.new("RGB", (max(c.width for c in crops), sum(c.height for c in crops)), "white")
y = 0
for c in crops:
    sheet.paste(c, (0, y))
    y += c.height
scale = 2 if dpi == 200 else 1.4
sheet = sheet.resize((round(sheet.width * scale), round(sheet.height * scale)), Image.NEAREST)
sheet.save(target)
print(target, sheet.size)
