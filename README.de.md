# paperless-mrc – gescannte PDFs in Paperless-ngx verkleinern

*[English](README.md) · Deutsch*

**paperless-mrc macht gescannte Dokumente in [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) meist 5-
bis 30-mal kleiner – Schrift bleibt scharf, Farben bleiben erhalten, das Dokument bleibt durchsuchbar.** Es läuft
automatisch als Pre-Consume-Skript: Jeder neue Scan wird komprimiert, bevor Paperless ihn speichert. Im Archiv liegt
danach nur noch die kleine Datei.

Dafür nutzt es *Mixed Raster Content* (MRC), das Verfahren hinter kompakten PDF-Archiven wie dem des Internet Archive,
über [archive-pdf-tools](https://github.com/internetarchive/archive-pdf-tools). Die Texterkennung (OCR) übernimmt
[Tesseract](https://github.com/tesseract-ocr/tesseract).

> Am Mac? Die App [PDF MRC](https://github.com/Philoneous/mac-pdf-mrc) komprimiert PDFs mit demselben Verfahren per
> Rechtsklick im Finder – ganz ohne Server.

## Typische Ergebnisse

| Dokument | vorher | nachher |
|---|---:|---:|
| Einseitiger Farbbrief (Testseite, simulierter Bürokopierer-Scan, 300 dpi) | 956 KB | 126 KB |
| Derselbe Brief in 200 dpi | 496 KB | 65 KB |
| Vier echte Handyscans, zusammen 6 Seiten (iPhone/Mac-Scanner) | 12.637 KB | 375 KB |

Kleingedrucktes bis 5 pt, hellgraue und farbige Schrift, Logos, Stempel und Unterschriften bleiben lesbar. Gemessen mit
CCITT-Maske; mit installiertem jbig2enc werden die Dateien noch etwas kleiner.

## So funktioniert es

Eine gescannte Seite ist ein Foto von Papier. MRC zerlegt sie in drei Ebenen, die jeweils passend komprimiert werden:

- **Textebene:** Schrift und Linien als scharfes Schwarz-Weiß-Bild in voller Auflösung, verlustfrei komprimiert
  (JBIG2 oder CCITT) – deshalb bleibt Schrift gestochen scharf.
- **Hintergrund:** Papier, farbige Flächen und Bilder in geringerer Auflösung, komprimiert mit JPEG 2000.
- **Schriftfarbe:** ein kleines Bild, das Buchstaben, Logos und Stempeln ihre Farbe gibt.

Ein normaler Scan speichert jede Seite als ein großes Foto; MRC behält die Details nur dort, wo sie zählen.

## Was mit jedem Dokument passiert

1. **Nur gescannte Seiten werden bearbeitet.** Eine Seite gilt als gescannt, wenn sie aus einem einzigen Seitenbild
   ohne sichtbaren Text besteht. Digitale Seiten (z. B. ein erzeugtes Anschreiben vor einem Scan), Lesezeichen und
   Metadaten bleiben genau so, wie sie sind. Rein digitale PDFs, **digital signierte oder verschlüsselte PDFs** und hochgeladene Bilder
   (JPEG, PNG …) bleiben ganz unverändert.
   - **Fotos bleiben, wie sie sind**, weil MRC sie sichtbar verschlechtern würde. Eine Seite, die überwiegend aus
     Papier besteht, gilt als Dokument; bei allen anderen (Fotos, aber auch Formulare mit grau hinterlegten Feldern)
     entscheidet die Texterkennung.
   - **Vektorisierte Scans** – manche Scanner-Software speichert eine Seite als Tausende Zeichenelemente statt als
     Bild – werden in ein Bild umgewandelt, komprimiert und durchsuchbar gemacht.
2. **Leere Seiten werden entfernt** – z. B. leere Rückseiten beim beidseitigen Scannen. Papierton, Rauschen und
   Durchscheinendes zählen nicht als Inhalt; eine Seite mit nur einer Seitenzahl bleibt, ebenso blasse Seiten (helles
   Foto, verblasster Beleg).
3. **Texterkennung:** Eine vorhandene Textebene (z. B. vom Scanner) bleibt erhalten. Sonst erkennt Tesseract den Text –
   nachdem auf dem Kopf stehende oder quer liegende Seiten gedreht und schiefe Seiten begradigt wurden.
4. **Komprimierung** jeder Seite mit MRC; unplausible Seitengrößen (z. B. Handyscans, die ein Vielfaches von A4 groß
   gespeichert sind) werden auf A4 korrigiert.
5. **Prüfung:** gleiche Seitenzahl, Textebene vollständig, die Datei lässt sich fehlerfrei darstellen und ist kleiner.
   Erst dann wird das Original ersetzt.

Geht **irgendetwas schief**, bleibt die Datei unverändert und Paperless verarbeitet sie wie gewohnt.

## Voraussetzungen

- Paperless-ngx 3.x (getestet mit 3.3.0), installiert **ohne Docker** auf Debian/Ubuntu mit uv und systemd – so wie die
  [Proxmox VE Helper-Scripts](https://community-scripts.github.io/ProxmoxVE/) es einrichten (`/opt/paperless`).
  Docker-Installationen unterstützt der Installer nicht.
- In Paperless: OCR-Modus `auto` (Standard) und Archivdatei-Erzeugung `auto` (Standard) oder `never`. Paperless nutzt
  dann die Textebene der komprimierten Datei, führt keine eigene OCR aus und legt keine zweite Datei an.
- Optional: `jbig2` ([jbig2enc](https://github.com/agl/jbig2enc)) für die kleinsten Dateien; ohne wird CCITT verwendet.

## Installation

Als root im Paperless-Container (bzw. in der VM):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Philoneous/paperless-mrc/main/install.sh)"
```

Der Installer führt durch die Einrichtung:

1. **Sprache** des Installers und der Meldungen (Englisch oder Deutsch).
2. **Die wichtigsten Einstellungen** – OCR-Sprachen, leere Seiten entfernen, Fotos unverändert lassen, PDFs mit
   digitalen Seiten, vorhandene Textebene, Papierformat, Original bis zur Prüfung aufbewahren (mit API-Token, das
   gleich geprüft wird). Enter übernimmt den Wert in Klammern; die Standardwerte sind auf beste Lesbarkeit ausgelegt.
3. **Detaileinstellungen** nur auf Wunsch – nach Gruppen (Qualität und Größe, Seitenauswahl, Texterkennung, leere
   Seiten, Sonstiges), jeweils mit Bereich und Wirkung.

Danach installiert er die Systempakete und OCR-Sprachpakete, richtet paperless-mrc in einer eigenen Python-Umgebung
unter `/opt/paperless-mrc` ein, schreibt nur die vom Standard abweichenden Einstellungen in
`/opt/paperless/paperless.conf` (eine Sicherung liegt daneben), trägt das Pre-Consume-Skript ein und startet
`paperless-task-queue` und `paperless-consumer` neu. Ist schon ein anderes Pre-Consume-Skript eingetragen, bricht er ab.

**Aktualisieren:** denselben Befehl erneut ausführen. Der Installer zeigt die aktuellen Einstellungen und bietet an,
sie zu übernehmen; dann fragt er nur nach Optionen, die seit der letzten Einrichtung dazugekommen sind (keine → keine
Fragen). Man kann auch alle Einstellungen noch einmal durchgehen. **Ohne Fragen** (z. B. in Skripten):
`MRC_YES=1 bash -c "…"` übernimmt die bestehenden Einstellungen. **Entfernen:** die Zeile
`PAPERLESS_PRE_CONSUME_SCRIPT=…` aus `paperless.conf` löschen und beide Dienste neu starten.

## Optional: Original bis zur Prüfung aufbewahren

Normalerweise ersetzt die komprimierte Datei das Original. Wer das Ergebnis erst prüfen möchte, kann paperless-mrc das
Original als zweite **Version** des Dokuments aufbewahren lassen (ab Paperless-ngx 3) und später löschen:

- Die komprimierte Datei wird das Dokument, das Original hängt als Version *Original* daran. In der Dokumentansicht
  lässt sich zwischen beiden Versionen wechseln und vergleichen.
- Ein Auswahlfeld **Original (MRC)** legt fest, was mit dem Original passiert:

  | Auswahl | Wirkung |
  |---|---|
  | **Löschen nach 30 Tagen** (Standard) | Das Original wird nach der Frist automatisch gelöscht (`MRC_KEEP_ORIGINAL_DAYS`) |
  | **Behalten** | Das Original bleibt dauerhaft – z. B. wenn die komprimierte Fassung nicht gut genug ist |
  | **Jetzt löschen** | Das Original wird innerhalb einer Stunde gelöscht – typischerweise nach deiner Prüfung |

- Die Auswahl ist in der Sprache beschriftet, die in Paperless gewählt ist (*Einstellungen → Sprache* des Benutzers,
  dessen API-Token verwendet wird); steht sie auf „Browsersprache“, die der Server nicht kennen kann, auf Englisch.
  `MRC_LANGUAGE` hat Vorrang.
- Nach dem Löschen bleibt nur die kleine komprimierte Datei, und das Feld verschwindet. Filtert man die Dokumentliste
  nach *Original (MRC)*, sieht man also genau die Dokumente, die noch ein Original haben (praktisch als gespeicherte
  Ansicht zum Prüfen).
- Das Löschen übernimmt ein stündlicher Timer (`paperless-mrc-cleanup`). Er löscht nur in eindeutigen Fällen; ein
  unbekannter Wert oder ein gleichnamiges Feld, das nicht von paperless-mrc stammt, lässt alles, wie es ist.

**Einschalten:** im Installer mit *ja* antworten und ein API-Token eingeben (in Paperless unter *Mein Profil*
erzeugen). Standardmäßig ist die Option aus. Ohne Fragen: `KEEP_ORIGINAL=1 MRC_YES=1 bash -c "…"`, danach das Token als
`MRC_API_TOKEN=<token>` in `/opt/paperless/paperless.conf` eintragen und `paperless-task-queue` sowie
`paperless-consumer` neu starten. Der
Installer richtet Post-Consume-Skript, den Ordner `/opt/paperless-mrc/originals` und den Timer ein; ist schon ein anderes
Post-Consume-Skript eingetragen, bricht er ab. **Ausschalten:** im Installer mit *nein* antworten (oder
`MRC_KEEP_ORIGINAL=false` setzen und beide Dienste neu starten) – neue Dokumente ersetzen dann wieder das Original, und
der Timer erledigt die schon vorhandenen Originale weiter.

Gut zu wissen:
- Bis zum Löschen belegt das Original so viel Platz wie bisher. Hat das Original keine Textebene, erkennt Paperless
  den Text dieser Version außerdem selbst noch einmal, das kostet etwas Rechenzeit auf dem Server.
- Gelöschte Versionen legt Paperless in den Papierkorb; der Platz wird frei, wenn der Papierkorb geleert wird
  (standardmäßig nach 30 Tagen, `PAPERLESS_EMPTY_TRASH_DELAY`).
- Lässt sich das Original nicht zurücklegen, wird die Datei gar nicht komprimiert – ein Original geht nie verloren.
  Scheitert das Anhängen (z. B. weil das Token fehlt), bleibt es in `/opt/paperless-mrc/originals`, und der Timer hängt
  es später an.

## Einstellungen

Ohne Einstellungen gelten die Standardwerte; sie sind auf die beste Lesbarkeit des Ergebnisses ausgelegt. paperless-mrc
übernimmt diese Paperless-Einstellungen aus `paperless.conf`:

| Variable | Wirkung |
|---|---|
| `PAPERLESS_OCR_LANGUAGE` | Tesseract-Sprachen, z. B. `deu+eng` |
| `PAPERLESS_OCR_DESKEW` | Schiefe Seiten begradigen (nur Seiten ohne vorhandene Textebene) |
| `PAPERLESS_OCR_ROTATE_PAGES` | Seiten richtig herum drehen (nur Seiten ohne vorhandene Textebene) |
| `PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD` | Wie sicher die Lageerkennung sein muss, bevor gedreht wird (0–100, Standard 12) |
| `PAPERLESS_THREADS_PER_WORKER` | Gleichzeitig verarbeitete Seiten (Standard wie in Paperless: Kerne ÷ `PAPERLESS_TASK_WORKERS`) |

Werte, die nur in der Weboberfläche (*Konfiguration*) gesetzt sind, sieht das Skript nicht; deshalb trägt der
Installer die OCR-Sprachen zusätzlich in `paperless.conf` ein.

Weitere Einstellungen, ebenfalls in `paperless.conf`. Werte außerhalb des Bereichs werden auf ihn begrenzt; ein
ungültiger Wert (keine Zahl) wird durch den Standard ersetzt und im Log gemeldet.

| Variable | Standard | Bereich | Wirkung |
|---|---|---|---|
| **Qualität und Größe** | | | |
| `MRC_SHARPEN` | `150` | 0–300 | Nachschärfen in % vor dem Komprimieren, damit blasse, dünne Schrift scharf bleibt. 0 = aus (blasse Schrift kann fleckig wirken); hohe Werte machen Schrift kräftiger, verstärken aber auch Rauschen und Flecken |
| `MRC_SHARPEN_RADIUS` | `1.5` | 0,5–5 | Breite des Nachschärfens in Pixeln bei 200 dpi (wird mit der Auflösung skaliert). Klein = nur feine Kanten, groß = sichtbare Lichthöfe |
| `MRC_MASK_FACTOR` | `0.5` | 0,1–1 | Welche Pixel in die scharfe Textebene kommen. Kleiner = auch blasse Schrift und dünne Linien bleiben scharf, aber mehr Schmutzpunkte bleiben erhalten; 1 = Einstellung von recode_pdf selbst (blasse Schrift kann unscharf werden) |
| `MRC_BG_DOWNSAMPLE` | `2` | 1–4 | Hintergrund in 1/n der Scan-Auflösung (Schrift bleibt immer in voller Auflösung). 1 = beste Farben und Bilder, größer; 4 = am kleinsten, Farbflächen werden blockig |
| `MRC_BG_COMPRESSION_RATE` | `200` | 50–800 | JPEG-2000-Kompression des Hintergrunds. 50 = kaum komprimiert; 800 = sehr klein, Farbflächen und Bilder werden fleckig |
| `MRC_MAX_DPI` | `0` | 0, 150–1200 | Scans oberhalb dieser Auflösung vor dem Komprimieren verkleinern: schneller und kleiner, feinste Details gehen verloren. 0 = aus (Auflösung des Scans bleibt) |
| `MRC_FIT_A4` | `true` | | Unplausibel große Seitenformate (kürzere Seite größer als A3, z. B. 72-ppi-Handyscans) auf das Zielformat verkleinern |
| `MRC_FIT_PAGE_SIZE` | `a4` | `a4`, `letter`, `legal` | Zielformat dafür (Seitenverhältnis bleibt) |
| **Seitenauswahl** | | | |
| `MRC_MIXED_PDFS` | `true` | | Auch PDFs mit digitalen Seiten bearbeiten (diese bleiben unverändert); `false` = nur PDFs, die ganz aus Scans bestehen |
| `MRC_SKIP_PHOTOS` | `true` | | Fotoseiten unverändert lassen |
| `MRC_PHOTO_PAPER_PERCENT` | `50` | 0–100 | Seiten mit weniger Papierfläche (in %) prüft die Texterkennung. 0 = nie prüfen (jede Seite gilt als Dokument), 100 = jede Seite prüfen. Dokumente auf weißem Papier haben typisch 60–98 %, Fotos 10–45 % |
| `MRC_PHOTO_MIN_WORDS` | `10` | 0–100 | Eine geprüfte Seite gilt bei weniger sicher erkannten Wörtern (≥ 3 Zeichen) als Foto. 0 = nie Foto |
| `MRC_VECTOR_PAGES` | `true` | | Vektorisierte Scans in ein Bild umwandeln, komprimieren und durchsuchbar machen |
| `MRC_VECTOR_MIN_ITEMS` | `1000` | 1–100.000 | Eine Seite ohne Bild und Text gilt ab so vielen Zeichenelementen als vektorisierter Scan. Niedrige Werte wandeln auch einfache digitale Zeichnungen um |
| `MRC_VECTOR_DPI` | `300` | 150–600 | Auflösung für vektorisierte Scans. Höher = Kleingedrucktes schärfer, aber größer und langsamer |
| **Texterkennung** | | | |
| `MRC_KEEP_TEXT_LAYER` | `true` | | Vorhandene Textebene übernehmen; `false` = immer neu erkennen (Seiten werden dann auch gedreht und begradigt) |
| `MRC_ROTATE_CHECK` | `true` | | Ist die Lageerkennung unsicher, schlägt aber eine Drehung vor, wird der Text in beiden Lagen erkannt und nur gedreht, wenn das deutlich mehr Wörter ergibt – hilft bei quer beschriebenen, hochkant gescannten Formularen |
| `MRC_DESKEW_MIN_ANGLE` | `0.2` | 0–2 | Kleinere Schräglagen (Grad) bleiben, wie sie sind. 0 = jede erkannte Schräglage korrigieren |
| `MRC_DESKEW_MAX_ANGLE` | `5` | 0,5–45 | Suchbereich ± in Grad. Größer = auch stark schiefe Seiten, aber langsamer. Ein Ergebnis am Rand des Bereichs gilt als unklar und wird nicht korrigiert |
| `MRC_DESKEW_MIN_CONFIDENCE` | `1.3` | 1–3 | Nur begradigen, wenn der beste Winkel deutlich heraussticht. 1 = immer (Logos oder Stempel auf textarmen Seiten können eine gerade Seite kippen); 3 = nur Seiten mit vielen klaren Textzeilen |
| **Leere Seiten** | | | |
| `MRC_REMOVE_BLANK_PAGES` | `true` | | Leere gescannte Seiten entfernen |
| `MRC_BLANK_INK_PERCENT` | `0.005` | 0–1 | Eine Seite ist leer unterhalb dieses Tintenanteils in %. 0 = nie entfernen; eine Seite mit nur einer Seitenzahl hat etwa 0,01 % |
| `MRC_BLANK_INK_CONTRAST` | `20` | 10–100 | Für die Leerseitenprüfung zählt ein Pixel als Tinte, wenn er so viele Helligkeitsstufen dunkler ist als das Papier ringsum. Kleiner = schon blasser Inhalt hält eine Seite (10: auch kräftiges Durchscheinen); größer = nur deutliche Zeichen zählen (40 = Verhalten vor 11/2026: blasse Fotos und verblasste Belege wurden entfernt) |
| `MRC_BLANK_PAPER_PERCENT` | `90` | 0–100 | Eine Seite kann nur leer sein, wenn mindestens dieser Anteil (%) wie Papier aussieht – schützt kontrastarme Fotos (z. B. einer weißen Wand) |
| **Sonstiges** | | | |
| `MRC_JOBS` | – | 1–64 | Gleichzeitig verarbeitete Seiten; überschreibt `PAPERLESS_THREADS_PER_WORKER` |
| `MRC_POPPLER_CHECK` | `true` | | Ergebnis zusätzlich mit Poppler (`pdftoppm`) darstellen und bei Fehlern verwerfen |
| `MRC_LANGUAGE` | `en` | | Sprache der Log-Meldungen: `en` oder `de` |
| `MRC_TIMING` | `false` | | Dauer jedes Schritts je Seite ins Log schreiben |
| **Original aufbewahren (optional)** | | | |
| `MRC_KEEP_ORIGINAL` | `false` | | Original bis zur Prüfung als Version aufbewahren (siehe oben) |
| `MRC_KEEP_ORIGINAL_DAYS` | `30` | 1–3650 | Standardfrist, nach der das Original gelöscht wird |
| `MRC_API_TOKEN` | – | | API-Token von Paperless (aus *Mein Profil*), nötig zum Anhängen und Löschen von Versionen |
| `MRC_API_URL` | `http://localhost:8000` | | Adresse der Paperless-API aus dem Container (Port aus `PAPERLESS_PORT`) |
| `MRC_ORIGINALS_DIR` | `/opt/paperless-mrc/originals` | | Hier warten Originale, bis sie angehängt sind |

Bewusst **nicht** einstellbar: Digital signierte PDFs bleiben unverändert (die Signatur würde sonst ungültig), und das
Original wird nur ersetzt, wenn das Ergebnis die Prüfung bestanden hat und kleiner ist.

## Log-Ausgabe

Meldungen erscheinen im Paperless-Log mit dem Präfix `paperless-mrc:` (standardmäßig Englisch, Deutsch mit
`MRC_LANGUAGE=de`). Zusätzlich gibt es je Dokument eine maschinenlesbare Zeile:

```
paperless-mrc-result: {"version": 1, "file": "scan.pdf", "status": "compressed", "reason": "compressed",
  "size_before": 1482508, "size_after": 46886, "pages": 1, "blank_removed": 1, "photos": 0, "vectorised": 0,
  "digital": 0, "text_layer": "ocr"}
```

- `status`: `compressed`, `unchanged` oder `error`
- `reason`: `compressed`, `not_pdf`, `signed`, `encrypted`, `original_version`, `no_scanned_pages`, `mixed_disabled`, `nothing_to_compress`
  (mit `photos`, `blank`), `not_smaller` (mit Größen), `error` (mit `message`)
- Größen in Bytes; `text_layer`: `kept`, `ocr` oder `mixed`

## Gut zu wissen

- **Die Komprimierung ist verlustbehaftet:** Standardmäßig wird das Original ersetzt; danach gibt es nur noch die
  komprimierte Fassung. Wer erst prüfen möchte, schaltet das
  [Aufbewahren des Originals](#optional-original-bis-zur-prüfung-aufbewahren) ein.
- **Duplikaterkennung:** Paperless vergleicht die Prüfsumme einer eingehenden Datei mit der gespeicherten. Da die
  komprimierte Fassung gespeichert ist, erkennt Paperless ein erneut hochgeladenes, identisches Original nicht mehr als
  Duplikat (solange das Original als Version aufbewahrt wird, schon).
- **„Erneut verarbeiten“** in Paperless führt paperless-mrc nicht erneut aus (die Datei ist bereits komprimiert).
- Anmerkungen (Kommentare, Markierungen) auf gescannten Seiten werden ins Bild eingebrannt und sind danach nicht mehr
  bearbeitbar.
- Seiten mit vorhandener Textebene werden nicht gedreht oder begradigt, weil die Textebene sonst nicht mehr passt.

## Unterstützen

paperless-mrc ist kostenlos. Wenn es dir Zeit oder Speicherplatz spart, kannst du die Entwicklung auf
[Ko-fi](https://ko-fi.com/Philoneous) unterstützen (PayPal oder Karte, kein Konto nötig) – auch über den
*Sponsor*-Knopf oben auf dieser Seite. Beiträge sind freiwillig und keine steuerlich absetzbaren Spenden.

## Entwicklung

**Neue Einstellung?** In `src/paperless_mrc/catalog.py` mit `since=REVISION + 1` eintragen und `REVISION` erhöhen.
Der Installer fragt bestehende Nutzer dann beim nächsten Update danach; `tests/test_catalog.py` schlägt fehl, wenn eine
im Code gelesene Einstellung im Katalog fehlt oder ihr Standard abweicht.

```bash
uv sync
uv run pytest                                                   # synthetische Testdokumente
PAPERLESS_MRC_TESTFILES=/pfad/zu/scans uv run pytest -k echte    # optional: eigene Scans
```

Benötigt `tesseract` (mit `deu`), `opj_compress` (libopenjp2-tools) und `pdftoppm` (poppler-utils; mit
`MRC_POPPLER_CHECK=false` nicht nötig).

## Lizenz

Copyright (C) 2026 Philoneous. GNU Affero General Public License v3.0 oder später (`AGPL-3.0-or-later`), siehe
[LICENSE](LICENSE) – passend zu den AGPL-lizenzierten Abhängigkeiten PyMuPDF und archive-pdf-tools.

Die MRC-Kodierung übernehmen [archive-pdf-tools](https://github.com/internetarchive/archive-pdf-tools) und
[archive-hocr-tools](https://github.com/internetarchive/archive-hocr-tools) des Internet Archive (AGPL-3.0), die
PDF-Verarbeitung [PyMuPDF](https://github.com/pymupdf/PyMuPDF)/MuPDF von Artifex (AGPL-3.0) und
[pikepdf](https://github.com/pikepdf/pikepdf) (MPL-2.0), die Texterkennung
[Tesseract](https://github.com/tesseract-ocr/tesseract) (Apache-2.0). paperless-mrc ist ein unabhängiges Projekt und
steht in keiner Verbindung zu Paperless-ngx oder dem Internet Archive.
