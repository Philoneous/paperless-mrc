# Testseiten – Fälle und Soll-Ergebnisse

Erzeugt von `make_printset.py`. Soll = Verhalten mit den Standardwerten von paperless-mrc (OCR deu+eng). „Befund“ = schon die Simulation zeigt eine Schwäche; der echte Scan klärt es.

| Seite | Fall | Soll | Vor dem Scannen |
|---|---|---|---|
| 1 | Brief mit Foto und Handschrift – Normaler Brief, Mischseite mit Foto (Papier ≥ 50 %), echte Handschrift, 7-pt-Fußzeile, senkrechter Randvermerk darf keine Drehung auslösen. | komprimiert (MRC), keine Drehung, keine Begradigung; Handschrift (auch Bleistift, Textmarker, Rotstift) lesbar, Foto im Hintergrund ohne störende Artefakte | Felder A–E wie auf dem Blatt beschrieben ausfüllen. |
| 2 | Lesbarkeitstafel, Englisch, QR-Code, Strichcode – Kleine (5–11 pt), dünne, graue, farbige und invertierte Schrift, Haarlinien, Graukeil; englischer Text (OCR deu+eng). | komprimiert (MRC), keine Drehung, keine Begradigung; QR-/Strichcode nach der Umwandlung lesbar | – |
| 3 | Leer mit einem Punkt von 0,5 mm (Staubkorn) – Echte leere Seite; ein Staubkorn darf sie nicht retten. Druckt der Drucker die Seite nicht: ein unbedrucktes Blatt einlegen und mit Kugelschreiber einen winzigen Punkt setzen. | leer → entfernt | – |
| 4 | Nur Seitenzahl – Untere Grenze der Leerseitenerkennung. | behalten, komprimiert (Simulation: Tinte 0,010 % – nur doppelt so viel wie die Leerschwelle 0,005 %) | – |
| 5 | Ganzseitiges Wandfoto im Schatten, unscharf – Weiches Foto ohne Kanten (Rand läuft weich aus); früher als leer gelöscht. | Foto → Seite unverändert (ohne Texterkennung: kaum Tinte, kein Papier) | – |
| 6 | Foto mit kurzer Bildunterschrift (6 Wörter) – Typische Seite einer Fotodokumentation. | Foto → Seite unverändert (Papier < 50 %, Texterkennung < 10 Wörter) | – |
| 7 | Farbig hinterlegte Seite mit Textblöcken (Versicherungsstil) – Dokument, das nur die Texterkennung vom Foto unterscheidet. | komprimiert (MRC), keine Drehung, keine Begradigung (Papier < 50 %, Texterkennung ≥ 10 Wörter) | – |
| 8 | Ganzseitiges Foto einer hellen Wand mit Wasserfleck und Haarriss – Mögliche Lücke der Fotoerkennung (Simulation: Papier 92 %, Tinte 0,4 %). | laut Code komprimiert (helle, ungesättigte Wand zählt als Papier ≥ 50 % → keine Fotoprüfung); gewünscht: Foto → Befund | – |
| 9 | Brief kopfüber und 2° schräg gedruckt – Drehung (OSD) und danach Begradigung auf derselben Seite. | komprimiert, gedreht um 180°, begradigt um ca. 2° | – |
| 10 | Querformat-Tabelle (7 pt, Wasserzeichen) hochkant gedruckt – Fall, für den MRC_ROTATE_CHECK gebaut wurde. | komprimiert, gedreht um 90° (ist die OSD unsicher, entscheidet der Wortvergleich, MRC_ROTATE_CHECK; Simulation: 300 dpi unsicher 6,3, 200 dpi sicher 14,2) | – |
| 11 | Textarme Seite kopfüber: Logo, ein Wort, schräger Stempel, Unterschrift, Seitenzahl – Logo/Stempel dürfen die Begradigung nicht bestimmen (Commit 316e21e); Untergrenze der Lageerkennung. | komprimiert, nicht begradigt; gewünscht: gedreht um 180°, laut Simulation wenig Text → OSD unsicher → bleibt kopfüber → Befund | – |
