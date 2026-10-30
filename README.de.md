# paperless-mrc

*[English](README.md) · Deutsch*

Pre-Consume-Skript für [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) (getestet mit 3.3.0).
Es verkleinert gescannte PDFs per *Mixed Raster Content* (MRC, [archive-pdf-tools](https://github.com/internetarchive/archive-pdf-tools)),
bevor Paperless sie verarbeitet. Paperless speichert danach nur noch diese eine, kleine Datei.

MRC zerlegt jede Seite in eine verlustfrei komprimierte Schwarz-Weiß-Maske (Text, Linien) und zwei stark komprimierte
Farbebenen (Hintergrund, Farben von Logos, Stempeln, Unterschriften). Farbe bleibt also erhalten, wo sie vorkommt.

## Ergebnis mit echten Scans

Vier Handyscans (macOS/iOS-Scanfunktion, verlustfrei gespeicherte Seitenbilder, 6 Seiten):

| Datei | vorher | nachher |
|---|---:|---:|
| 1 Seite | 3.767 KB | 75 KB |
| 2 Seiten | 5.832 KB | 139 KB |
| 1 Seite | 2.477 KB | 66 KB |
| 2 Seiten | 559 KB | 95 KB |
| **Summe** | **12.637 KB** | **375 KB** |

Die vorhandene Textebene blieb vollständig erhalten, Logos blieben farbig, Kleingedrucktes lesbar.
Die Maske war dabei CCITT-komprimiert; mit jbig2enc werden die Dateien noch etwas kleiner.

## Was das Skript tut

1. **Nur gescannte Seiten:** Eine Seite gilt als Scan, wenn sie aus genau einem Seitenbild besteht, ohne sichtbaren Text.
   Nur diese Seiten werden neu kodiert. Andere Seiten (z. B. ein angehängtes digitales Anschreiben), Lesezeichen und
   Metadaten bleiben unverändert. Rein digitale PDFs, digital signierte PDFs und direkt hochgeladene Bilder
   (JPEG, PNG …) bleiben ganz unverändert.
   - **Fotos** (z. B. Schadensfotos) lässt das Skript unverändert, weil MRC sie sichtbar verschlechtert. Seiten mit
     überwiegend Papierfläche gelten als Dokument. Bei allen anderen – Fotos, aber auch grau oder farbig hinterlegte
     Textblöcke wie in Versicherungsscheinen – entscheidet die Texterkennung: Nur mit genug sicher erkannten Wörtern ist
     es ein Dokument. Seiten fast ohne Kontrast, die kein Papier sind (z. B. Foto einer Wand), bleiben unverändert und
     werden nie als leer entfernt.
   - **Vektorisierte Scans** (manche Scanprogramme speichern Seiten als Tausende Vektorelemente ohne Text) werden
     mit 300 dpi gerastert, komprimiert und per Tesseract durchsuchbar gemacht.
2. **Leere Seiten entfernen:** nur wirklich leere gescannte Seiten. Papierton, Rauschen und durchscheinende Rückseiten zählen nicht
   als Inhalt; eine Seite mit nur einer Seitenzahl bleibt erhalten.
3. **Seiten rendern** in nativer Auflösung, einschließlich darübergelegter Grafiken (z. B. Markierungen).
4. **Textebene:** Eine vorhandene Textebene (z. B. von der iOS-Scanfunktion) wird übernommen. Sonst erkennt Tesseract den Text,
   vorher werden Seiten bei Bedarf gedreht und begradigt. Ist die Schräglage nicht eindeutig (Messwert am Rand des
   Suchbereichs, z. B. bei Seiten ohne Textzeilen), wird nicht begradigt.
5. **MRC-Kodierung** je Seite (Hintergrund halbe Auflösung, JPEG2000), offensichtlich falsche Seitengrößen
   (z. B. 61 × 86 cm bei Handyscans) werden auf A4 korrigiert.
6. **Prüfung:** Seitenzahl, Vollständigkeit der übernommenen Textebene und des Texts digitaler Seiten, fehlerfreie Darstellung mit Poppler, kleinere Datei.
   Nur dann wird die Arbeitskopie ersetzt.

Bei **jedem Fehler** bleibt die Datei unverändert und Paperless verarbeitet sie wie bisher.

## Voraussetzungen

- Paperless-ngx 3.x, uv-basierte Installation (Layout der [community-scripts](https://community-scripts.github.io/ProxmoxVE/)).
- `PAPERLESS_OCR_MODE` auf `auto` (Standard) und `PAPERLESS_ARCHIVE_FILE_GENERATION` auf `auto` (Standard) oder `never`.
  Dann erkennt Paperless die Textebene der komprimierten Datei, führt kein eigenes OCR mehr aus und legt keine zweite Datei an.
- Optional `jbig2` (jbig2enc) für die kleinste Maske; ohne wird CCITT verwendet.

## Installation

Im Paperless-Container als root:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Philoneous/paperless-mrc/main/install.sh)"
```

(Bei einem privaten Repo stattdessen das Repo klonen und `bash install.sh` ausführen.)

Der Installer
- installiert die Systempakete (OpenJPEG-Werkzeuge, Poppler, Tesseract-Sprachpakete),
- legt das Skript in einer eigenen Python-Umgebung unter `/opt/paperless-mrc` an,
- trägt in `/opt/paperless/paperless.conf` `PAPERLESS_PRE_CONSUME_SCRIPT` und – falls noch nicht vorhanden –
  `PAPERLESS_OCR_LANGUAGE` ein (Sicherung der Datei daneben),
- bricht ab, wenn dort bereits ein anderes Pre-Consume-Skript steht,
- startet `paperless-task-queue` und `paperless-consumer` neu.

**Update:** denselben Befehl erneut ausführen. **Entfernen:** die Zeile `PAPERLESS_PRE_CONSUME_SCRIPT=…` löschen und die
beiden Dienste neu starten.

Die Ausgaben stehen im Paperless-Log mit dem Präfix `paperless-mrc:` – standardmäßig auf Englisch, mit
`MRC_LANGUAGE=de` auf Deutsch. Zusätzlich schreibt das Skript je Dokument eine maschinenlesbare Zeile
`paperless-mrc-result: {…}` (JSON, sprachunabhängig; Felder siehe englisches README), die z. B. die Mac-App auswertet.

## Konfiguration

Das Skript übernimmt diese Paperless-Einstellungen aus `paperless.conf` (mit denselben Standardwerten):

| Variable | Wirkung im Skript |
|---|---|
| `PAPERLESS_OCR_LANGUAGE` | Tesseract-Sprachen, z. B. `deu+eng` |
| `PAPERLESS_OCR_DESKEW` | Schräglage korrigieren (nur Seiten ohne vorhandene Textebene) |
| `PAPERLESS_OCR_ROTATE_PAGES` | Seiten drehen (nur Seiten ohne vorhandene Textebene) |
| `PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD` | Mindestsicherheit der Drehungserkennung |
| `PAPERLESS_THREADS_PER_WORKER` | Seiten, die gleichzeitig verarbeitet werden (Standard wie Paperless: Kerne ÷ `PAPERLESS_TASK_WORKERS`) |

Werte, die nur in der Weboberfläche unter *Konfiguration* gesetzt sind, sieht das Skript nicht – deshalb trägt der
Installer die Sprachen zusätzlich in `paperless.conf` ein.

Eigene Einstellungen (optional, ebenfalls in `paperless.conf`; ohne Eintrag gilt der Standardwert):

| Variable | Standard | Wirkung |
|---|---|---|
| `MRC_REMOVE_BLANK_PAGES` | `true` | Leere gescannte Seiten entfernen |
| `MRC_BLANK_INK_PERCENT` | `0.005` | Seite gilt als leer unter diesem Tintenanteil in % (eine Seitenzahl liegt bei ca. 0,05 %) |
| `MRC_BG_DOWNSAMPLE` | `2` | Hintergrund in 1/n der Scan-Auflösung (Text und Linien bleiben in voller Auflösung) |
| `MRC_BG_COMPRESSION_RATE` | `200` | JPEG2000-Kompressionsrate des Hintergrunds; höher = kleiner, aber Farbflächen und hellgraue Schrift leiden |
| `MRC_FIT_A4` | `true` | Offensichtlich falsche Seitengrößen (z. B. 72-ppi-Handyscans) auf A4 skalieren |
| `MRC_SKIP_PHOTOS` | `true` | Fotoseiten unverändert lassen |
| `MRC_PHOTO_PAPER_PERCENT` | `50` | Seiten mit weniger Papierfläche in % werden per Texterkennung geprüft (gemessen: Dokumente auf weißem Papier 61–98 %, Fotos 11–43 %, farbig hinterlegte Versicherungsseiten darunter) |
| `MRC_PHOTO_MIN_WORDS` | `10` | … und gelten unter so vielen sicher erkannten Wörtern (Konfidenz ≥ 60, ≥ 3 Zeichen) als Foto |
| `MRC_BLANK_PAPER_PERCENT` | `90` | Leer kann eine Seite nur sein, wenn mindestens dieser Flächenanteil in % Papierton ist (schützt kontrastarme Fotos) |
| `MRC_VECTOR_PAGES` | `true` | Vektorisierte Scans rastern und komprimieren |
| `MRC_VECTOR_MIN_ITEMS` | `1000` | Seite ohne Bild und Text gilt ab so vielen Vektorelementen als vektorisierter Scan |
| `MRC_VECTOR_DPI` | `300` | Rasterauflösung für vektorisierte Scans |
| `MRC_DESKEW_MIN_ANGLE` | `0.2` | Kleinere Schräglagen (in Grad) werden nicht korrigiert |
| `MRC_DESKEW_MAX_ANGLE` | `5` | Gesuchter Bereich ± in Grad; ein Ergebnis am Rand gilt als unklar und wird nicht korrigiert |
| `MRC_DESKEW_MIN_CONFIDENCE` | `1.3` | Nur begradigen, wenn sich der beste Winkel deutlich abhebt (Bewertung ≥ Faktor × Median über den Suchbereich). Verhindert, dass Logos oder Stempel auf textarmen Seiten eine gerade Seite schief drehen |
| `MRC_MIXED_PDFS` | `true` | PDFs mit nicht gescannten Seiten bearbeiten (diese Seiten bleiben unverändert); `false`: nur reine Scan-PDFs |
| `MRC_KEEP_TEXT_LAYER` | `true` | Vorhandene Textebene übernehmen; `false`: immer neu mit Tesseract erkennen (dann auch drehen/begradigen) |
| `MRC_ROTATE_CHECK` | `true` | Ist sich die Ausrichtungserkennung unsicher (unter `PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD`), schlägt aber eine Drehung vor: Texterkennung in beiden Lagen, gedreht wird nur bei mindestens 1,5-mal so vielen (und mindestens 10) sicher erkannten Wörtern – z. B. hochkant gescannte Querformat-Formulare |
| `MRC_POPPLER_CHECK` | `true` | Ergebnis zusätzlich mit Poppler rendern (`pdftoppm`, so liest Paperless es) und bei Fehlern verwerfen; `false`: auslassen (z. B. wenn ein anderer Darsteller prüft) |
| `MRC_JOBS` | – | Seiten, die gleichzeitig verarbeitet werden; überschreibt `PAPERLESS_THREADS_PER_WORKER` (sonst Kerne ÷ `PAPERLESS_TASK_WORKERS`) |
| `MRC_SHARPEN` | `150` | Nachschärfen vor der Kodierung in % (Unscharfmaskierung); hellgraue, dünne Schrift landet sonst teils im verkleinerten Hintergrund und wirkt unscharf. `0` = aus |
| `MRC_SHARPEN_RADIUS` | `1.5` | Radius des Nachschärfens in Pixeln bei 200 dpi (wird mit der Auflösung skaliert) |
| `MRC_MASK_FACTOR` | `0.5` | Empfindlichkeit der scharfen Textmaske (Faktor auf die Sauvola-Schwellen von recode_pdf): kleiner = auch hellgraue Striche bleiben scharf statt im verkleinerten Hintergrund zu landen; `1` = recode_pdf-Standard |
| `MRC_MAX_DPI` | `0` | Höchstauflösung in dpi für komprimierte Seiten (z. B. `300`); höher aufgelöste Scans werden herunterskaliert – schneller und kleiner, feinste Details gehen verloren. `0` = aus |
| `MRC_TIMING` | `false` | Laufzeiten je Seite und Arbeitsschritt ins Log schreiben (zur Analyse) |
| `MRC_LANGUAGE` | `en` | Sprache der Meldungen im Log: `en` oder `de` |

Bewusst **nicht** abschaltbar: digital signierte PDFs bleiben unverändert (sonst wird die Signatur ungültig), und die
Datei wird nur ersetzt, wenn die Prüfung bestanden ist und das Ergebnis kleiner ist.

## Einschränkungen

- **Verlustbehaftet:** Das Original wird ersetzt; es gibt danach nur noch die MRC-Version.
- **Duplikaterkennung:** Paperless vergleicht die eingehende Datei mit der gespeicherten. Da gespeichert wird, was das Skript
  erzeugt, erkennt Paperless ein erneut hochgeladenes, byte-identisches Original nicht mehr als Duplikat.
- **„Erneut verarbeiten“** in Paperless führt das Skript nicht noch einmal aus (die Datei ist ja bereits komprimiert).
- Anmerkungen (Kommentare, Markierungen) auf gescannten Seiten werden ins Seitenbild übernommen und sind danach
  nicht mehr bearbeitbar.
- Seiten mit vorhandener Textebene werden nicht gedreht oder begradigt, weil die Textebene sonst nicht mehr zum Bild passt.

## Entwicklung

```bash
uv sync
uv run pytest                                   # synthetische Testfälle
PAPERLESS_MRC_TESTFILES=/pfad/zu/scans uv run pytest -k echte   # optional: eigene Scans
```

Benötigt `tesseract` (mit `deu`), `opj_compress` (libopenjp2-tools) und `pdftoppm` (poppler-utils; mit `MRC_POPPLER_CHECK=false` nicht nötig).

## Lizenz

Copyright (C) 2026 Philoneous. GNU Affero General Public License v3.0 oder später (`AGPL-3.0-or-later`), siehe
[LICENSE](LICENSE) – passend zu den AGPL-lizenzierten Abhängigkeiten PyMuPDF und archive-pdf-tools.

Die MRC-Kodierung übernehmen [archive-pdf-tools](https://github.com/internetarchive/archive-pdf-tools) und
[archive-hocr-tools](https://github.com/internetarchive/archive-hocr-tools) des Internet Archive (AGPL-3.0), die
PDF-Verarbeitung [PyMuPDF](https://github.com/pymupdf/PyMuPDF)/MuPDF von Artifex (AGPL-3.0) und
[pikepdf](https://github.com/pikepdf/pikepdf) (MPL-2.0), die Texterkennung
[Tesseract](https://github.com/tesseract-ocr/tesseract) (Apache-2.0). paperless-mrc ist ein unabhängiges Projekt und
weder mit Paperless-ngx noch mit dem Internet Archive verbunden oder von ihnen unterstützt.
