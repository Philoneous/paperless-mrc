# SPDX-License-Identifier: AGPL-3.0-or-later
"""paperless-mrc – Pre-Consume-Skript für Paperless-ngx.

Komprimiert gescannte PDFs per Mixed Raster Content (MRC, archive-pdf-tools) und
ersetzt damit die Arbeitskopie. Paperless speichert so nur noch eine, kleine Datei.

Ablauf je Dokument:
  1. Gescannte Seiten erkennen (Seite = ein Seitenbild, kein sichtbarer Text); andere Seiten
     (z. B. angehängte digitale Seiten) bleiben unverändert, signierte PDFs ganz.
  2. Wirklich leere gescannte Seiten entfernen.
  3. Jede Seite in nativer Auflösung rendern (inkl. darübergelegter Grafiken).
  4. Textebene: vorhandene übernehmen, sonst Tesseract (mit Drehung/Begradigung).
  5. MRC-Kodierung je Scan-Seite, an ihrer Stelle in die Originaldatei einsetzen (Lesezeichen und
     Metadaten bleiben), Übergrößen auf A4, SMask-Farbraum korrigieren.
  6. Ergebnis prüfen; nur wenn alles stimmt und es kleiner ist, Arbeitskopie ersetzen.

Bei jedem Fehler bleibt die Arbeitskopie unverändert und das Skript endet mit 0,
damit Paperless das Dokument normal verarbeitet.
"""

from __future__ import annotations

import contextlib
import json
import re
import os
import shutil
import subprocess
import sys
import multiprocessing
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pikepdf
import pymupdf
from PIL import Image, ImageFilter

A4 = (595.28, 841.89)  # pt
A3_WIDTH = 841.89  # pt; ist die kürzere Seite größer, ist die Seitengröße offensichtlich falsch
BLANK_INK_PERCENT = 0.005  # nur wirklich leere Seiten (eine Seitenzahl liegt bei ca. 0,05 %)
MIN_SKEW_DEG = 0.2
TOOLS_DIR = Path(sys.executable).parent  # recode_pdf, pdf-to-hocr, pdf-metadata-json


def log(message: str) -> None:
    print(f"paperless-mrc: {message}", flush=True)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("true", "1", "t", "y", "yes")


@dataclass(frozen=True)
class Settings:
    """Übernimmt die passenden OCR-Einstellungen von Paperless (gleiche Standardwerte)."""

    language: str
    deskew: bool
    rotate: bool
    rotate_threshold: float
    jobs: int = 1  # Seiten parallel; wie Paperless' OCRmyPDF-Aufruf (THREADS_PER_WORKER)
    # Eigene Einstellungen (MRC_*), Standardwerte = bisheriges festes Verhalten
    remove_blank: bool = True
    blank_ink_percent: float = BLANK_INK_PERCENT
    bg_downsample: int = 2  # Hintergrund in 1/n der Auflösung
    bg_rate: float = 200.0  # JPEG2000-Kompressionsrate des Hintergrunds (opj_compress -r)
    fit_a4: bool = True
    deskew_min: float = MIN_SKEW_DEG  # kleinere Schräglagen werden nicht korrigiert
    deskew_max: float = 5.0  # gesuchter Bereich ±; Ergebnis am Rand gilt als unklar → nicht drehen
    skip_photos: bool = True  # Fotoseiten unverändert lassen
    photo_paper_percent: float = 50.0  # Seiten mit weniger Papierfläche (%) werden per Texterkennung geprüft
    photo_min_words: int = 10  # … und gelten unter so vielen sicher erkannten Wörtern als Foto
    blank_paper_percent: float = 90.0  # leer nur, wenn mindestens so viel Fläche Papierton hat (%)
    vector_pages: bool = True  # in Vektorgrafik umgewandelte Scans rastern und komprimieren
    vector_min_items: int = 1000  # ab so vielen Vektorelementen (ohne Bild und Text) gilt eine Seite als solcher Scan
    vector_dpi: int = 300  # Rasterauflösung für diese Seiten
    mixed_pdfs: bool = True  # PDFs mit nicht gescannten Seiten bearbeiten (diese Seiten bleiben unverändert)
    keep_text_layer: bool = True  # vorhandene Textebene übernehmen statt neu erkennen
    max_dpi: int = 0  # Obergrenze der Auflösung für kodierte Seiten; 0 = aus (Originalauflösung)
    timing: bool = False  # Laufzeiten je Schritt und Seite ausgeben (Analyse/Optimierung)

    @classmethod
    def from_env(cls) -> Settings:
        workers = int(os.environ.get("PAPERLESS_TASK_WORKERS", "1"))
        default_jobs = max((os.cpu_count() or 1) // max(workers, 1), 1)
        return cls(
            language=os.environ.get("PAPERLESS_OCR_LANGUAGE", "eng"),
            deskew=_env_bool("PAPERLESS_OCR_DESKEW", True),
            rotate=_env_bool("PAPERLESS_OCR_ROTATE_PAGES", True),
            rotate_threshold=float(os.environ.get("PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD", "12.0")),
            # MRC_JOBS (eigener Wert) vor PAPERLESS_THREADS_PER_WORKER vor Kerne ÷ Worker
            jobs=max(int(os.environ.get("MRC_JOBS") or os.environ.get("PAPERLESS_THREADS_PER_WORKER") or default_jobs), 1),
            remove_blank=_env_bool("MRC_REMOVE_BLANK_PAGES", True),
            blank_ink_percent=float(os.environ.get("MRC_BLANK_INK_PERCENT", BLANK_INK_PERCENT)),
            bg_downsample=max(int(os.environ.get("MRC_BG_DOWNSAMPLE", "2")), 1),
            bg_rate=max(float(os.environ.get("MRC_BG_COMPRESSION_RATE", "200")), 1.0),
            fit_a4=_env_bool("MRC_FIT_A4", True),
            deskew_min=max(float(os.environ.get("MRC_DESKEW_MIN_ANGLE", MIN_SKEW_DEG)), 0.0),
            deskew_max=min(max(float(os.environ.get("MRC_DESKEW_MAX_ANGLE", "5")), 0.5), 45.0),
            skip_photos=_env_bool("MRC_SKIP_PHOTOS", True),
            photo_paper_percent=float(os.environ.get("MRC_PHOTO_PAPER_PERCENT", "50")),
            photo_min_words=max(int(os.environ.get("MRC_PHOTO_MIN_WORDS", "10")), 0),
            blank_paper_percent=float(os.environ.get("MRC_BLANK_PAPER_PERCENT", "90")),
            vector_pages=_env_bool("MRC_VECTOR_PAGES", True),
            vector_min_items=max(int(os.environ.get("MRC_VECTOR_MIN_ITEMS", "1000")), 1),
            vector_dpi=min(max(int(os.environ.get("MRC_VECTOR_DPI", "300")), 72), 1200),
            mixed_pdfs=_env_bool("MRC_MIXED_PDFS", True),
            keep_text_layer=_env_bool("MRC_KEEP_TEXT_LAYER", True),
            max_dpi=max(int(os.environ.get("MRC_MAX_DPI", "0")), 0),
            timing=_env_bool("MRC_TIMING", False),
        )


class Stopwatch:
    """Misst aufeinanderfolgende Schritte: lap("Name") schließt den laufenden Schritt ab."""

    def __init__(self) -> None:
        self.start = self.last = time.perf_counter()
        self.laps: list[tuple[str, float]] = []

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.laps.append((name, now - self.last))
        self.last = now

    def __str__(self) -> str:
        parts = ", ".join(f"{name} {seconds:.1f}s" for name, seconds in self.laps)
        return f"{parts} | gesamt {self.last - self.start:.1f}s"


def run(*cmd: str | Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PATH": f"{TOOLS_DIR}{os.pathsep}{os.environ.get('PATH', '')}"}
    return subprocess.run([str(c) for c in cmd], check=True, capture_output=True, text=True, env=env)


# ----------------------------------------------------------------------------- Erkennung


def is_scan_page(page: pymupdf.Page) -> bool:
    """Genau ein Bild, das die Seite fast ganz bedeckt, und kein sichtbarer Text."""
    images = page.get_image_info()
    if len(images) != 1:
        return False
    covered = pymupdf.Rect(images[0]["bbox"]) & page.rect
    if covered.get_area() < 0.9 * page.rect.get_area():
        return False
    return all(span["type"] == 3 or span.get("opacity", 1) == 0 for span in page.get_texttrace())


def is_vector_page(page: pymupdf.Page, min_items: int) -> bool:
    """Kein Bild, kein sichtbarer Text, aber sehr viele Vektorelemente (Linien, Kurven, Rechtecke): ein beim Scannen
    vektorisierter Scan (ohne Textebene, groß)."""
    if page.get_image_info():
        return False
    if any(span["type"] != 3 and span.get("opacity", 1) != 0 for span in page.get_texttrace()):
        return False
    return sum(len(path["items"]) for path in page.get_cdrawings()) >= min_items


def ink_percent(page: pymupdf.Page) -> float:
    """Anteil Pixel, die deutlich dunkler sind als der lokale Papierton (Rand ignoriert)."""
    zoom = 600 / page.rect.width
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
    gray = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    # lokaler Papierton: Median auf 1/4 der Auflösung (wie Fenster 31 px bei voller), dann zurückskaliert
    paper = gray.reduce(4).filter(ImageFilter.MedianFilter(7)).resize(gray.size, Image.BILINEAR)
    ink = (np.asarray(paper, np.int16) - np.asarray(gray, np.int16)) > 40
    m_y, m_x = int(0.02 * ink.shape[0]), int(0.02 * ink.shape[1])
    return float(ink[m_y:-m_y, m_x:-m_x].mean() * 100)


def paper_percent(page: pymupdf.Page) -> float:
    """Anteil der Fläche in Papierton (hell, ungesättigt) in %; 3 % Rand ignoriert.
    Für die Leerseitenprüfung: eine leere Seite ist fast vollständig Papier."""
    zoom = 600 / page.rect.width
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB, alpha=False)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).astype(np.int16)
    m = int(0.03 * pix.width)
    a = a[m:-m, m:-m]
    luma = a @ np.array([0.299, 0.587, 0.114])
    saturation = a.max(axis=2) - a.min(axis=2)
    paper = np.percentile(luma, 95)
    return float(((np.abs(luma - paper) < 30) & (saturation < 40)).mean() * 100)


def analyse_page(path: Path, index: int) -> tuple[float, float]:
    """Tintenanteil und Papieranteil einer Seite (je %)."""
    with pymupdf.open(path) as doc:
        page = doc[index]
        return ink_percent(page), paper_percent(page)


def confident_words(hocr: str, min_confidence: int = 60) -> int:
    """Anzahl sicher erkannter Wörter (≥ 3 Buchstaben/Ziffern) in Tesseract-hOCR."""
    count = 0
    for confidence, inner in re.findall(r"class='ocrx_word'[^>]*x_wconf (\d+)[^>]*>(.*?)</span>", hocr, re.S):
        text = re.sub(r"<[^>]+>", "", inner)
        if int(confidence) >= min_confidence and sum(c.isalnum() for c in text) >= 3:
            count += 1
    return count


def image_scale(page: pymupdf.Page) -> float:
    """Auflösung des Seitenbilds als Faktor zu 72 dpi (wie pdf-metadata-json, ohne eigenen Prozess)."""
    scale_x = scale_y = 1.0
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        if abs(x1 - x0) < info["width"]:
            scale_x = info["width"] / abs(x1 - x0)
        if abs(y1 - y0) < info["height"]:
            scale_y = info["height"] / abs(y1 - y0)
    scale = max(scale_x, scale_y) if page.get_image_info() else 300 / 72
    return min(scale, 25000 / page.rect.width, 25000 / page.rect.height)


def pmap(fn, args: list[tuple], jobs: int) -> list:
    """fn(*a) für alle a, bei jobs > 1 in getrennten Prozessen; Reihenfolge bleibt erhalten."""
    if jobs <= 1 or len(args) <= 1:
        return [fn(*a) for a in args]
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # Tesseract nicht zusätzlich mehrfädig
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=min(jobs, len(args)), mp_context=ctx) as pool:
        return list(pool.map(fn, *zip(*args)))


# ----------------------------------------------------------------------------- OCR-Hilfen


def orientation(image_path: Path, threshold: float) -> int:
    """Nötige Drehung laut Tesseract-OSD (0, 90, 180, 270); 0 bei zu geringer Sicherheit."""
    try:
        out = run("tesseract", image_path, "-", "--psm", "0").stdout
    except subprocess.CalledProcessError:
        return 0  # z. B. zu wenig Text für eine Erkennung
    values = dict(line.split(":", 1) for line in out.splitlines() if ":" in line)
    rotate = int(values.get("Rotate", "0").strip())
    confidence = float(values.get("Orientation confidence", "0").strip())
    return rotate if confidence >= threshold else 0


def skew_angle(image: Image.Image, max_angle: float = 5.0) -> float | None:
    """Schräglage per Projektionsprofil: Winkel mit der größten Varianz der Zeilensummen.
    None, wenn das Ergebnis am Rand des Suchbereichs liegt (keine erkennbaren Zeilen, z. B. Foto)."""
    small = image.convert("L").resize((800, round(800 * image.height / image.width)))
    a = np.asarray(small, np.float32)
    binary = Image.fromarray(((a < a.mean() - a.std()) * 255).astype(np.uint8))

    def score(angle: float) -> float:
        return float(np.asarray(binary.rotate(angle), np.float32).sum(axis=1).var())

    coarse = max(np.arange(-max_angle, max_angle + 0.01, 0.5), key=score)
    if abs(coarse) >= max_angle - 0.01:
        return None
    return round(float(max(np.arange(coarse - 0.5, coarse + 0.51, 0.1), key=score)), 1)


# ----------------------------------------------------------------------------- Verarbeitung


def encode_page(page_pdf: Path, work: Path, settings: Settings, label: str = "Seite",
                render_dpi: float | None = None, photo_check: bool = False) -> tuple[Path | None, bool]:
    """Kodiert eine einseitige Scan-PDF per MRC. Rückgabe: Ergebnis (None = Foto, Seite bleibt),
    Textebene übernommen? render_dpi: feste Auflösung (Vektorseiten); sonst die des Seitenbilds.
    photo_check: Seite nur kodieren, wenn genug Text erkannt wird (sonst Foto)."""
    clock = Stopwatch()
    with pymupdf.open(page_pdf) as doc:
        page = doc[0]
        scale = render_dpi / 72 if render_dpi else image_scale(page)
        if settings.max_dpi:
            scale = min(scale, settings.max_dpi / 72)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False)
        words = [w[4] for w in page.get_text("words")]
        has_text = settings.keep_text_layer and bool(words)
        x0, y0, x1, y1 = page.rect
    meta_file = work / "meta.json"  # Eingabe für pdf-to-hocr, Felder wie bei pdf-metadata-json
    meta_file.write_text(json.dumps({"page_data": [{
        "estimated_scale": scale, "estimated_ppi": int(72 * scale),
        "estimated_default_render_res": [x0 * scale, y0 * scale, x1 * scale, y1 * scale]}]}))
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    image_path = work / "page.png"
    dpi = 72 * scale
    clock.lap("Rendern")

    def save(img: Image.Image) -> None:
        img.save(image_path, dpi=(dpi, dpi), compress_level=1)  # Zwischendatei: schnell statt klein

    if has_text:
        if photo_check and sum(sum(c.isalnum() for c in w) >= 3 for w in words) < settings.photo_min_words:
            log(f"{label}: Foto (kaum Text in der Textebene) – unverändert")
            return None, has_text
        hocr = run("pdf-to-hocr", "-f", page_pdf, "-J", meta_file).stdout
        save(image)
        clock.lap("Textebene")
    else:
        save(image)
        if settings.rotate and (rotate := orientation(image_path, settings.rotate_threshold)):
            image = image.rotate(-rotate, expand=True)
            log(f"{label}: um {rotate}° gedreht")
        clock.lap("Ausrichtung")
        if settings.deskew:
            angle = skew_angle(image, settings.deskew_max)
            if angle is None:
                log(f"{label}: Schräglage nicht eindeutig – nicht begradigt")
            elif abs(angle) >= max(settings.deskew_min, 0.05):
                image = image.rotate(angle, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
                log(f"{label}: Schräglage {angle:+.1f}° korrigiert")
        save(image)
        clock.lap("Begradigen")
        hocr = run("tesseract", image_path, "-", "-l", settings.language, "hocr").stdout
        clock.lap("OCR")
        if photo_check and (found := confident_words(hocr)) < settings.photo_min_words:
            log(f"{label}: Foto ({found} sicher erkannte Wörter) – unverändert")
            return None, has_text

    hocr_path = work / "page.hocr"
    hocr_path.write_text(hocr)
    out = work / "page_mrc.pdf"
    mask = "jbig2" if shutil.which("jbig2") else "ccitt"
    run("recode_pdf", "-I", image_path, "-T", hocr_path, "-o", out, "--dpi", str(round(dpi)),
        "-J", "openjpeg", "--mrc-image-format", "jpeg2000", "--mask-compression", mask,
        "--bg-downsample", str(settings.bg_downsample), f"--bg-compression-flags=-r {settings.bg_rate:g}")
    clock.lap("MRC")
    if settings.timing:
        log(f"{label}: Zeit {clock} ({image.width}x{image.height} px, {dpi:.0f} dpi)")
    return out, has_text


def fit_a4(pdf: pikepdf.Pdf, page: pikepdf.Page) -> bool:
    """Skaliert offensichtlich zu große Seiten (z. B. 72-ppi-Handyscans) auf A4."""
    x0, y0, x1, y1 = (float(v) for v in page.mediabox)
    w, h = x1 - x0, y1 - y0
    if min(w, h) <= A3_WIDTH:
        return False
    box_w, box_h = (A4[1], A4[0]) if w > h else A4
    f = min(box_w / w, box_h / h)
    page.contents_add(pikepdf.Stream(pdf, f"q {f:.6f} 0 0 {f:.6f} {-x0 * f:.4f} {-y0 * f:.4f} cm\n".encode()),
                      prepend=True)
    page.contents_add(pikepdf.Stream(pdf, b"\nQ"))
    page.mediabox = pikepdf.Array([0, 0, w * f, h * f])
    if "/CropBox" in page.obj:
        del page.obj["/CropBox"]
    return True


def fix_smask_colorspace(page: pikepdf.Page) -> None:
    """recode_pdf legt die Maske im ICC-Farbraum an; die PDF-Norm verlangt DeviceGray
    (sonst zeigt z. B. Poppler nur den Hintergrund)."""
    for image in page.get_images().values():
        smask = image.get("/SMask")
        if smask is not None and smask.get("/ColorSpace") != pikepdf.Name.DeviceGray:
            smask.ColorSpace = pikepdf.Name.DeviceGray


def replace_page_content(pdf: pikepdf.Pdf, page: pikepdf.Page, new: pikepdf.Page) -> None:
    """Ersetzt Inhalt und Größe einer Seite, behält aber das Seitenobjekt selbst – damit bleiben
    Lesezeichen und Verweise auf die Seite gültig."""
    obj, copied = page.obj, pdf.copy_foreign(new.obj)  # nicht eingebundene Reste entfallen beim Speichern
    obj.Contents = copied.Contents
    obj.Resources = copied.Resources
    obj.MediaBox = pikepdf.Array([float(v) for v in new.mediabox])
    # Drehung und Anmerkungen sind im neuen Seitenbild bereits enthalten
    for key in ("/CropBox", "/TrimBox", "/BleedBox", "/ArtBox", "/Rotate", "/UserUnit", "/Annots", "/Thumb"):
        if key in obj:
            del obj[key]


def build(src: Path, encode: list[int], blank: list[int], settings: Settings, work: Path,
          vectors: set[int] = frozenset(), doubtful: set[int] = frozenset()) -> tuple[Path | None, list[tuple[bool, bool]]]:
    """Kodiert die Scan-Seiten neu und setzt sie an ihrer Stelle in die Originaldatei ein.
    Alle anderen Seiten, Lesezeichen und Metadaten bleiben, wie sie sind; leere Seiten entfallen."""
    with pikepdf.open(src) as pdf, contextlib.ExitStack() as parts:
        page_dirs = []
        for index in encode:
            page_dir = work / f"p{index:04d}"
            page_dir.mkdir()
            single = pikepdf.new()
            single.pages.append(pdf.pages[index])
            single.save(page_dir / "in.pdf")
            page_dirs.append(page_dir)

        args = [(d / "in.pdf", d, settings, f"Seite {index + 1}", settings.vector_dpi if index in vectors else None,
                 index in doubtful) for d, index in zip(page_dirs, encode)]
        encoded = pmap(encode_page, args, settings.jobs)
        results = [(path is not None, had_text) for path, had_text in encoded]
        if not any(coded for coded, _ in results):
            return None, results

        resized = 0
        for index, (path, _) in zip(encode, encoded):
            if path is None:  # Foto: Seite bleibt unverändert
                continue
            part = parts.enter_context(pikepdf.open(path))  # bis zum Speichern offen halten
            page = pdf.pages[index]
            replace_page_content(pdf, page, part.pages[0])
            resized += settings.fit_a4 and fit_a4(pdf, page)
            fix_smask_colorspace(page)
        if resized:
            log(f"{resized} Seite(n) mit falscher Seitengröße auf A4 skaliert")
        for index in sorted(blank, reverse=True):
            del pdf.pages[index]
        out = work / "result.pdf"
        pdf.save(out, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    return out, results


def verify(src: Path, keep: list[int], out: Path, text_checked: set[int], work: Path) -> None:
    """Wirft eine Ausnahme, wenn das Ergebnis nicht verwendet werden darf.
    text_checked: Seiten (alte Nummern), deren Text erhalten bleiben muss."""
    with pymupdf.open(src) as before, pymupdf.open(out) as after:
        if after.page_count != len(keep):
            raise RuntimeError(f"Seitenzahl {after.page_count} statt {len(keep)}")
        for n, index in enumerate(keep):
            if index not in text_checked:
                continue
            words_before = len(before[index].get_text("words"))
            words_after = len(after[n].get_text("words"))
            if words_after < 0.95 * words_before:
                raise RuntimeError(f"Seite {index + 1}: Text unvollständig ({words_after}/{words_before} Wörter)")
    check = run("pdftoppm", "-r", "10", "-png", out, work / "check")
    if "error" in check.stderr.lower():
        raise RuntimeError(f"Darstellungsprüfung mit Poppler fehlgeschlagen: {check.stderr.strip()}")


def process(path: Path, settings: Settings) -> None:
    if path.suffix.lower() != ".pdf":
        log(f"{path.name}: keine PDF – unverändert")
        return
    clock = Stopwatch()
    with pymupdf.open(path) as doc:
        if doc.get_sigflags() > 0:
            log(f"{path.name}: digital signiert – unverändert, damit die Signatur gültig bleibt")
            return
        pages = doc.page_count
        scans = [i for i, page in enumerate(doc) if is_scan_page(page)]
        vectors = [i for i, page in enumerate(doc) if settings.vector_pages and i not in scans
                   and is_vector_page(page, settings.vector_min_items)]
    candidates = sorted(scans + vectors)
    if not candidates:
        log(f"{path.name}: keine gescannten Seiten – unverändert")
        return
    if not settings.mixed_pdfs and len(candidates) < pages:
        log(f"{path.name}: enthält nicht gescannte Seiten – unverändert (MRC_MIXED_PDFS aus)")
        return

    clock.lap("Erkennung")
    photos, blank, doubtful = [], [], set()
    if settings.remove_blank or settings.skip_photos:
        # im eigenen Prozess: ~0,1 s je Seite, Prozessstart wäre teurer (live: 2,3 s statt 6,6 s mit 4 Prozessen)
        stats = [analyse_page(path, i) for i in candidates]
        for i, (ink, paper) in zip(candidates, stats):
            little_ink = ink < settings.blank_ink_percent
            if little_ink and paper >= settings.blank_paper_percent:  # leeres Papier
                if settings.remove_blank:
                    blank.append(i)
            elif settings.skip_photos and i in scans:
                if little_ink:  # kaum Kontraste, aber kein Papier (z. B. Foto einer Wand)
                    photos.append(i)
                elif paper < settings.photo_paper_percent:
                    # farbig hinterlegtes Dokument oder Foto: entscheidet die Texterkennung
                    doubtful.add(i)
    clock.lap("Seitenanalyse")
    encode = [i for i in candidates if i not in photos and i not in blank]
    if not encode:
        log(f"{path.name}: keine Seite zu komprimieren ({len(photos)} Foto, {len(blank)} leer) – unverändert")
        return
    keep = [i for i in range(pages) if i not in blank]
    others = pages - len(candidates)

    with tempfile.TemporaryDirectory(prefix="paperless-mrc-") as tmp:
        work = Path(tmp)
        out, results = build(path, encode, blank, settings, work, set(vectors), doubtful)
        clock.lap(f"Kodieren ({len(encode)} S., {settings.jobs} parallel)")
        photos += [i for i, (coded, _) in zip(encode, results) if not coded]
        if out is None:
            log(f"{path.name}: keine Seite zu komprimieren ({len(photos)} Foto, {len(blank)} leer) – unverändert")
            return
        text_kept = [had for coded, had in results if coded]
        coded = [i for i, (c, _) in zip(encode, results) if c]
        must_keep_text = {i for i, (c, had) in zip(encode, results) if c and had} | (set(keep) - set(coded))
        verify(path, keep, out, must_keep_text, work)
        clock.lap("Prüfung")
        size_before, size_after = path.stat().st_size, out.stat().st_size
        if size_after >= size_before:
            log(f"{path.name}: Ergebnis nicht kleiner ({size_after // 1024} KB) – unverändert")
            return
        staged = path.with_name(path.name + ".mrc-tmp")
        shutil.copyfile(out, staged)
        os.replace(staged, path)

    source = "übernommen" if all(text_kept) else "per Tesseract" if not any(text_kept) else "gemischt"
    details = [f"{len(blank)} leere entfernt" if blank else "",
               f"{len(photos)} Foto(s) unverändert" if photos else "",
               f"{len([i for i in vectors if i in coded])} vektorisierte gerastert" if vectors else "",
               f"{others} digitale unverändert" if others else ""]
    if settings.timing:
        log(f"{path.name}: Zeit {clock}")
    log(f"{path.name}: {size_before // 1024} KB -> {size_after // 1024} KB, {len(keep)} Seite(n)"
        + "".join(f", {d}" for d in details if d) + f", Textebene {source}")


def main() -> int:
    working_path = os.environ.get("DOCUMENT_WORKING_PATH")
    if not working_path:
        log("DOCUMENT_WORKING_PATH ist nicht gesetzt – nichts zu tun")
        return 0
    try:
        process(Path(working_path), Settings.from_env())
    except Exception as exc:  # fail-safe: Paperless soll das Original normal verarbeiten
        detail = exc.stderr.strip()[-500:] if isinstance(exc, subprocess.CalledProcessError) else ""
        log(f"Fehler, Dokument bleibt unverändert: {exc!r} {detail}".strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
