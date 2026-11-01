# Testseiten (echte Scans)

Eine Vorlage mit 11 Seiten, die ausgedruckt und wieder eingescannt wird. Sie liefert echte Scans (Druckraster,
Papier, Scanner-Schärfe, Einzug) für alle Zweige der Verarbeitung: Dokument, Leerseite, Foto, Drehung, Begradigung.
Jede Seite prüft einen eigenen Zweig; unabhängige Prüfungen teilen sich eine Seite (z. B. Drehung und Begradigung).
Die Fallliste mit Soll-Ergebnis je Seite erzeugt das Skript (`faelle.md`, `expected.json`).

```bash
uv run --with reportlab --with opencv-python-headless python bench/printset/make_printset.py printset
```

Die Soll-Ergebnisse folgen den Standardwerten. Sie wurden vor dem Druck mit einem simulierten Scan (200 und 300 dpi)
nach den Formeln aus `main.py` geprüft; „Befund“ markiert Fälle, bei denen schon die Simulation eine Schwäche zeigt.

## Drucken

- Farbdrucker, normales weißes Papier, einseitig, tatsächliche Größe / 100 % (nicht „an Seite anpassen“).
- Seite 3 ist fast leer; lässt der Drucker sie aus, ein unbedrucktes Blatt einlegen.

## Vor dem Scannen

Auf Seite 1 die Felder A–E von Hand ausfüllen (Kugelschreiber blau, Bleistift ganz leicht, Textmarker, Rotstift,
Unterschrift).

## Scannen

- Alle Seiten als ein Scan, Reihenfolge beibehalten, Blätter gerade einlegen.
- 300 dpi Farbe; wenn möglich zusätzlich 200 dpi Farbe.
- Komprimierung („hohe Komprimierung“, MRC) und Texterkennung des Scanners aus: paperless-mrc bearbeitet nur Seiten
  aus genau einem Bild ohne sichtbaren Text.
- Dateiname z. B. `testseiten_300.pdf`.

## Nicht per Druck und Scan erzeugbar

Wird aus dem Scan abgeleitet: digitale und gescannte Seiten gemischt (`MRC_MIXED_PDFS`), digital signierte PDFs,
Anmerkungen auf Scan-Seiten, vektorisierte Scans (`MRC_VECTOR_PAGES`), übergroße Seiten (`MRC_FIT_A4`), vorhandene
Textebene (`MRC_KEEP_TEXT_LAYER`).

Fotos: `coffee` (CC0) aus scikit-image; übrige Bilder synthetisch.
