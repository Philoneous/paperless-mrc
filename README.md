# paperless-mrc

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
2. **Leere Seiten entfernen:** nur wirklich leere gescannte Seiten. Papierton, Rauschen und durchscheinende Rückseiten zählen nicht
   als Inhalt; eine Seite mit nur einer Seitenzahl bleibt erhalten.
3. **Seiten rendern** in nativer Auflösung, einschließlich darübergelegter Grafiken (z. B. Markierungen).
4. **Textebene:** Eine vorhandene Textebene (z. B. von der iOS-Scanfunktion) wird übernommen. Sonst erkennt Tesseract den Text,
   vorher werden Seiten bei Bedarf gedreht und begradigt.
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

Die Ausgaben stehen im Paperless-Log mit dem Präfix `paperless-mrc:`.

## Mac: Finder-Schnellaktion

Dieselbe Verarbeitung gibt es als Rechtsklick-Eintrag im Finder (*Schnellaktionen → PDF komprimieren (MRC)*).
Sie legt je ausgewählter PDF `<Name> (komprimiert).pdf` daneben an; das Original bleibt unverändert. Ist keine
Verkleinerung möglich (keine reine Scan-PDF, Ergebnis nicht kleiner, Fehler), entsteht keine Datei. Das Ergebnis
erscheint als Mitteilung.

Installation als normaler Benutzer, [Homebrew](https://brew.sh) vorausgesetzt:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Philoneous/paperless-mrc/main/macos/install.sh)"
```

Der Installer installiert per Homebrew Tesseract mit allen Sprachpaketen (`tesseract-lang`, großer Download),
OpenJPEG, Poppler, jbig2enc und uv, legt paperless-mrc mit `uv tool install` an und schreibt die Schnellaktion nach
`~/Library/Services`. **Update:** denselben Befehl erneut ausführen. **Entfernen:**
`uv tool uninstall paperless-mrc`, `~/.local/bin/pdf-mrc` und `~/Library/Services/PDF komprimieren (MRC).workflow` löschen.

Tesseract-Sprachen: `deu+eng+pol`, änderbar in `~/.local/bin/pdf-mrc` (`PAPERLESS_OCR_LANGUAGE`). Erscheint der
Eintrag nicht, unter *Systemeinstellungen → Tastatur → Tastaturkurzbefehle → Dienste* prüfen, ob er aktiviert ist.
Für Apple-Silicon-Macs gibt es fertige Pakete aller Python-Abhängigkeiten; auf Intel-Macs muss archive-pdf-tools
aus dem Quellcode gebaut werden (Xcode Command Line Tools).

## Konfiguration

Das Skript übernimmt diese Paperless-Einstellungen aus `paperless.conf` (mit denselben Standardwerten):

| Variable | Wirkung im Skript |
|---|---|
| `PAPERLESS_OCR_LANGUAGE` | Tesseract-Sprachen, z. B. `deu+eng+pol` |
| `PAPERLESS_OCR_DESKEW` | Schräglage korrigieren (nur Seiten ohne vorhandene Textebene) |
| `PAPERLESS_OCR_ROTATE_PAGES` | Seiten drehen (nur Seiten ohne vorhandene Textebene) |
| `PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD` | Mindestsicherheit der Drehungserkennung |
| `PAPERLESS_THREADS_PER_WORKER` | Seiten, die gleichzeitig verarbeitet werden (Standard wie Paperless: Kerne ÷ `PAPERLESS_TASK_WORKERS`) |

Werte, die nur in der Weboberfläche unter *Konfiguration* gesetzt sind, sieht das Skript nicht – deshalb trägt der
Installer die Sprachen zusätzlich in `paperless.conf` ein.

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

Benötigt `tesseract` (mit `deu`), `opj_compress` (libopenjp2-tools) und `pdftoppm` (poppler-utils).

## Lizenz

GNU Affero General Public License v3.0 oder später (`AGPL-3.0-or-later`), siehe [LICENSE](LICENSE) –
passend zu den AGPL-lizenzierten Abhängigkeiten PyMuPDF und archive-pdf-tools.
