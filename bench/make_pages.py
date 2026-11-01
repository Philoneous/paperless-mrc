# SPDX-License-Identifier: AGPL-3.0-or-later
"""Testseiten mit bekanntem Text für die Lesbarkeitsmessung (simulierter Scan).

Jeder Block hat eine Kategorie, Text und Lage (bei 600 dpi gezeichnet, dann auf die Scan-Auflösung verkleinert,
leicht weichgezeichnet, Papierton, Rauschen, JPEG – wie ein typischer Bürokopierer/ADF-Scanner).

    python make_pages.py <ziel> → <ziel>/scan_<dpi>.pdf, <ziel>/blocks.json
"""
import io
import json
import random
import sys
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = "/usr/share/fonts/truetype/dejavu/"
SERIF, SANS, THIN = FONTS + "DejaVuSerif.ttf", FONTS + "DejaVuSans.ttf", FONTS + "DejaVuSans-ExtraLight.ttf"
HI = 600  # Zeichenauflösung
W, H = round(8.27 * HI), round(11.69 * HI)
rng = random.Random(7)
WORDS = ("Vertrag Kunde Leistung Zahlung Konto Frist Antrag Nummer Datum Betrag Anlage Seite Hinweis Auftrag "
         "Lieferung Rechnung Schaden Termin Bescheid Versand Anschrift Telefon Zeitraum Gebühr Beitrag Prüfung "
         "invoice account balance delivery customer payment contract reference period notice amount service").split()


def words(n):
    return " ".join(rng.choice(WORDS) for _ in range(n))


def digits():
    return (f"Nr. {rng.randint(10000, 99999)}-{rng.randint(100, 999)}  "
            f"{rng.randint(1, 9)}.{rng.randint(100, 999)},{rng.randint(10, 99)} EUR  "
            f"{rng.randint(1, 28):02d}.{rng.randint(1, 12):02d}.20{rng.randint(10, 29)}")


def pt(size):
    return round(size * HI / 72)


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    blocks = []
    y = pt(60)
    x0 = pt(60)

    def line(cat, text, size, color=(0, 0, 0), font=SERIF, bg=None):
        nonlocal y
        f = ImageFont.truetype(font, pt(size))
        box = d.textbbox((x0, y), text, font=f)
        pad = pt(3)
        if bg:
            d.rectangle((box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad), fill=bg)
        d.text((x0, y), text, font=f, fill=color)
        blocks.append(dict(cat=cat, text=text, box=[box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad]))
        y = box[3] + pt(size * 0.9)

    for cat, size, color, font, bg in [
        ("Fließtext 11 pt", 11, (20, 20, 20), SERIF, None),
        ("Fließtext 10 pt serifenlos", 10, (20, 20, 20), SANS, None),
        ("Kleingedrucktes 7 pt", 7, (20, 20, 20), SERIF, None),
        ("Kleingedrucktes 6 pt", 6, (20, 20, 20), SANS, None),
        ("Kleingedrucktes 5 pt", 5, (20, 20, 20), SANS, None),
        ("Dünne Schrift 8 pt", 8, (20, 20, 20), THIN, None),
        ("Dunkelgrau 9 pt", 9, (85, 85, 85), SANS, None),
        ("Hellgrau 9 pt", 9, (150, 150, 150), SANS, None),
        ("Sehr hellgrau 9 pt", 9, (185, 185, 185), SANS, None),
        ("Sehr hellgrau 7 pt", 7, (190, 190, 190), SANS, None),
        ("Blau 10 pt", 10, (26, 79, 160), SANS, None),
        ("Rot 10 pt", 10, (192, 57, 43), SANS, None),
        ("Hellblau 8 pt", 8, (111, 168, 220), SANS, None),
        ("Auf Gelb markiert 10 pt", 10, (20, 20, 20), SERIF, (255, 236, 140)),
        ("Auf Hellgrau (Tabellenkopf) 9 pt", 9, (20, 20, 20), SANS, (215, 215, 215)),
        ("Weiß auf Dunkelblau 10 pt", 10, (255, 255, 255), SANS, (31, 58, 104)),
        ("Weiß auf Dunkelblau 7 pt", 7, (255, 255, 255), SANS, (31, 58, 104)),
    ]:
        line(cat, words(7), size, color, font, bg)
        line(cat + " (Ziffern)", digits(), size, color, font, bg)
        y += pt(4)
    # Tabelle mit Haarlinien und ein Stempel (nicht ausgewertet, nur zur Sichtprüfung und Dateigröße)
    for i in range(6):
        d.line((x0, y + i * pt(14), W - x0, y + i * pt(14)), fill=(60, 60, 60), width=max(1, pt(0.4)))
    for j in range(5):
        xx = x0 + j * (W - 2 * x0) // 4
        d.line((xx, y, xx, y + 5 * pt(14)), fill=(60, 60, 60), width=max(1, pt(0.4)))
    stamp = Image.new("RGBA", (pt(170), pt(60)), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.rectangle((0, 0, stamp.width - 1, stamp.height - 1), outline=(200, 30, 40, 200), width=pt(2.5))
    sd.text((pt(12), pt(16)), "EINGEGANGEN", font=ImageFont.truetype(SANS, pt(20)), fill=(200, 30, 40, 200))
    stamp = stamp.rotate(12, expand=True)
    img.paste(stamp, (W - pt(260), y + 5 * pt(14) + pt(20)), stamp)

    for dpi in (200, 300):
        clean = img.resize((round(W * dpi / HI), round(H * dpi / HI)), Image.LANCZOS)
        clean.save(out / f"clean_{dpi}.png")
        scan = clean
        scan = scan.filter(ImageFilter.GaussianBlur(0.7 * dpi / 300))
        a = np.asarray(scan).astype(np.float32)
        a = a * (np.array([0.985, 0.975, 0.955]))  # Papierton
        a += np.random.default_rng(dpi).normal(0, 3.5, a.shape)
        scan = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        buf = io.BytesIO()
        scan.save(buf, "JPEG", quality=85)
        doc = pymupdf.open()
        page = doc.new_page(width=8.27 * 72, height=11.69 * 72)
        page.insert_image(page.rect, stream=buf.getvalue())
        doc.save(out / f"scan_{dpi}.pdf")
    (out / "blocks.json").write_text(json.dumps(dict(hi=HI, blocks=blocks), ensure_ascii=False, indent=1))
    print(len(blocks), "Blöcke")


if __name__ == "__main__":
    main()
