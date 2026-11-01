# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Philoneous
"""Katalog aller Einstellungen in paperless.conf – einzige Quelle für den Einrichtungsassistenten
(paperless-mrc-setup). tests/test_catalog.py prüft, dass jede im Code gelesene Einstellung hier steht, Standard
und Bereich mit dem Code übereinstimmen und REVISION zur neuesten Option passt.

Neue Option: Eintrag mit since=REVISION + 1 anlegen und REVISION erhöhen. Der Assistent fragt bei einem Update
dann genau die Optionen, die seit der letzten Einrichtung hinzugekommen sind.
"""

from __future__ import annotations

from dataclasses import dataclass, field

REVISION = 1  # erhöhen, sobald eine Option hinzukommt (since der neuen Option = REVISION)


@dataclass(frozen=True)
class Option:
    key: str
    level: str  # "basic": wird jedem gezeigt; "advanced": nur auf Wunsch
    kind: str  # bool, int, float, choice, text
    default: str  # wie in paperless.conf geschrieben
    title: tuple[str, str]  # (Englisch, Deutsch)
    help: tuple[str, str]
    group: tuple[str, str] = ("General", "Allgemein")
    choices: tuple[str, ...] = ()
    since: int = 1
    secret: bool = False
    requires: str | None = None  # nur fragen, wenn diese Ja/Nein-Option an ist
    min_max: tuple[float, float] | None = field(default=None)  # sonst aus main.RANGES


QUALITY = ("Quality and size", "Qualität und Größe")
PAGES = ("Page selection", "Seitenauswahl")
OCR = ("Text recognition", "Texterkennung")
BLANK = ("Blank pages", "Leere Seiten")
ORIGINAL = ("Keep the original until checked", "Original bis zur Prüfung aufbewahren")
OTHER = ("Other", "Sonstiges")

OPTIONS: list[Option] = [
    # ---------------------------------------------------------------- wichtigste Einstellungen (jeder sieht sie)
    Option("PAPERLESS_OCR_LANGUAGE", "basic", "text", "eng", group=OCR,
           title=("OCR languages", "Sprachen der Texterkennung"),
           help=("Tesseract language codes joined with +, e.g. deu+eng or fra+eng. Shared with Paperless itself; "
                 "the installer installs the matching language packs.",
                 "Tesseract-Sprachkürzel, mit + verbunden, z. B. deu+eng oder fra+eng. Gilt auch für Paperless "
                 "selbst; der Installer installiert die passenden Sprachpakete.")),
    Option("MRC_REMOVE_BLANK_PAGES", "basic", "bool", "true", group=BLANK,
           title=("Remove blank scanned pages", "Leere gescannte Seiten entfernen"),
           help=("Removes empty pages, e.g. back sides from double-sided scanning. A page with only a page number "
                 "is kept; digital pages are never removed.",
                 "Entfernt leere Seiten, z. B. Rückseiten beim beidseitigen Scannen. Eine Seite mit nur einer "
                 "Seitenzahl bleibt; digitale Seiten werden nie entfernt.")),
    Option("MRC_SKIP_PHOTOS", "basic", "bool", "true", group=PAGES,
           title=("Leave photo pages unchanged", "Fotoseiten unverändert lassen"),
           help=("MRC would visibly degrade photos, so pages recognized as photos stay as they are.",
                 "MRC würde Fotos sichtbar verschlechtern; als Foto erkannte Seiten bleiben deshalb, wie sie sind.")),
    Option("MRC_MIXED_PDFS", "basic", "bool", "true", group=PAGES,
           title=("Also process PDFs with digital pages", "Auch PDFs mit digitalen Seiten bearbeiten"),
           help=("Compresses the scanned pages of PDFs that also contain digital pages (these stay unchanged). "
                 "No = only PDFs that consist entirely of scans.",
                 "Komprimiert die gescannten Seiten von PDFs, die auch digitale Seiten enthalten (diese bleiben "
                 "unverändert). Nein = nur PDFs, die ganz aus Scans bestehen.")),
    Option("MRC_KEEP_TEXT_LAYER", "basic", "bool", "true", group=OCR,
           title=("Keep an existing text layer", "Vorhandene Textebene übernehmen"),
           help=("Keeps the text layer from the scanner instead of recognizing the text again. No = always "
                 "recognize again (pages are then also turned and straightened).",
                 "Übernimmt die Textebene des Scanners, statt den Text neu zu erkennen. Nein = immer neu erkennen "
                 "(Seiten werden dann auch gedreht und begradigt).")),
    Option("MRC_FIT_A4", "basic", "bool", "true", group=QUALITY,
           title=("Correct wrong page sizes", "Falsche Seitengrößen korrigieren"),
           help=("Scales scanned pages with an implausibly large page size (e.g. phone scans stored several times "
                 "larger than A4) to the paper format below.",
                 "Skaliert gescannte Seiten mit unplausibel großer Seitengröße (z. B. Handyscans, die ein "
                 "Vielfaches von A4 groß gespeichert sind) auf das folgende Papierformat.")),
    Option("MRC_FIT_PAGE_SIZE", "basic", "choice", "a4", requires="MRC_FIT_A4", group=QUALITY, choices=("a4", "letter", "legal"),
           title=("Paper format", "Papierformat"),
           help=("Target format for corrected page sizes: a4, letter (US Letter) or legal (US Legal).",
                 "Zielformat für korrigierte Seitengrößen: a4, letter (US Letter) oder legal (US Legal).")),
    Option("MRC_KEEP_ORIGINAL", "basic", "bool", "false", group=ORIGINAL,
           title=("Keep the original until you have checked it", "Original bis zur Prüfung aufbewahren"),
           help=("Keeps the original as a second version of the document (Paperless-ngx 3 or later); a field "
                 "“Original (MRC)” decides when it is deleted. Needs an API token.",
                 "Bewahrt das Original als zweite Version des Dokuments auf (ab Paperless-ngx 3); ein Feld "
                 "„Original (MRC)“ entscheidet, wann es gelöscht wird. Braucht ein API-Token.")),
    Option("MRC_KEEP_ORIGINAL_DAYS", "basic", "int", "30", requires="MRC_KEEP_ORIGINAL", group=ORIGINAL,
           title=("Delete the original after (days)", "Original löschen nach (Tagen)"),
           help=("Default period after which a kept original is deleted, unless “Keep” is chosen in the document.",
                 "Standardfrist, nach der ein aufbewahrtes Original gelöscht wird – außer im Dokument ist "
                 "„Behalten“ gewählt.")),
    Option("MRC_API_TOKEN", "basic", "text", "", requires="MRC_KEEP_ORIGINAL", group=ORIGINAL, secret=True,
           title=("Paperless API token", "API-Token von Paperless"),
           help=("Create it in Paperless under “My Profile” → API token. Needed to attach and delete the original.",
                 "In Paperless unter „Mein Profil“ → API-Token erzeugen. Nötig zum Anhängen und Löschen des "
                 "Originals.")),
    # ---------------------------------------------------------------- Details (nur auf Wunsch)
    Option("MRC_SHARPEN", "advanced", "int", "150", group=QUALITY,
           title=("Sharpening (%)", "Nachschärfen (%)"),
           help=("Keeps faint, thin text crisp. 0 = off (faint text can look patchy); high values make text bolder "
                 "but also emphasize noise.",
                 "Hält blasse, dünne Schrift scharf. 0 = aus (blasse Schrift kann fleckig wirken); hohe Werte machen "
                 "Schrift kräftiger, verstärken aber auch Rauschen.")),
    Option("MRC_SHARPEN_RADIUS", "advanced", "float", "1.5", requires="MRC_SHARPEN", group=QUALITY,
           title=("Sharpening radius (px at 200 dpi)", "Radius Nachschärfen (px bei 200 dpi)"),
           help=("Small = only fine edges (thin strokes can break up), large = visible halos.",
                 "Klein = nur feine Kanten (dünne Striche können aufbrechen), groß = sichtbare Lichthöfe.")),
    Option("MRC_MASK_FACTOR", "advanced", "float", "0.5", group=QUALITY,
           title=("Text mask factor", "Textmaske, Faktor"),
           help=("Smaller = faint text and thin lines also stay sharp, but more specks are kept; 1 = recode_pdf's "
                 "own setting.",
                 "Kleiner = auch blasse Schrift und dünne Linien bleiben scharf, aber mehr Schmutzpunkte; "
                 "1 = Einstellung von recode_pdf selbst.")),
    Option("MRC_BG_DOWNSAMPLE", "advanced", "int", "2", group=QUALITY,
           title=("Background resolution 1/n", "Hintergrundauflösung 1/n"),
           help=("1 = full resolution (best colours and pictures, larger), 4 = smallest (coloured areas get "
                 "blocky). Text always keeps full resolution.",
                 "1 = volle Auflösung (beste Farben und Bilder, größer), 4 = am kleinsten (Farbflächen werden "
                 "blockig). Schrift behält immer die volle Auflösung.")),
    Option("MRC_BG_COMPRESSION_RATE", "advanced", "float", "200", group=QUALITY,
           title=("Background compression rate", "Kompressionsrate des Hintergrunds"),
           help=("50 = barely compressed, 800 = very small (coloured areas and pictures get blotchy).",
                 "50 = kaum komprimiert, 800 = sehr klein (Farbflächen und Bilder werden fleckig).")),
    Option("MRC_MAX_DPI", "advanced", "int", "0", group=QUALITY,
           title=("Maximum resolution (dpi)", "Höchstauflösung (dpi)"),
           help=("Downscale scans above this resolution: faster and smaller, finest details are lost. 0 = off.",
                 "Scans oberhalb dieser Auflösung verkleinern: schneller und kleiner, feinste Details gehen "
                 "verloren. 0 = aus.")),
    Option("MRC_PHOTO_PAPER_PERCENT", "advanced", "float", "50", requires="MRC_SKIP_PHOTOS", group=PAGES,
           title=("Text check below paper area (%)", "Texterkennung prüft unter Papierfläche (%)"),
           help=("Pages with less paper area are only treated as documents if enough text is recognized. "
                 "0 = never check, 100 = check every page.",
                 "Seiten mit weniger Papierfläche gelten nur als Dokument, wenn genug Text erkannt wird. "
                 "0 = nie prüfen, 100 = jede Seite prüfen.")),
    Option("MRC_PHOTO_MIN_WORDS", "advanced", "int", "10", requires="MRC_SKIP_PHOTOS", group=PAGES,
           title=("Photo below confident words", "Foto unter sicher erkannten Wörtern"),
           help=("A checked page counts as a photo with fewer confidently recognized words. 0 = never a photo.",
                 "Eine geprüfte Seite gilt bei weniger sicher erkannten Wörtern als Foto. 0 = nie Foto.")),
    Option("MRC_VECTOR_PAGES", "advanced", "bool", "true", group=PAGES,
           title=("Rasterize vectorized scans", "Vektorisierte Scans rastern"),
           help=("Some scanner software stores pages as thousands of drawing elements; such pages are turned into "
                 "an image, compressed and made searchable.",
                 "Manche Scanner-Software speichert Seiten als Tausende Zeichenelemente; solche Seiten werden in ein "
                 "Bild umgewandelt, komprimiert und durchsuchbar gemacht.")),
    Option("MRC_VECTOR_MIN_ITEMS", "advanced", "int", "1000", requires="MRC_VECTOR_PAGES", group=PAGES,
           title=("Vectorized from elements", "Vektorisiert ab Elementen"),
           help=("A page without image and text counts as a vectorized scan from this many drawing elements.",
                 "Eine Seite ohne Bild und Text gilt ab so vielen Zeichenelementen als vektorisierter Scan.")),
    Option("MRC_VECTOR_DPI", "advanced", "int", "300", requires="MRC_VECTOR_PAGES", group=PAGES,
           title=("Resolution for vectorized scans (dpi)", "Auflösung für vektorisierte Scans (dpi)"),
           help=("Higher = small print sharper, but larger and slower.",
                 "Höher = Kleingedrucktes schärfer, aber größer und langsamer.")),
    Option("MRC_ROTATE_CHECK", "advanced", "bool", "true", requires="PAPERLESS_OCR_ROTATE_PAGES", group=OCR,
           title=("Check uncertain rotation with text recognition", "Unsichere Drehung per Texterkennung prüfen"),
           help=("If the orientation detection is unsure, compare both orientations by recognized words – helps "
                 "with landscape forms scanned in portrait.",
                 "Ist die Lageerkennung unsicher, beide Lagen anhand erkannter Wörter vergleichen – hilft bei quer "
                 "beschriebenen, hochkant gescannten Formularen.")),
    Option("MRC_DESKEW_MIN_ANGLE", "advanced", "float", "0.2", requires="PAPERLESS_OCR_DESKEW", group=OCR,
           title=("Minimum skew (degrees)", "Erst ab Schräglage (Grad)"),
           help=("Smaller skews are left as they are. 0 = correct every detected skew.",
                 "Kleinere Schräglagen bleiben, wie sie sind. 0 = jede erkannte Schräglage korrigieren.")),
    Option("MRC_DESKEW_MAX_ANGLE", "advanced", "float", "5", requires="PAPERLESS_OCR_DESKEW", group=OCR,
           title=("Skew search range ± (degrees)", "Suchbereich Schräglage ± (Grad)"),
           help=("Larger = also strongly skewed pages, but slower.",
                 "Größer = auch stark schiefe Seiten, aber langsamer.")),
    Option("MRC_DESKEW_MIN_CONFIDENCE", "advanced", "float", "1.3", requires="PAPERLESS_OCR_DESKEW", group=OCR,
           title=("Minimum skew clarity", "Mindestdeutlichkeit der Schräglage"),
           help=("1 = always straighten (logos or stamps on pages with little text can tilt a straight page); "
                 "3 = only pages with many clear lines of text.",
                 "1 = immer begradigen (Logos oder Stempel auf textarmen Seiten können eine gerade Seite kippen); "
                 "3 = nur Seiten mit vielen klaren Textzeilen.")),
    Option("MRC_BLANK_INK_PERCENT", "advanced", "float", "0.005", requires="MRC_REMOVE_BLANK_PAGES", group=BLANK,
           title=("Blank below ink share (%)", "Leer unter Tintenanteil (%)"),
           help=("0 = never remove a page; a page with only a page number has about 0.008–0.01 %.",
                 "0 = nie eine Seite entfernen; eine Seite mit nur einer Seitenzahl hat etwa 0,008–0,01 %.")),
    Option("MRC_BLANK_INK_CONTRAST", "advanced", "int", "20", requires="MRC_REMOVE_BLANK_PAGES", group=BLANK,
           title=("Ink contrast for blank (levels)", "Tintenkontrast für leer (Stufen)"),
           help=("How much darker than the paper a mark must be to count as content. Lower = faint content "
                 "(pale photos, faded receipts) is kept; below about 20, show-through can count as content.",
                 "So viel dunkler als das Papier muss etwas sein, um als Inhalt zu zählen. Niedriger = blasse "
                 "Inhalte (helle Fotos, verblasste Belege) bleiben; unter etwa 20 zählt Durchscheinen als Inhalt.")),
    Option("MRC_BLANK_PAPER_PERCENT", "advanced", "float", "90", requires="MRC_REMOVE_BLANK_PAGES", group=BLANK,
           title=("Minimum paper area for blank (%)", "Leer nur ab Papierfläche (%)"),
           help=("Protects low-contrast photos (e.g. of a white wall) from being removed. 100 = practically never "
                 "blank.",
                 "Schützt kontrastarme Fotos (z. B. einer weißen Wand) vor dem Entfernen. 100 = praktisch nie leer.")),
    Option("PAPERLESS_OCR_DESKEW", "advanced", "bool", "true", group=OCR,
           title=("Straighten skewed pages (shared with Paperless)", "Schiefe Seiten begradigen (gilt auch für Paperless)"),
           help=("Only pages without an existing text layer.", "Nur Seiten ohne vorhandene Textebene.")),
    Option("PAPERLESS_OCR_ROTATE_PAGES", "advanced", "bool", "true", group=OCR,
           title=("Turn pages the right way up (shared with Paperless)",
                  "Seiten richtig herum drehen (gilt auch für Paperless)"),
           help=("Only pages without an existing text layer.", "Nur Seiten ohne vorhandene Textebene.")),
    Option("PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD", "advanced", "float", "12", requires="PAPERLESS_OCR_ROTATE_PAGES", group=OCR,
           title=("Minimum rotation confidence (shared with Paperless)",
                  "Mindestsicherheit für Drehung (gilt auch für Paperless)"),
           help=("0 = rotate whenever suggested, higher = only clear cases.",
                 "0 = immer drehen, wenn vorgeschlagen; höher = nur eindeutige Fälle.")),
    Option("MRC_JOBS", "advanced", "int", "", group=OTHER,
           title=("Pages processed at the same time", "Gleichzeitig verarbeitete Seiten"),
           help=("Empty = as Paperless (PAPERLESS_THREADS_PER_WORKER, otherwise cores ÷ task workers).",
                 "Leer = wie Paperless (PAPERLESS_THREADS_PER_WORKER, sonst Kerne ÷ Worker).")),
    Option("MRC_API_URL", "advanced", "text", "", requires="MRC_KEEP_ORIGINAL", group=ORIGINAL,
           title=("Paperless API address", "Adresse der Paperless-API"),
           help=("Empty = http://localhost:<PAPERLESS_PORT or 8000>. Only needed if Paperless runs elsewhere or "
                 "under a sub-path.",
                 "Leer = http://localhost:<PAPERLESS_PORT oder 8000>. Nur nötig, wenn Paperless anderswo oder unter "
                 "einem Unterpfad läuft.")),
    Option("MRC_POPPLER_CHECK", "advanced", "bool", "true", group=OTHER,
           title=("Also check the result with Poppler", "Ergebnis zusätzlich mit Poppler prüfen"),
           help=("Renders the result with pdftoppm and discards it on errors.",
                 "Stellt das Ergebnis mit pdftoppm dar und verwirft es bei Fehlern.")),
    Option("MRC_TIMING", "advanced", "bool", "false", group=OTHER,
           title=("Log the time of each step", "Dauer jedes Schritts ins Log schreiben"),
           help=("For analysis only.", "Nur zur Analyse.")),
    Option("MRC_LANGUAGE", "advanced", "choice", "en", group=OTHER, choices=("en", "de"),
           title=("Language of messages", "Sprache der Meldungen"),
           help=("Log messages, installer and the labels of the field “Original (MRC)”.",
                 "Log-Meldungen, Installer und Beschriftung des Felds „Original (MRC)“.")),
]

BY_KEY = {o.key: o for o in OPTIONS}

# Gelesen, aber keine Einstellung für den Assistenten (von Paperless gesetzt bzw. intern)
NOT_SETTINGS = {"DOCUMENT_ID", "DOCUMENT_WORKING_PATH", "TASK_ID", "PAPERLESS_TASK_WORKERS", "PAPERLESS_PORT",
                "PAPERLESS_THREADS_PER_WORKER", "MRC_PAPERLESS_CONF", "MRC_ORIGINALS_DIR"}
