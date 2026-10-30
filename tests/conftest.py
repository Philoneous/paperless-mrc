# SPDX-License-Identifier: AGPL-3.0-or-later
"""Erzeugt synthetische, scannerähnliche Test-PDFs (Papierton, Rauschen, Logo, Text)."""

import io

import numpy as np
import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DPI = 200
A4_PX = (round(8.27 * DPI), round(11.69 * DPI))
A4_PT = (595.28, 841.89)

LETTER = [
    "Stadtwerke Musterstadt GmbH",
    "Jahresabrechnung 2025 für Wasser und Wärme",
    "Sehr geehrte Damen und Herren,",
    "wir bestätigen den Eingang Ihrer Unterlagen und teilen",
    "Ihnen mit, dass die Prüfung abgeschlossen ist. Der Betrag",
    "von 1.284,50 EUR wird zum 1. Dezember 2026 fällig.",
    "Bitte überweisen Sie den Betrag fristgerecht.",
    "Mit freundlichen Grüßen",
]


def paper(rng: np.random.Generator) -> Image.Image:
    base = np.ones((A4_PX[1], A4_PX[0], 3)) * np.array([248, 246, 240]) + rng.normal(0, 3, (A4_PX[1], A4_PX[0], 1))
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))


def letter_page(rng: np.random.Generator, lines=LETTER) -> Image.Image:
    img = paper(rng)
    d = ImageDraw.Draw(img)
    d.ellipse((130, 110, 290, 270), fill=(0, 102, 179))  # farbiges Logo
    d.rectangle((175, 155, 245, 225), fill=(255, 196, 0))
    font = ImageFont.truetype(FONT, 34)
    for i, line in enumerate(lines):
        d.text((130, 420 + i * 70), line, font=font, fill=(25, 25, 25))
    return img


def page_number_only(rng: np.random.Generator) -> Image.Image:
    img = paper(rng)
    ImageDraw.Draw(img).text((A4_PX[0] - 420, A4_PX[1] - 160), "Seite 3 von 3",
                             font=ImageFont.truetype(FONT, 26), fill=(30, 30, 30))
    return img


def blank_back(rng: np.random.Generator) -> Image.Image:
    """Leere Rückseite mit Papierrauschen und schwach durchscheinendem Text."""
    img = np.asarray(paper(rng)).astype(np.float32)
    ghost = letter_page(rng).convert("L").transpose(Image.FLIP_LEFT_RIGHT)
    ink = 1 - np.asarray(ghost, np.float32) / 255
    return Image.fromarray(np.clip(img - ink[..., None] * 12, 0, 255).astype(np.uint8))


def photo_page(rng: np.random.Generator) -> Image.Image:
    """Fotoähnliche Seite: weiche Farbverläufe und Zwischentöne über die ganze Fläche."""
    y, x = np.mgrid[0:A4_PX[1], 0:A4_PX[0]].astype(np.float32)
    r = 120 + 70 * np.sin(x / 150) * np.cos(y / 210)
    g = 110 + 60 * np.cos(x / 260 + y / 330)
    b = 90 + 50 * np.sin(y / 120)
    img = np.stack([r, g, b], axis=2) + rng.normal(0, 6, (A4_PX[1], A4_PX[0], 1))
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def insurance_page(rng: np.random.Generator, halftone: bool = False) -> Image.Image:
    """Dokument mit grau und farbig hinterlegten Textblöcken (wie Versicherungsscheine), optional im Druckraster."""
    img = letter_page(rng)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 32)
    fills = [(200, 200, 200), (190, 215, 240), (250, 225, 180)]
    for k, (y0, y1) in enumerate([(380, 700), (760, 1100), (1150, 1500), (1550, 2200)]):
        d.rectangle((90, y0, 1560, y1), fill=fills[k % 3])
        for j in range(5):
            d.text((130, y0 + 30 + j * 55), f"Versicherungsnummer {k}{j} Beitrag 12,{j}0 EUR", font=font,
                   fill=(20, 20, 20))
    a = np.asarray(img).astype(np.float32)
    if halftone:
        yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
        dots = ((np.sin(xx * 2.2) * np.sin(yy * 2.2)) > 0.2)[..., None]  # Raster ca. 100 lpi bei 200 dpi
        tinted = a.mean(axis=2, keepdims=True) < 245
        a = np.where(tinted & dots, a * 0.9, np.where(tinted, np.minimum(a * 1.05, 255), a))
    return Image.fromarray(np.clip(a + rng.normal(0, 3, a.shape[:2])[..., None], 0, 255).astype(np.uint8))


def wall_photo(rng: np.random.Generator) -> Image.Image:
    """Foto einer fast einfarbigen Wand: weicher Helligkeitsverlauf, kein Text, kein Papierweiß."""
    y, x = np.mgrid[0:A4_PX[1], 0:A4_PX[0]].astype(np.float32)
    v = 150 + 40 * (x / A4_PX[0]) - 30 * (y / A4_PX[1])
    a = np.stack([v, v * 0.95, v * 0.85], axis=2) + rng.normal(0, 4, (A4_PX[1], A4_PX[0], 1))
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def add_vector_scan_page(doc: pymupdf.Document, img: Image.Image) -> None:
    """Hängt eine Seite an, die das Bild als viele kleine Rechtecke enthält (vektorisierter Scan)."""
    page = doc.new_page(width=A4_PT[0], height=A4_PT[1])
    dark = np.asarray(img.convert("L")) < 128
    f = A4_PT[0] / dark.shape[1]
    shape = page.new_shape()
    for row, line in enumerate(dark):
        edges = np.flatnonzero(np.diff(np.concatenate([[0], line.astype(np.int8), [0]])))
        for start, stop in zip(edges[::2], edges[1::2]):
            shape.draw_rect(pymupdf.Rect(start * f, row * f, stop * f, (row + 1) * f))
            shape.finish(color=None, fill=(0, 0, 0))  # ein Pfad je Element, wie bei Vektorisierern
    shape.commit()


def write_scan_pdf(path, images, page_size=A4_PT, invisible_text=None):
    """Jede Seite = ein JPEG-Seitenbild; optional unsichtbare Textebene (render_mode 3)."""
    doc = pymupdf.open()
    for n, img in enumerate(images):
        w, h = (page_size[1], page_size[0]) if img.width > img.height else page_size
        page = doc.new_page(width=w, height=h)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=92, dpi=(DPI, DPI))
        page.insert_image(page.rect, stream=buf.getvalue())
        if invisible_text and invisible_text[n]:
            page.insert_text((60, 200), invisible_text[n], fontsize=12, render_mode=3)
    doc.save(path)
    return path


@pytest.fixture
def rng():
    return np.random.default_rng(7)
