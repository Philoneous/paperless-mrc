# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Philoneous
"""Notiz am Dokument (MRC_NOTE): übersichtliches Protokoll, was paperless-mrc an der Datei gemacht hat.

Das Pre-Consume-Skript kennt die Einzelheiten, aber noch keine Dokumentnummer; das Post-Consume-Skript kennt die
Nummer. Beide laufen in derselben Paperless-Aufgabe (gleiche TASK_ID). Deshalb legt das Pre-Consume-Skript die
Angaben in notes/<TASK_ID>.json ab, das Post-Consume-Skript schreibt daraus die Notiz (POST documents/<id>/notes/)
und löscht die Datei. Notizen sind Markdown (ab Paperless-ngx 3.5 formatiert angezeigt, davor als lesbarer Text).
Alles hier ist optional: Fehler werden nur gemeldet und ändern nie etwas an der Datei.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from paperless_mrc import originals

STALE_SECONDS = 2 * 86400  # liegengebliebene Angaben (Post-Consume lief nie) nach zwei Tagen verwerfen

TEXTS = {
    "title": ("**paperless-mrc** · {when}", "**paperless-mrc** · {when}"),
    "compressed": ("Compressed: {before} → {after} (−{saved} %)", "Komprimiert: {before} → {after} (−{saved} %)"),
    "unchanged": ("Not compressed: {reason}", "Nicht komprimiert: {reason}"),
    "error": ("Error – file left unchanged: {message}", "Fehler – Datei unverändert: {message}"),
    "pages": ("Pages: {before} → {after}", "Seiten: {before} → {after}"),
    "pages_same": ("Pages: {n}", "Seiten: {n}"),
    "blank": ("Blank pages removed: {pages}", "Leere Seiten entfernt: {pages}"),
    "photos": ("Photos left unchanged: {pages}", "Fotos unverändert gelassen: {pages}"),
    "vectorised": ("Vectorised scans rasterised and made searchable: {pages}",
                   "Vektorisierte Scans gerastert und durchsuchbar gemacht: {pages}"),
    "digital": ("Digital pages left unchanged: {pages}", "Digitale Seiten unverändert: {pages}"),
    "rotated": ("Rotated: {items}", "Gedreht: {items}"),
    "deskewed": ("Straightened: {items}", "Begradigt: {items}"),
    "resized": ("Page size corrected to {size}: {pages}", "Seitengröße auf {size} korrigiert: {pages}"),
    "text_kept": ("Text layer: kept from the scan", "Textebene: aus dem Scan übernommen"),
    "text_ocr": ("Text layer: recognised with Tesseract ({languages})",
                 "Textebene: mit Tesseract erkannt ({languages})"),
    "text_mixed": ("Text layer: kept on {kept}, recognised with Tesseract ({languages}) on {ocr}",
                   "Textebene: übernommen auf {kept}, mit Tesseract erkannt ({languages}) auf {ocr}"),
    "original": ("Original kept as version “Original” (field “Original (MRC)”)",
                 "Original als Version „Original“ aufbewahrt (Feld „Original (MRC)“)"),
    "original_failed": ("Original could not be attached – it is kept on the server",
                        "Original konnte nicht angehängt werden – es bleibt auf dem Server erhalten"),
    "duration": ("Duration: {duration}", "Dauer: {duration}"),
    "page_numbers": ("Page numbers refer to the uploaded file.", "Seitenangaben beziehen sich auf die eingelesene Datei."),
    "page": ("page {pages}", "Seite {pages}"),
    "pages_word": ("pages {pages}", "Seiten {pages}"),
    # Gründe für „nicht komprimiert“ (reason aus paperless-mrc-result)
    "reason_not_pdf": ("not a PDF", "keine PDF"),
    "reason_signed": ("digitally signed (signature stays valid)", "digital signiert (Signatur bleibt gültig)"),
    "reason_encrypted": ("encrypted or protected", "verschlüsselt oder geschützt"),
    "reason_no_scanned_pages": ("no scanned pages", "keine gescannten Seiten"),
    "reason_mixed_disabled": ("contains digital pages (MRC_MIXED_PDFS off)",
                              "enthält digitale Seiten (MRC_MIXED_PDFS aus)"),
    "reason_nothing_to_compress": ("nothing to compress ({photos} photo(s), {blank} blank)",
                                   "nichts zu komprimieren ({photos} Foto(s), {blank} leer)"),
    "reason_not_smaller": ("the result would not have been smaller", "das Ergebnis wäre nicht kleiner gewesen"),
    "reason_original_version": ("original attached by paperless-mrc", "von paperless-mrc angehängtes Original"),
}


def notes_dir() -> Path:
    # Standard: neben der Ablage der Originale (/opt/paperless-mrc/notes)
    return Path(os.environ.get("MRC_NOTES_DIR") or originals.hold_dir().parent / "notes")


def save(task_id: str, data: dict) -> None:
    """Angaben für die Notiz ablegen (vom Pre-Consume-Skript). Ohne TASK_ID (z. B. Mac-App) nichts tun."""
    if not task_id:
        return
    folder = notes_dir()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    now = time.time()
    for old in folder.glob("*.json"):
        if now - old.stat().st_mtime > STALE_SECONDS:
            old.unlink(missing_ok=True)
    (folder / f"{task_id}.json").write_text(json.dumps({**data, "time": now}, ensure_ascii=False))


def page_ranges(pages: list[int]) -> str:
    """[1, 2, 3, 5, 7, 8] → „1–3, 5, 7–8“ (Seitennummern ab 1)."""
    parts, run = [], []
    for page in sorted(set(pages)):
        if run and page == run[-1] + 1:
            run.append(page)
            continue
        if run:
            parts.append(str(run[0]) if len(run) == 1 else f"{run[0]}–{run[-1]}")
        run = [page]
    if run:
        parts.append(str(run[0]) if len(run) == 1 else f"{run[0]}–{run[-1]}")
    return ", ".join(parts)


def _size(n: int, de: bool) -> str:
    text = f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"
    return text.replace(".", ",") if de else text


def _duration(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min {seconds % 60} s"


def render(data: dict, de: bool, original: bool | None = None) -> str:
    """Markdown-Notiz aus den abgelegten Angaben. original: True = als Version angehängt, False = Anhängen
    gescheitert, None = Option aus."""

    def t(key: str, **values) -> str:
        return TEXTS[key][1 if de else 0].format(**values)

    def pages(numbers: list[int]) -> str:
        return t("page" if len(numbers) == 1 else "pages_word", pages=page_ranges(numbers))

    when = datetime.fromtimestamp(data.get("time", time.time())).strftime("%d.%m.%Y %H:%M" if de else "%Y-%m-%d %H:%M")
    lines = [t("title", when=when), ""]
    status = data.get("status")
    if status == "error":
        lines.append(f"- {t('error', message=str(data.get('message', ''))[:300])}")
        return "\n".join(lines)
    if status != "compressed":
        reason = data.get("reason", "")
        key = f"reason_{reason}"
        text = t(key, photos=data.get("photos", 0), blank=data.get("blank", 0)) if key in TEXTS else reason
        lines.append(f"- {t('unchanged', reason=text)}")
        return "\n".join(lines)

    before, after = data["size_before"], data["size_after"]
    lines.append(f"- {t('compressed', before=_size(before, de), after=_size(after, de), saved=round(100 - after * 100 / before))}")
    total = data.get("pages_before", data.get("pages"))
    lines.append(f"- {t('pages', before=total, after=data['pages'])}" if total != data["pages"]
                 else f"- {t('pages_same', n=data['pages'])}")
    for key in ("blank", "photos", "vectorised", "digital"):
        if data.get(f"{key}_pages"):
            lines.append(f"- {t(key, pages=page_ranges(data[f'{key}_pages']))}")
    if data.get("rotated"):
        lines.append(f"- {t('rotated', items=', '.join(f'{pages([p])} ({d}°)' for p, d in data['rotated']))}")
    if data.get("deskewed"):
        items = ", ".join(f"{pages([p])} ({a:+.1f}°)".replace(".", "," if de else ".").replace("-", "−")
                          for p, a in data["deskewed"])
        lines.append(f"- {t('deskewed', items=items)}")
    if data.get("resized_pages"):
        lines.append(f"- {t('resized', size=data.get('fit_size', 'A4'), pages=page_ranges(data['resized_pages']))}")
    kept, ocr = data.get("text_kept_pages", []), data.get("text_ocr_pages", [])
    languages = data.get("languages", "")
    if kept and ocr:
        lines.append(f"- {t('text_mixed', kept=pages(kept), ocr=pages(ocr), languages=languages)}")
    elif kept:
        lines.append(f"- {t('text_kept')}")
    elif ocr:
        lines.append(f"- {t('text_ocr', languages=languages)}")
    if original is True:
        lines.append(f"- {t('original')}")
    elif original is False:
        lines.append(f"- {t('original_failed')}")
    if data.get("seconds") is not None:
        lines.append(f"- {t('duration', duration=_duration(data['seconds']))}")
    if data.get("blank_pages") and any(data.get(k) for k in ("photos_pages", "vectorised_pages", "digital_pages",
                                                              "rotated", "deskewed", "resized_pages")):
        lines += ["", f"_{t('page_numbers')}_"]
    return "\n".join(lines)


def write(api: originals.Api, doc_id: int, task_id: str, original: bool | None) -> bool:
    """Abgelegte Angaben als Notiz an das Dokument schreiben (vom Post-Consume-Skript). False: nichts abgelegt."""
    path = notes_dir() / f"{task_id}.json"
    if not task_id or not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
        api.request("POST", f"documents/{doc_id}/notes/", {"note": render(data, originals.german(api), original)})
    finally:
        path.unlink(missing_ok=True)
    return True


def pending(task_id: str) -> bool:
    return bool(task_id) and (notes_dir() / f"{task_id}.json").exists()


def discard(task_id: str) -> None:
    if task_id:
        (notes_dir() / f"{task_id}.json").unlink(missing_ok=True)
