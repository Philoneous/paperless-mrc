# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drucktestsatz: eine Vorlage zum Ausdrucken und erneuten Einscannen (echte Scans statt simulierter).

So wenige Seiten wie möglich: jede Seite prüft einen eigenen Zweig der Verarbeitung (Dokument, leer, Foto, Drehung,
Begradigung); unabhängige Prüfungen teilen sich eine Seite (z. B. Drehung und Begradigung). Das Soll-Ergebnis steht in
faelle.md / expected.json und folgt den Standardwerten von paperless-mrc.

    python make_printset.py <ziel>   → <ziel>/testseiten.pdf, faelle.md, expected.json

Benötigt reportlab, numpy, opencv, scikit-image (Fotos, CC0/gemeinfrei) und die DejaVu-Schriften.
Ausgabe ist reproduzierbar (feste Zufallszahlen), nicht byte-identisch (PDF-Zeitstempel).
"""
import io
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import skimage.data
from PIL import Image, ImageDraw, ImageFilter
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

W, H = A4
FONTS = "/usr/share/fonts/truetype/dejavu/"
for name, file in [("Serif", "DejaVuSerif.ttf"), ("Sans", "DejaVuSans.ttf"), ("Bold", "DejaVuSans-Bold.ttf"),
                   ("Thin", "DejaVuSans-ExtraLight.ttf"), ("Mono", "DejaVuSansMono.ttf")]:
    pdfmetrics.registerFont(TTFont(name, FONTS + file))

DE = [
    "vielen Dank für Ihre Anfrage vom 14. Oktober. Gerne bestätigen wir die Übernahme der Wartungsarbeiten an der "
    "Heizungsanlage in Ihrem Objekt. Die Arbeiten umfassen die Prüfung des Brenners, die Reinigung des "
    "Wärmetauschers sowie die Messung der Abgaswerte; das Protokoll erhalten Sie im Anschluss per Post.",
    "Für die Durchführung benötigen wir am vereinbarten Termin Zugang zum Heizungsraum und zum Zählerschrank. "
    "Bitte sorgen Sie dafür, dass der Bereich vor der Anlage auf einer Breite von mindestens einem Meter frei ist. "
    "Sollte der Termin nicht passen, genügt eine kurze Nachricht bis spätestens zwei Werktage vorher.",
    "Die Kosten richten sich nach dem beigefügten Angebot Nr. 2026-0815. Zusätzliche Ersatzteile werden nur nach "
    "Rücksprache eingebaut und gesondert berechnet. Die Rechnung ist innerhalb von vierzehn Tagen ohne Abzug "
    "zahlbar; bei Zahlung innerhalb von sieben Tagen gewähren wir zwei Prozent Skonto.",
    "Bitte beachten Sie, dass die gesetzliche Gewährleistung für Arbeitsleistungen zwei Jahre beträgt. Mängel "
    "zeigen Sie uns bitte schriftlich an. Unsere Allgemeinen Geschäftsbedingungen finden Sie auf der Rückseite "
    "des Angebots; abweichende Vereinbarungen bedürfen der Schriftform.",
    "Für Rückfragen steht Ihnen unser Kundendienst montags bis freitags zwischen acht und siebzehn Uhr zur "
    "Verfügung. Halten Sie dafür bitte Ihre Kundennummer bereit. Außerhalb dieser Zeiten erreichen Sie in "
    "dringenden Fällen unseren Notdienst unter der auf der Rechnung angegebenen Nummer.",
    "Wir weisen darauf hin, dass die nächste Überprüfung der Anlage in zwölf Monaten fällig wird. Auf Wunsch "
    "erinnern wir Sie rechtzeitig daran. Größere Schäden, etwa an Leitungen oder am Schornstein, gehören nicht "
    "zum Leistungsumfang und werden vorab mit Ihnen abgestimmt.",
]
EN = [
    "This agreement sets out the terms under which the supplier provides maintenance services for the equipment "
    "listed in the schedule. Services are performed during normal business hours unless the parties agree "
    "otherwise in writing. Each visit is documented in a short report signed by both parties.",
    "The customer shall grant reasonable access to the premises and provide a contact person on site. Delays "
    "caused by missing access may be charged at the hourly rate stated in the price list. Spare parts are "
    "invoiced separately and remain the property of the supplier until paid in full.",
    "Either party may terminate this agreement with three months' notice to the end of a calendar quarter. "
    "Termination for cause remains unaffected. Notices must be given in writing; electronic mail is sufficient "
    "if receipt is confirmed by the other party within five working days.",
    "Liability for slight negligence is limited to foreseeable damage typical for this type of contract. This "
    "limitation does not apply to injury to life, body or health. The supplier maintains liability insurance "
    "with a minimum coverage of two million euros per claim and year.",
]
WORDS = ("Vertrag Kunde Leistung Zahlung Konto Frist Antrag Nummer Datum Betrag Anlage Seite Hinweis Auftrag "
         "Lieferung Rechnung Schaden Termin Bescheid Versand Anschrift Telefon Zeitraum Gebühr Beitrag Prüfung "
         "invoice account balance delivery customer payment contract reference period notice amount service").split()

CASES: list[dict] = []  # Reihenfolge = Seitenreihenfolge


def case(title, expect, purpose, hand=""):
    """Registriert die nächste Seite: expect = Soll-Ergebnis, purpose = was sie prüft, hand = was der Nutzer vor dem
    Scannen von Hand tut."""
    def deco(fn):
        CASES.append(dict(page=len(CASES) + 1, title=title, expect=expect, purpose=purpose, hand=hand, fn=fn))
        return fn
    return deco


# ----------------------------------------------------------------------------- Zeichenhilfen

def par(c, text, x, y, width, font="Serif", size=11, leading=None, color=(0, 0, 0)):
    """Absatz ab Oberkante y; Rückgabe: Oberkante des nächsten Absatzes."""
    leading = leading or size * 1.35
    c.setFont(font, size)
    c.setFillColorRGB(*color)
    for line in simpleSplit(text, font, size, width):
        y -= leading
        c.drawString(x, y, line)
    return y - leading * 0.6


def body(c, x, y, width, paragraphs, size=11, font="Serif", bottom=25 * mm):
    for p in paragraphs:
        if y < bottom:
            break
        y = par(c, p, x, y, width, font, size)
    return y


def logo(c, x, y, s=1.0):
    """Einfaches Firmenzeichen (Kreis mit Blatt) und Name."""
    c.setFillColorRGB(0.13, 0.42, 0.29)
    c.circle(x + 9 * s * mm, y + 9 * s * mm, 9 * s * mm, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    p = c.beginPath()
    p.moveTo(x + 4 * s * mm, y + 5 * s * mm)
    p.curveTo(x + 5 * s * mm, y + 15 * s * mm, x + 13 * s * mm, y + 15 * s * mm, x + 14 * s * mm, y + 14 * s * mm)
    p.curveTo(x + 14 * s * mm, y + 7 * s * mm, x + 8 * s * mm, y + 4 * s * mm, x + 4 * s * mm, y + 5 * s * mm)
    c.drawPath(p, stroke=0, fill=1)
    c.setFillColorRGB(0.13, 0.42, 0.29)
    c.setFont("Bold", 16 * s)
    c.drawString(x + 22 * s * mm, y + 7 * s * mm, "Musterwerk Beispiel GmbH")
    c.setFont("Sans", 8 * s)
    c.drawString(x + 22 * s * mm, y + 2.5 * s * mm, "Heizung · Sanitär · Wartung")


def stamp(c, x, y, angle=12, text="EINGEGANGEN", date="03. NOV. 2026"):
    c.saveState()
    c.translate(x, y)
    c.rotate(angle)
    c.setStrokeColorRGB(0.78, 0.12, 0.16)
    c.setFillColorRGB(0.78, 0.12, 0.16)
    c.setLineWidth(2)
    c.roundRect(0, 0, 62 * mm, 20 * mm, 2 * mm)
    c.setFont("Bold", 15)
    c.drawCentredString(31 * mm, 11 * mm, text)
    c.setFont("Sans", 10)
    c.drawCentredString(31 * mm, 4 * mm, date)
    c.restoreState()


def signature(c, x, y, color=(0.1, 0.2, 0.6)):
    """Gedruckter Unterschriftszug (Bézierkurven)."""
    c.setStrokeColorRGB(*color)
    c.setLineWidth(1.1)
    p = c.beginPath()
    p.moveTo(x, y)
    pts = [(8, 14, 12, -6, 18, 6), (22, 14, 26, -2, 30, 4), (33, 9, 36, -4, 42, 3), (48, 10, 50, 0, 56, 2),
           (60, 4, 64, -3, 70, 5)]
    for a, b, c2, d, e, f in pts:
        p.curveTo(x + a * mm / 2.5, y + b * mm / 2.5, x + c2 * mm / 2.5, y + d * mm / 2.5, x + e * mm / 2.5,
                  y + f * mm / 2.5)
    c.drawPath(p, stroke=1, fill=0)
    c.line(x + 4 * mm, y - 2 * mm, x + 26 * mm, y - 1.5 * mm)


def page_number(c, n):
    c.setFont("Sans", 10)
    c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(W / 2, 15 * mm, f"– {n} –")


def rotated(c, angle, fn):
    """fn(c) um den Seitenmittelpunkt gedreht zeichnen (Grad, gegen den Uhrzeigersinn)."""
    c.saveState()
    c.translate(W / 2, H / 2)
    c.rotate(angle)
    c.translate(-W / 2, -H / 2)
    fn(c)
    c.restoreState()


def image(c, img, x, y, w, h, quality=90):
    """PIL-Bild als JPEG einbetten (x, y = linke untere Ecke)."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    buf.seek(0)
    c.drawImage(ImageReader(buf), x, y, w, h)


def letter_head(c, subject):
    """Briefkopf nach DIN 5008 (Form B): Logo, Rücksendeangabe, Anschrift, Infoblock, Betreff."""
    logo(c, 20 * mm, H - 30 * mm)
    c.setFont("Sans", 7)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawString(25 * mm, H - 50 * mm, "Musterwerk Beispiel GmbH · Industriestraße 12 · 12345 Musterstadt")
    c.setFillColorRGB(0, 0, 0)
    y = H - 56 * mm
    for line in ["Frau", "Erika Mustermann", "Beispielweg 7", "54321 Musterdorf"]:
        c.setFont("Serif", 11)
        c.drawString(25 * mm, y, line)
        y -= 5 * mm
    info = [("Ihr Zeichen", "EM/10-26"), ("Unser Zeichen", "W-2026-0815"), ("Telefon", "0123 456789-0"),
            ("Datum", "01.11.2026")]
    yy = H - 56 * mm
    for k, v in info:
        c.setFont("Sans", 8)
        c.drawString(125 * mm, yy, k)
        c.setFont("Sans", 9)
        c.drawString(155 * mm, yy, v)
        yy -= 5 * mm
    c.setFont("Bold", 11)
    c.drawString(25 * mm, H - 103 * mm, subject)


def letter_foot(c):
    """Fußzeile in 7 pt."""
    c.setFont("Sans", 7)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    for i, line in enumerate(["Musterwerk Beispiel GmbH · Sitz Musterstadt · Amtsgericht Musterstadt HRB 0000 · "
                              "Geschäftsführer: Max Beispiel",
                              "Bankverbindung: Musterbank · IBAN DE00 1234 5678 9012 3456 78 · BIC MUSTDEXXXXX · "
                              "USt-IdNr. DE000000000"]):
        c.drawString(25 * mm, 18 * mm - i * 3.5 * mm, line)
    c.setFillColorRGB(0, 0, 0)


def letter(c):
    """Vollständiger Geschäftsbrief (Text, Gruß, gedruckte Unterschrift, Fußzeile)."""
    letter_head(c, "Wartung Ihrer Heizungsanlage – Auftragsbestätigung")
    y = par(c, "Sehr geehrte Frau Mustermann,", 25 * mm, H - 108 * mm, 165 * mm)
    y = body(c, 25 * mm, y, 165 * mm, DE[:3], bottom=60 * mm)
    y = par(c, "Mit freundlichen Grüßen", 25 * mm, y, 165 * mm)
    signature(c, 27 * mm, y - 12 * mm)
    c.setFont("Serif", 11)
    c.drawString(25 * mm, y - 22 * mm, "Max Beispiel, Kundendienst")
    letter_foot(c)


# ----------------------------------------------------------------------------- Bilder (Fotos)

def fractal(h, w, rng, octaves=6, base=3, persistence=0.55):
    out = np.zeros((h, w), np.float32)
    amp = 1.0
    for o in range(octaves):
        gh = base * 2 ** o
        gw = max(2, round(gh * w / h))
        out += amp * cv2.resize(rng.random((gh, gw)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
        amp *= persistence
    out -= out.min()
    return out / out.max()


def photo_wall(w=2400, h=3400, seed=1, shade=False):
    """Kontrastarmes Foto einer verputzten Wand mit Wasserfleck und Haarriss (wie Schadensfotos).
    shade: Wand im Schatten, unscharf, ohne Riss – Helligkeitsverlauf statt Papierton, kaum Kanten."""
    rng = np.random.default_rng(seed)
    tone = 0.86 + 0.08 * fractal(h, w, rng) + 0.02 * rng.standard_normal((h, w)).astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    light = 0.9 + 0.12 * (xx / w) - 0.05 * (yy / h)
    if shade:
        light = 0.45 + 0.45 * (xx / w) + 0.08 * (yy / h)
    r = np.hypot((xx - 0.55 * w) / (0.28 * w), (yy - 0.45 * h) / (0.22 * h))
    edge = 1 + 0.3 * (fractal(h, w, rng, octaves=4, base=4) - 0.5)
    stain = np.clip((edge - r) * 4, 0, 1)
    ring = np.exp(-((r - edge) / 0.03) ** 2)
    rgb = np.stack([np.full((h, w), 224.0), np.full((h, w), 214.0), np.full((h, w), 196.0)], -1)
    rgb *= (tone * light)[..., None]
    rgb -= (stain * 0.10 + ring * 0.07)[..., None] * np.array([40.0, 60.0, 90.0])
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    if shade:
        # Rand weich zu Weiß auslaufen lassen: eine harte Bildkante zum unbedruckten Druckrand zählte sonst als Tinte
        # (Drucker drucken nicht randlos, Handyfotos haben keinen Rand)
        img = np.asarray(img.filter(ImageFilter.GaussianBlur(8)), np.float32)
        fade = np.clip(np.minimum.reduce([xx, w - xx, yy, h - yy]) / (0.12 * w), 0, 1)[..., None]
        return Image.fromarray((img * fade + 255 * (1 - fade)).astype(np.uint8))
    d = ImageDraw.Draw(img)
    x, y = 0.3 * w, 0.15 * h
    pts = [(x, y)]
    for _ in range(60):
        x += rng.normal(4, 12)
        y += abs(rng.normal(25, 8))
        pts.append((x, y))
    d.line(pts, fill=(150, 140, 125), width=3)
    return img.filter(ImageFilter.GaussianBlur(1.2))


def photo_landscape(w=2400, h=800, seed=4):
    """Detailreiches Landschaftsfoto (Himmel, Wolken, Hügel, Wiese) – synthetisch."""
    rng = np.random.default_rng(seed)
    yy = np.mgrid[0:h, 0:w][0].astype(np.float32) / h
    sky = np.stack([110 + 90 * yy, 160 + 60 * yy, 230 + 15 * yy], -1)
    clouds = np.clip((fractal(h, w, rng, octaves=7) - 0.55) * 3, 0, 1)[..., None]
    img = sky * (1 - clouds) + 245 * clouds
    for i, (base, amp, col) in enumerate([(0.42, 0.10, (70, 110, 80)), (0.55, 0.08, (60, 120, 50)),
                                          (0.68, 0.05, (90, 140, 40))]):
        prof = fractal(1, w, rng, octaves=7, base=2)[0]
        top = (base + amp * (prof - 0.5)) * h
        mask = yy * h > top[None, :]
        tex = 0.75 + 0.5 * fractal(h, w, rng, octaves=7, base=8)
        img = np.where(mask[..., None], np.array(col, np.float32) * tex[..., None], img)
    img += rng.normal(0, 4, img.shape)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def image_fit(c, img, x, y, w, h):
    """Bild unverzerrt in das Feld einpassen (zentriert)."""
    scale = min(w / img.width, h / img.height)
    iw, ih = img.width * scale, img.height * scale
    image(c, img, x + (w - iw) / 2, y + (h - ih) / 2, iw, ih)


def real_photo(name, w):
    """CC0-/gemeinfreie Fotos aus scikit-image, auf Druckbreite hochskaliert (weich wie ein Handyfoto)."""
    a = getattr(skimage.data, name)()
    img = Image.fromarray(a)
    return img.resize((w, round(w * img.height / img.width)), Image.LANCZOS)


# ----------------------------------------------------------------------------- Lesbarkeitstafel, Querformat-Formular

def readability_chart(c):
    """Lesbarkeitstafel wie bench/make_pages.py; Rückgabe: Unterkante."""
    rng = random.Random(7)
    x, y = 18 * mm, H - 18 * mm
    for label, size, color, font, bg in [
        ("Fließtext 11 pt", 11, (20, 20, 20), "Serif", None), ("Serifenlos 10 pt", 10, (20, 20, 20), "Sans", None),
        ("7 pt", 7, (20, 20, 20), "Serif", None), ("6 pt", 6, (20, 20, 20), "Sans", None),
        ("5 pt", 5, (20, 20, 20), "Sans", None), ("Dünn 8 pt", 8, (20, 20, 20), "Thin", None),
        ("Dunkelgrau 9 pt", 9, (85, 85, 85), "Sans", None), ("Hellgrau 9 pt", 9, (150, 150, 150), "Sans", None),
        ("Sehr hellgrau 9 pt", 9, (185, 185, 185), "Sans", None),
        ("Sehr hellgrau 7 pt", 7, (190, 190, 190), "Sans", None), ("Blau 10 pt", 10, (26, 79, 160), "Sans", None),
        ("Rot 10 pt", 10, (192, 57, 43), "Sans", None), ("Hellblau 8 pt", 8, (111, 168, 220), "Sans", None),
        ("Auf Gelb 10 pt", 10, (20, 20, 20), "Serif", (255, 236, 140)),
        ("Auf Hellgrau 9 pt", 9, (20, 20, 20), "Sans", (215, 215, 215)),
        ("Weiß auf Dunkelblau 10 pt", 10, (255, 255, 255), "Sans", (31, 58, 104)),
        ("Weiß auf Dunkelblau 7 pt", 7, (255, 255, 255), "Sans", (31, 58, 104)),
    ]:
        for text in (" ".join(rng.choice(WORDS) for _ in range(7)),
                     f"Nr. {rng.randint(10000, 99999)}-{rng.randint(100, 999)}  {rng.randint(1, 9)}."
                     f"{rng.randint(100, 999)},{rng.randint(10, 99)} EUR  {rng.randint(1, 28):02d}."
                     f"{rng.randint(1, 12):02d}.20{rng.randint(10, 29)}"):
            y -= size * 1.5
            if bg:
                c.setFillColorRGB(*(v / 255 for v in bg))
                c.rect(x - 2, y - size * 0.3, pdfmetrics.stringWidth(text, font, size) + 4, size * 1.3, 0, 1)
            c.setFillColorRGB(*(v / 255 for v in color))
            c.setFont(font, size)
            c.drawString(x, y, text)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.setFont("Sans", 5.5)
        c.drawRightString(W - 15 * mm, y, label)
        y -= 3
    y -= 8 * mm
    for i, width in enumerate([0.1, 0.25, 0.5, 1.0]):  # Haarlinien
        c.setLineWidth(width)
        c.setStrokeColorRGB(0, 0, 0)
        c.line(x, y - i * 3 * mm, x + 80 * mm, y - i * 3 * mm)
    for i in range(11):  # Graukeil 0–100 %
        c.setFillColorRGB(1 - i / 10, 1 - i / 10, 1 - i / 10)
        c.rect(x + 95 * mm + i * 7 * mm, y - 10 * mm, 7 * mm, 10 * mm, 0, 1)
    for i, col in enumerate([(1, 0, 0), (0, 0.6, 0), (0, 0, 1), (0, 1, 1), (1, 0, 1), (1, 1, 0)]):
        c.setFillColorRGB(*col)
        c.rect(x + 95 * mm + i * 12.8 * mm, y - 22 * mm, 12.8 * mm, 10 * mm, 0, 1)
    c.setStrokeColorRGB(0, 0, 0)
    return y - 22 * mm


def landscape_form(c):
    """Querformat-Formular (kleine Schrift, Tabelle, Wasserzeichen) auf eine Hochformatseite gezeichnet."""
    c.saveState()
    c.translate(W, 0)
    c.rotate(90)  # Koordinaten jetzt Querformat: Breite H, Höhe W
    c.setFillColorRGB(0.88, 0.88, 0.88)
    c.setFont("Bold", 110)
    c.saveState()
    c.translate(H / 2, W / 2)
    c.rotate(20)
    c.drawCentredString(0, -30, "MUSTER")
    c.restoreState()
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Bold", 12)
    c.drawString(15 * mm, W - 18 * mm, "Jahresübersicht Zählerstände und Verbrauch 2026")
    rng = random.Random(5)
    months = "Jan Feb Mär Apr Mai Jun Jul Aug Sep Okt Nov Dez".split()
    x0, y0, cw, rh = 15 * mm, W - 28 * mm, 19 * mm, 6 * mm
    c.setLineWidth(0.3)
    c.setFont("Bold", 7)
    for j, m in enumerate(["Zähler"] + months + ["Summe"]):
        c.drawString(x0 + j * cw + 1 * mm, y0 - 4 * mm, m)
    c.setFont("Sans", 7)
    for i in range(24):
        y = y0 - (i + 1) * rh
        c.drawString(x0 + 1 * mm, y - 4 * mm, f"Z-{rng.randint(1000, 9999)}")
        for j in range(12):
            c.drawRightString(x0 + (j + 2) * cw - 1 * mm, y - 4 * mm, f"{rng.randint(100, 9999):,}".replace(",", "."))
        c.drawRightString(x0 + 14 * cw - 1 * mm, y - 4 * mm, f"{rng.randint(10000, 99999):,}".replace(",", "."))
    for i in range(26):
        c.line(x0, y0 - i * rh, x0 + 14 * cw, y0 - i * rh)
    for j in range(15):
        c.line(x0 + j * cw, y0, x0 + j * cw, y0 - 25 * rh)
    c.restoreState()


# ----------------------------------------------------------------------------- Seiten

DOC = "komprimiert (MRC), keine Drehung, keine Begradigung"
PHOTO = "Foto → Seite unverändert"


@case("Brief mit Foto und Handschrift", DOC + "; Handschrift (auch Bleistift, Textmarker, Rotstift) lesbar, Foto "
      "im Hintergrund ohne störende Artefakte", "Normaler Brief, Mischseite mit Foto (Papier ≥ 50 %), echte "
      "Handschrift, 7-pt-Fußzeile, senkrechter Randvermerk darf keine Drehung auslösen.",
      "Felder A–E wie auf dem Blatt beschrieben ausfüllen.")
def p_letter_form(c):
    letter_head(c, "Wartungsbericht und Auftragsbestätigung")
    y = par(c, "Sehr geehrte Frau Mustermann,", 25 * mm, H - 108 * mm, 165 * mm, size=10.5)
    y = par(c, DE[0], 25 * mm, y, 165 * mm, size=10.5)
    image(c, photo_landscape(), 25 * mm, y - 52 * mm, 165 * mm, 50 * mm)
    c.setFont("Sans", 7)
    c.drawString(25 * mm, y - 56 * mm, "Abb.: Außenanlage nach der Wartung")
    y -= 66 * mm
    c.setFont("Bold", 9)
    c.drawString(25 * mm, y, "Von Hand ausfüllen:")
    c.setLineWidth(0.4)
    for label in ["A  Name (Kugelschreiber blau)", "B  Bemerkung (Bleistift, ganz leicht)"]:
        y -= 11 * mm
        c.setFont("Sans", 9)
        c.drawString(25 * mm, y + 5 * mm, label)
        c.setStrokeColorRGB(0.5, 0.5, 0.5)
        c.line(25 * mm, y, 190 * mm, y)
    c.setStrokeColorRGB(0, 0, 0)
    y -= 7 * mm
    c.drawString(25 * mm, y, "C  Diesen Satz mit gelbem Textmarker markieren:")
    c.setFont("Serif", 11)
    c.drawString(25 * mm, y - 6 * mm, "Die Anlage wurde geprüft und ist betriebsbereit.")
    y -= 15 * mm
    c.setFont("Sans", 9)
    c.drawString(25 * mm, y, "D  Betrag mit Rotstift durchstreichen und 145,80 € darüber schreiben:")
    c.setFont("Serif", 12)
    c.drawString(25 * mm, y - 9 * mm, "Betrag: 128,40 €")
    y -= 22 * mm
    c.setFont("Sans", 9)
    c.drawString(25 * mm, y + 5 * mm, "E  Unterschrift (Kugelschreiber blau)")
    c.line(25 * mm, y - 6 * mm, 100 * mm, y - 6 * mm)
    c.saveState()
    c.translate(13 * mm, 110 * mm)
    c.rotate(90)
    c.setFont("Sans", 7)
    c.drawString(0, 0, "Formular WP-7 · Stand 01/2026 · Ablage: Kundenakte")
    c.restoreState()
    letter_foot(c)


@case("Lesbarkeitstafel, Englisch, QR-Code, Strichcode", DOC + "; QR-/Strichcode nach der Umwandlung lesbar",
      "Kleine (5–11 pt), dünne, graue, farbige und invertierte Schrift, Haarlinien, Graukeil; englischer Text "
      "(OCR deu+eng).")
def p_readability(c):
    y = readability_chart(c)
    par(c, EN[0], 18 * mm, y, W - 36 * mm, "Serif", 9.5)
    q = qr.QrCodeWidget("PAPERLESS-MRC TEST RE-2026-0815")
    b = q.getBounds()
    d = Drawing(28 * mm, 28 * mm, transform=[28 * mm / (b[2] - b[0]), 0, 0, 28 * mm / (b[3] - b[1]), 0, 0])
    d.add(q)
    renderPDF.draw(d, c, 18 * mm, 14 * mm)
    code128.Code128("RE20260815", barHeight=12 * mm, barWidth=0.35 * mm).drawOn(c, 60 * mm, 22 * mm)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Sans", 7)
    c.drawString(62 * mm, 18 * mm, "RE20260815 (Code 128)")


@case("Leer mit einem Punkt von 0,5 mm (Staubkorn)", "leer → entfernt",
      "Echte leere Seite; ein Staubkorn darf sie nicht retten. Druckt der Drucker die Seite nicht: ein "
      "unbedrucktes Blatt einlegen und mit Kugelschreiber einen winzigen Punkt setzen.")
def p_blank(c):
    c.setFillColorRGB(0, 0, 0)
    c.circle(W * 0.62, H * 0.41, 0.25 * mm, stroke=0, fill=1)


@case("Nur Seitenzahl", "behalten, komprimiert (Simulation: Tinte 0,010 % – nur doppelt so viel wie die "
      "Leerschwelle 0,005 %)", "Untere Grenze der Leerseitenerkennung.")
def p_number(c):
    page_number(c, 4)


@case("Ganzseitiges Wandfoto im Schatten, unscharf", PHOTO + " (ohne Texterkennung: kaum Tinte, kein Papier)",
      "Weiches Foto ohne Kanten (Rand läuft weich aus); früher als leer gelöscht.")
def p_wall(c):
    image(c, photo_wall(shade=True), 6 * mm, 6 * mm, W - 12 * mm, H - 12 * mm)


@case("Foto mit kurzer Bildunterschrift (6 Wörter)", PHOTO + " (Papier < 50 %, Texterkennung < 10 Wörter)",
      "Typische Seite einer Fotodokumentation.")
def p_photo_caption(c):
    image_fit(c, real_photo("coffee", 2200).rotate(90, expand=True), 12 * mm, 30 * mm, W - 24 * mm, H - 50 * mm)
    c.setFont("Sans", 11)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(14 * mm, 20 * mm, "Bild 3: Kaffeefleck auf Arbeitsplatte, Küche, 12.03.2026")


@case("Farbig hinterlegte Seite mit Textblöcken (Versicherungsstil)", DOC + " (Papier < 50 %, Texterkennung "
      "≥ 10 Wörter)", "Dokument, das nur die Texterkennung vom Foto unterscheidet.")
def p_blocks(c):
    c.setFillColorRGB(0.80, 0.88, 0.98)
    c.rect(12 * mm, 12 * mm, W - 24 * mm, H - 24 * mm, 0, 1)
    c.setFillColorRGB(0.12, 0.25, 0.45)
    c.rect(12 * mm, H - 40 * mm, W - 24 * mm, 28 * mm, 0, 1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Bold", 18)
    c.drawString(20 * mm, H - 29 * mm, "Ihre Versicherungsübersicht 2027")
    y = H - 50 * mm
    for k, p in enumerate(DE[:5]):
        c.setFillColorRGB(*[(0.97, 0.93, 0.80), (0.92, 0.92, 0.92)][k % 2])
        lines = simpleSplit(p, "Sans", 10, W - 50 * mm)
        hgt = (len(lines) + 2) * 13.5
        c.rect(18 * mm, y - hgt, W - 36 * mm, hgt, 0, 1)
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.setFont("Bold", 10)
        c.drawString(22 * mm, y - 13, f"Baustein {k + 1}")
        par(c, p, 22 * mm, y - 15, W - 50 * mm, "Sans", 10)
        y -= hgt + 6 * mm


@case("Ganzseitiges Foto einer hellen Wand mit Wasserfleck und Haarriss",
      "laut Code komprimiert (helle, ungesättigte Wand zählt als Papier ≥ 50 % → keine Fotoprüfung); gewünscht: "
      "Foto → Befund", "Mögliche Lücke der Fotoerkennung (Simulation: Papier 92 %, Tinte 0,4 %).")
def p_wall_bright(c):
    image(c, photo_wall(), 6 * mm, 6 * mm, W - 12 * mm, H - 12 * mm)


@case("Brief kopfüber und 2° schräg gedruckt", "komprimiert, gedreht um 180°, begradigt um ca. 2°",
      "Drehung (OSD) und danach Begradigung auf derselben Seite.")
def p_upside_skewed(c):
    rotated(c, 182, letter)


@case("Querformat-Tabelle (7 pt, Wasserzeichen) hochkant gedruckt", "komprimiert, gedreht um 90° (ist die OSD unsicher, "
      "entscheidet der Wortvergleich, MRC_ROTATE_CHECK; Simulation: 300 dpi unsicher 6,3, 200 dpi sicher 14,2)", "Fall, für den MRC_ROTATE_CHECK gebaut wurde.")
def p_landscape_form(c):
    landscape_form(c)


@case("Textarme Seite kopfüber: Logo, ein Wort, schräger Stempel, Unterschrift, Seitenzahl",
      "komprimiert, nicht begradigt; gewünscht: gedreht um 180°, laut Simulation wenig Text → OSD unsicher → "
      "bleibt kopfüber → Befund", "Logo/Stempel dürfen die Begradigung nicht bestimmen (Commit 316e21e); "
      "Untergrenze der Lageerkennung.")
def p_sparse_upside(c):
    def draw(cc):
        logo(cc, 20 * mm, H - 30 * mm)
        cc.setFont("Serif", 11)
        cc.setFillColorRGB(0, 0, 0)
        cc.drawString(25 * mm, H - 60 * mm, "Anlage")
        stamp(cc, 110 * mm, 170 * mm)
        signature(cc, 30 * mm, 60 * mm)
        page_number(cc, 11)
    rotated(c, 180, draw)


# ----------------------------------------------------------------------------- Ausgabe

def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out / "testseiten.pdf"), pagesize=A4)
    c.setTitle("paperless-mrc Testseiten")
    lines = ["# Testseiten – Fälle und Soll-Ergebnisse", "",
             "Erzeugt von `make_printset.py`. Soll = Verhalten mit den Standardwerten von paperless-mrc "
             "(OCR deu+eng). „Befund“ = schon die Simulation zeigt eine Schwäche; der echte Scan klärt es.", "",
             "| Seite | Fall | Soll | Vor dem Scannen |", "|---|---|---|---|"]
    for cs in CASES:
        cs["fn"](c)
        c.showPage()
        lines.append(f"| {cs['page']} | {cs['title']} – {cs['purpose']} | {cs['expect']} | {cs['hand'] or '–'} |")
    c.save()
    (out / "faelle.md").write_text("\n".join(lines) + "\n")
    expected = [dict(file="testseiten.pdf", id=str(cs["page"]), **{k: v for k, v in cs.items() if k != "fn"})
                for cs in CASES]
    (out / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=1))
    print(len(CASES), "Seiten")


if __name__ == "__main__":
    main()
