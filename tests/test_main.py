import json
import os
from pathlib import Path

import pikepdf
import pymupdf
import pytest
from conftest import (LETTER, add_vector_scan_page, blank_back, insurance_page, letter_page, page_number_only,
                      photo_page, wall_photo, write_scan_pdf)
from PIL import Image, ImageDraw

from paperless_mrc import main as mrc

SETTINGS = mrc.Settings(language="deu", deskew=True, rotate=True, rotate_threshold=12.0)


def results(out: str) -> list[dict]:
    """Maschinenlesbare Ergebniszeilen aus der Ausgabe."""
    prefix = "paperless-mrc-result: "
    return [json.loads(line[len(prefix):]) for line in out.splitlines() if line.startswith(prefix)]


def text_of(path: Path) -> str:
    with pymupdf.open(path) as doc:
        return " ".join(page.get_text() for page in doc)


def page_count(path: Path) -> int:
    with pymupdf.open(path) as doc:
        return doc.page_count


def test_digital_pdf_bleibt_unveraendert(tmp_path):
    path = tmp_path / "digital.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Digital erzeugte Rechnung", fontsize=12)
    doc.save(path)
    before = path.read_bytes()
    mrc.process(path, SETTINGS)
    assert path.read_bytes() == before


def test_scan_ohne_text_wird_komprimiert_und_erkannt(tmp_path, rng):
    path = write_scan_pdf(tmp_path / "scan.pdf", [letter_page(rng)])
    size_before = path.stat().st_size
    mrc.process(path, SETTINGS)
    assert path.stat().st_size < size_before / 3
    assert page_count(path) == 1
    assert "Jahresabrechnung" in text_of(path)
    with pikepdf.open(path) as pdf:
        smasks = [img.get("/SMask") for img in pdf.pages[0].get_images().values() if "/SMask" in img]
        assert smasks and all(s.ColorSpace == pikepdf.Name.DeviceGray for s in smasks)


def test_vorhandene_textebene_wird_uebernommen(tmp_path, rng):
    # Das Wort steht nur in der unsichtbaren Textebene, nicht im Bild: Tesseract könnte es nicht finden.
    path = write_scan_pdf(tmp_path / "handyscan.pdf", [letter_page(rng)],
                          invisible_text=["Zauberwort4711 Jahresabrechnung"])
    mrc.process(path, SETTINGS)
    assert "Zauberwort4711" in text_of(path)


def test_nur_wirklich_leere_seiten_werden_entfernt(tmp_path, rng):
    path = write_scan_pdf(tmp_path / "leer.pdf", [letter_page(rng), blank_back(rng), page_number_only(rng)])
    with pymupdf.open(path) as doc:
        inks = [mrc.ink_percent(p) for p in doc]
        assert mrc.paper_percent(doc[1]) > 90
    assert inks[1] < mrc.BLANK_INK_PERCENT <= inks[2], inks
    mrc.process(path, SETTINGS)
    assert page_count(path) == 2
    assert "Seite 3 von 3" in text_of(path)


def test_alle_seiten_leer_bleibt_unveraendert(tmp_path, rng):
    path = write_scan_pdf(tmp_path / "nurleer.pdf", [blank_back(rng)])
    before = path.read_bytes()
    mrc.process(path, SETTINGS)
    assert path.read_bytes() == before


def test_uebergrosse_seite_wird_auf_a4_skaliert(tmp_path, rng):
    img = letter_page(rng)
    path = write_scan_pdf(tmp_path / "gross.pdf", [img], page_size=(img.width, img.height))  # 72 ppi
    mrc.process(path, SETTINGS)
    with pymupdf.open(path) as doc:
        rect = doc[0].rect
    assert abs(rect.width - 595.28) < 3 or abs(rect.height - 841.89) < 3
    assert rect.width <= 596 and rect.height <= 842


def test_parallel_behaelt_seitenreihenfolge(tmp_path, rng):
    pages = [letter_page(rng, lines=[f"Testseite Nummer {n}"]) for n in (1, 2, 3)]
    path = write_scan_pdf(tmp_path / "parallel.pdf", pages)
    mrc.process(path, mrc.Settings(language="deu", deskew=True, rotate=True, rotate_threshold=12.0, jobs=3))
    with pymupdf.open(path) as doc:
        assert [f"Nummer {n}" in page.get_text() for n, page in enumerate(doc, 1)] == [True] * 3


def test_gemischte_pdf_digitale_seite_bleibt(tmp_path, rng):
    path = write_scan_pdf(tmp_path / "gemischt.pdf", [letter_page(rng), blank_back(rng), letter_page(rng)])
    with pymupdf.open(path) as doc:
        page = doc.new_page(width=595, height=842)  # angehängte digitale Seite
        page.insert_text((72, 72), "Digitaler Anhang Kontonummer", fontsize=12)
        doc.set_toc([[1, "Anschreiben", 1], [1, "Anhang", 4]])
        doc.set_metadata({"title": "Testtitel"})
        doc.saveIncr()
    size_before = path.stat().st_size
    mrc.process(path, SETTINGS)
    assert path.stat().st_size < size_before / 3
    with pymupdf.open(path) as doc:
        assert doc.page_count == 3  # leere Scan-Seite entfernt
        assert "Jahresabrechnung" in doc[0].get_text()
        assert doc[2].get_text().strip() == "Digitaler Anhang Kontonummer"
        assert doc[2].get_images() == []  # nicht gerastert
        assert [t[1:] for t in doc.get_toc()] == [["Anschreiben", 1], ["Anhang", 3]]
        assert doc.metadata["title"] == "Testtitel"


def test_signierte_pdf_bleibt_unveraendert(tmp_path, rng):
    path = write_scan_pdf(tmp_path / "signiert.pdf", [letter_page(rng)])
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array(), SigFlags=3)
        pdf.save(path)
    before = path.read_bytes()
    mrc.process(path, SETTINGS)
    assert path.read_bytes() == before


def test_schraeglage_wird_erkannt(rng):
    img = letter_page(rng).rotate(1.5, resample=Image.BICUBIC, fillcolor=(248, 246, 240))
    assert abs(mrc.skew_angle(img) - (-1.5)) <= 0.2


def test_kopfstehende_seite_wird_gedreht(tmp_path, rng):
    img = letter_page(rng).rotate(180)
    path = write_scan_pdf(tmp_path / "kopf.pdf", [img])
    mrc.process(path, mrc.Settings(language="deu", deskew=False, rotate=True, rotate_threshold=5.0))
    assert "Jahresabrechnung" in text_of(path)


def test_fehler_laesst_datei_unveraendert(tmp_path, rng, monkeypatch, capsys):
    path = write_scan_pdf(tmp_path / "fehler.pdf", [letter_page(rng)])
    before = path.read_bytes()

    def kaputt(*args, **kwargs):
        raise RuntimeError("simulierter Fehler")

    monkeypatch.setattr(mrc, "encode_page", kaputt)
    monkeypatch.setenv("DOCUMENT_WORKING_PATH", str(path))
    assert mrc.main() == 0
    assert path.read_bytes() == before
    out = capsys.readouterr().out
    assert "document left unchanged" in out
    assert results(out)[0]["status"] == "error" and "simulierter Fehler" in results(out)[0]["message"]


def test_mrc_einstellungen_aus_umgebung(monkeypatch):
    for name in ("MRC_REMOVE_BLANK_PAGES", "MRC_BLANK_INK_PERCENT", "MRC_BG_DOWNSAMPLE",
                 "MRC_BG_COMPRESSION_RATE", "MRC_FIT_A4"):
        monkeypatch.delenv(name, raising=False)
    s = mrc.Settings.from_env()
    assert (s.remove_blank, s.blank_ink_percent, s.bg_downsample, s.bg_rate, s.fit_a4) == (
        True, mrc.BLANK_INK_PERCENT, 2, 200.0, True)  # bisheriges Verhalten
    monkeypatch.setenv("MRC_REMOVE_BLANK_PAGES", "false")
    monkeypatch.setenv("MRC_BLANK_INK_PERCENT", "0.02")
    monkeypatch.setenv("MRC_BG_DOWNSAMPLE", "3")
    monkeypatch.setenv("MRC_BG_COMPRESSION_RATE", "400")
    monkeypatch.setenv("MRC_FIT_A4", "no")
    s = mrc.Settings.from_env()
    assert (s.remove_blank, s.blank_ink_percent, s.bg_downsample, s.bg_rate, s.fit_a4) == (
        False, 0.02, 3, 400.0, False)


def test_leere_seiten_bleiben_wenn_abgeschaltet(tmp_path, rng):
    path = write_scan_pdf(tmp_path / "leer_bleibt.pdf", [letter_page(rng), blank_back(rng)])
    mrc.process(path, mrc.Settings(language="deu", deskew=True, rotate=True, rotate_threshold=12.0,
                                   remove_blank=False))
    assert page_count(path) == 2


def test_a4_korrektur_abschaltbar(tmp_path, rng):
    img = letter_page(rng)
    path = write_scan_pdf(tmp_path / "gross_bleibt.pdf", [img], page_size=(img.width, img.height))
    mrc.process(path, mrc.Settings(language="deu", deskew=True, rotate=True, rotate_threshold=12.0,
                                   fit_a4=False))
    with pymupdf.open(path) as doc:
        assert doc[0].rect.width > 1000


def test_staerkere_hintergrundkompression_wird_kleiner(tmp_path, rng):
    img = letter_page(rng)
    normal = write_scan_pdf(tmp_path / "normal.pdf", [img])
    stark = write_scan_pdf(tmp_path / "stark.pdf", [img])
    mrc.process(normal, SETTINGS)
    mrc.process(stark, mrc.Settings(language="deu", deskew=True, rotate=True, rotate_threshold=12.0,
                                    bg_downsample=4, bg_rate=800))
    assert stark.stat().st_size < normal.stat().st_size


REAL = os.environ.get("PAPERLESS_MRC_TESTFILES")


@pytest.mark.skipif(not REAL, reason="PAPERLESS_MRC_TESTFILES nicht gesetzt (echte Scans liegen nicht im Repo)")
def test_echte_scans(tmp_path):
    for src in sorted(Path(REAL).glob("*.pdf")):
        path = tmp_path / src.name
        path.write_bytes(src.read_bytes())
        words_before = len(text_of(path).split())
        mrc.process(path, SETTINGS)
        assert path.stat().st_size < src.stat().st_size / 3, src.name
        assert len(text_of(path).split()) >= 0.95 * words_before, src.name


def settings(**changes) -> mrc.Settings:
    return mrc.Settings(language="deu", deskew=True, rotate=True, rotate_threshold=12.0, **changes)


def image_sizes(page: pymupdf.Page) -> list[tuple[int, int]]:
    return sorted((w, h) for _, _, w, h, *_ in page.get_images())


def test_fotoseite_bleibt_unveraendert(tmp_path, rng):
    path = write_scan_pdf(tmp_path / "foto.pdf", [letter_page(rng), photo_page(rng)])
    with pymupdf.open(path) as doc:
        assert mrc.paper_percent(doc[0]) > 80 and mrc.paper_percent(doc[1]) < 30
        photo_before = image_sizes(doc[1])
    mrc.process(path, SETTINGS)
    with pymupdf.open(path) as doc:
        assert doc.page_count == 2
        assert len(doc[0].get_images()) > 1  # MRC-Ebenen
        assert image_sizes(doc[1]) == photo_before  # Foto unverändert


def test_fotoerkennung_abschaltbar(tmp_path, rng):
    path = write_scan_pdf(tmp_path / "foto_mrc.pdf", [letter_page(rng), photo_page(rng)])
    mrc.process(path, settings(skip_photos=False))
    with pymupdf.open(path) as doc:
        assert doc.page_count == 2  # weiches Foto hat kaum „Tinte“, darf aber nicht als leer gelten
        assert len(doc[1].get_images()) > 1


def test_vektorisierter_scan_wird_gerastert_und_erkannt(tmp_path, rng):
    path = tmp_path / "vektor.pdf"
    with pymupdf.open() as doc:
        add_vector_scan_page(doc, letter_page(rng))
        doc.save(path, expand=255)  # unkomprimiert, wie die echten vektorisierten Scans (~1 MB/Seite)
    with pymupdf.open(path) as doc:
        assert mrc.is_vector_page(doc[0], 1000) and not doc[0].get_text().strip()
    mrc.process(path, settings(vector_dpi=200))
    with pymupdf.open(path) as doc:
        assert doc[0].get_images() and not doc[0].get_cdrawings()
    assert "Jahresabrechnung" in text_of(path)


def test_vektorseiten_abschaltbar(tmp_path, rng):
    path = tmp_path / "vektor_bleibt.pdf"
    with pymupdf.open() as doc:
        add_vector_scan_page(doc, letter_page(rng))
        doc.save(path)
    before = path.read_bytes()
    mrc.process(path, settings(vector_pages=False))
    assert path.read_bytes() == before


def test_schraeglage_ohne_zeilen_ist_unklar(rng):
    assert mrc.skew_angle(blank_back(rng).convert("L").point(lambda v: 245)) is None


@pytest.mark.parametrize("lines", [["Kurz"], ["Seite 3 von 3"]])
def test_textarme_gerade_seite_wird_nicht_gekippt(rng, lines):
    # Bei einem Wort neben dem Logo bestimmt das Logo die Bewertung; früher ergab das +3,3°.
    img = letter_page(rng, lines=lines)
    angle = mrc.skew_angle(img)
    assert angle is None or abs(angle) < mrc.MIN_SKEW_DEG, angle


@pytest.mark.parametrize("lines, degrees", [(LETTER[:2], 2.0), (LETTER[1:2], 1.0), (LETTER, 4.0)])
def test_schraege_zeilen_werden_weiter_erkannt(rng, lines, degrees):
    img = letter_page(rng, lines=lines).rotate(degrees, resample=Image.BICUBIC, fillcolor=(248, 246, 240))
    assert abs(mrc.skew_angle(img) + degrees) <= 0.2


def test_begradigungs_konfidenz_aus_umgebung(monkeypatch):
    monkeypatch.delenv("MRC_DESKEW_MIN_CONFIDENCE", raising=False)
    assert mrc.Settings.from_env().deskew_confidence == 1.3
    monkeypatch.setenv("MRC_DESKEW_MIN_CONFIDENCE", "1.6")
    assert mrc.Settings.from_env().deskew_confidence == 1.6


def test_textarme_seite_bleibt_gerade_im_ablauf(tmp_path, rng, capsys):
    path = write_scan_pdf(tmp_path / "kurz.pdf", [letter_page(rng, lines=["Kurz"])])
    mrc.process(path, SETTINGS)
    assert "corrected" not in capsys.readouterr().out


def test_gemischte_pdfs_abschaltbar(tmp_path, rng):
    path = write_scan_pdf(tmp_path / "gemischt_bleibt.pdf", [letter_page(rng)])
    with pymupdf.open(path) as doc:
        doc.new_page().insert_text((72, 72), "Digitaler Anhang", fontsize=12)
        doc.saveIncr()
    before = path.read_bytes()
    mrc.process(path, settings(mixed_pdfs=False))
    assert path.read_bytes() == before


def test_textebene_neu_erkennen(tmp_path, rng):
    path = write_scan_pdf(tmp_path / "neu.pdf", [letter_page(rng)], invisible_text=["Zauberwort4711"])
    mrc.process(path, settings(keep_text_layer=False))
    text = text_of(path)
    assert "Zauberwort4711" not in text and "Jahresabrechnung" in text


def test_neue_einstellungen_aus_umgebung(monkeypatch):
    names = ("MRC_DESKEW_MIN_ANGLE", "MRC_DESKEW_MAX_ANGLE", "MRC_SKIP_PHOTOS", "MRC_PHOTO_PAPER_PERCENT",
             "MRC_VECTOR_PAGES", "MRC_VECTOR_MIN_ITEMS", "MRC_VECTOR_DPI", "MRC_MIXED_PDFS", "MRC_KEEP_TEXT_LAYER",
             "MRC_BLANK_PAPER_PERCENT", "MRC_PHOTO_MIN_WORDS")
    for name in names:
        monkeypatch.delenv(name, raising=False)
    s = mrc.Settings.from_env()
    fields = lambda s: (s.deskew_min, s.deskew_max, s.skip_photos, s.photo_paper_percent, s.vector_pages,
                        s.vector_min_items, s.vector_dpi, s.mixed_pdfs, s.keep_text_layer, s.blank_paper_percent,
                        s.photo_min_words)
    assert fields(s) == (0.2, 5.0, True, 50.0, True, 1000, 300, True, True, 90.0, 10)
    for name, value in zip(names, ("0.5", "8", "false", "40", "no", "500", "400", "0", "false", "95", "25")):
        monkeypatch.setenv(name, value)
    assert fields(mrc.Settings.from_env()) == (0.5, 8.0, False, 40.0, False, 500, 400, False, False, 95.0, 25)


@pytest.mark.parametrize("halftone", [False, True])
def test_hinterlegte_textbloecke_sind_kein_foto(tmp_path, rng, halftone):
    path = write_scan_pdf(tmp_path / "versicherung.pdf", [insurance_page(rng, halftone)])
    with pymupdf.open(path) as doc:
        assert mrc.paper_percent(doc[0]) < 50  # wenig Papierfläche: Texterkennung entscheidet
    size_before = path.stat().st_size
    mrc.process(path, SETTINGS)
    assert path.stat().st_size < size_before / 3
    assert "Versicherungsnummer" in text_of(path)


def test_wandfoto_wird_weder_geloescht_noch_komprimiert(tmp_path, rng):
    path = write_scan_pdf(tmp_path / "wand.pdf", [letter_page(rng), wall_photo(rng)])
    with pymupdf.open(path) as doc:
        wall_before = image_sizes(doc[1])
    mrc.process(path, SETTINGS)
    with pymupdf.open(path) as doc:
        assert doc.page_count == 2
        assert image_sizes(doc[1]) == wall_before


def test_zeitmessung(tmp_path, rng, capsys):
    path = write_scan_pdf(tmp_path / "zeit.pdf", [letter_page(rng)])
    mrc.process(path, settings(timing=True))
    out = capsys.readouterr().out
    assert "Page 1: time render" in out and "OCR" in out and "MRC" in out
    assert "zeit.pdf: time detection" in out and "verification" in out


def test_kontrastreiches_foto_ohne_text_bleibt(tmp_path, rng, capsys):
    # Kanten und Strukturen wie in einem Foto: genug „Tinte“, wenig Papier → Texterkennung entscheidet
    img = photo_page(rng)
    d = ImageDraw.Draw(img)
    for _ in range(60):
        x, y = rng.integers(0, img.width - 200), rng.integers(0, img.height - 200)
        d.ellipse((x, y, x + rng.integers(40, 200), y + rng.integers(40, 200)),
                  fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
    path = write_scan_pdf(tmp_path / "nur_foto.pdf", [img])
    before = path.read_bytes()
    mrc.process(path, SETTINGS)
    assert path.read_bytes() == before
    out = capsys.readouterr().out
    assert "confidently recognised words" in out and "1 photo" in out


def test_sichere_woerter_im_hocr():
    hocr = ("<span class='ocrx_word' id='w1' title='bbox 1 1 2 2; x_wconf 91'>Vertrag</span>"
            "<span class='ocrx_word' id='w2' title='bbox 1 1 2 2; x_wconf 30'>Xq</span>"
            "<span class='ocrx_word' id='w3' title='bbox 1 1 2 2; x_wconf 88'><strong>2026</strong></span>"
            "<span class='ocrx_word' id='w4' title='bbox 1 1 2 2; x_wconf 95'>a.</span>")
    assert mrc.confident_words(hocr) == 2


def test_hoechstaufloesung(tmp_path, rng):
    img = letter_page(rng)  # 200 dpi
    path = write_scan_pdf(tmp_path / "dpi.pdf", [img])
    mrc.process(path, settings(max_dpi=100))
    with pymupdf.open(path) as doc:
        widths = [w for _, _, w, *_ in doc[0].get_images()]
    assert max(widths) <= round(595.28 / 72 * 100) + 2
    assert mrc.Settings.from_env().max_dpi == 0  # Standard: aus


def test_parallelitaet_aus_umgebung(monkeypatch):
    monkeypatch.setenv("PAPERLESS_THREADS_PER_WORKER", "1")
    monkeypatch.delenv("MRC_JOBS", raising=False)
    assert mrc.Settings.from_env().jobs == 1
    monkeypatch.setenv("MRC_JOBS", "3")
    assert mrc.Settings.from_env().jobs == 3


def test_nachschaerfen_einstellbar(tmp_path, rng, monkeypatch):
    assert (mrc.Settings.from_env().sharpen, mrc.Settings.from_env().sharpen_radius) == (150, 1.5)
    monkeypatch.setenv("MRC_SHARPEN", "0")
    monkeypatch.setenv("MRC_SHARPEN_RADIUS", "2")
    assert (mrc.Settings.from_env().sharpen, mrc.Settings.from_env().sharpen_radius) == (0, 2.0)
    path = write_scan_pdf(tmp_path / "ohne.pdf", [letter_page(rng)])
    mrc.process(path, settings(sharpen=0))
    assert "Jahresabrechnung" in text_of(path)


def test_maskenfaktor(tmp_path, rng, monkeypatch):
    assert mrc.Settings.from_env().mask_sensitivity == 0.5
    monkeypatch.setenv("MRC_MASK_FACTOR", "1")
    assert mrc.Settings.from_env().mask_sensitivity == 1.0
    for factor in (1.0, 0.3):
        path = write_scan_pdf(tmp_path / f"maske{factor}.pdf", [letter_page(rng)])
        mrc.process(path, settings(mask_sensitivity=factor))
        assert "Jahresabrechnung" in text_of(path)


def test_ergebniszeile_komprimiert(tmp_path, rng, capsys):
    path = write_scan_pdf(tmp_path / "ergebnis.pdf", [letter_page(rng), blank_back(rng)])
    size = path.stat().st_size
    mrc.process(path, SETTINGS)
    out = capsys.readouterr().out
    [r] = results(out)
    assert r["status"] == "compressed" and r["file"] == "ergebnis.pdf" and r["version"] == 1
    assert r["size_before"] == size and r["size_after"] == path.stat().st_size
    assert (r["pages"], r["blank_removed"], r["photos"], r["digital"], r["text_layer"]) == (1, 1, 0, 0, "ocr")
    assert "ergebnis.pdf: " in out and "1 blank removed, text layer via Tesseract" in out


def test_ergebniszeile_unveraendert(tmp_path, capsys):
    path = tmp_path / "digital.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Digital")
    doc.save(path)
    mrc.process(path, SETTINGS)
    out = capsys.readouterr().out
    assert results(out) == [{"version": 1, "file": "digital.pdf", "status": "unchanged", "reason": "no_scanned_pages"}]
    assert "digital.pdf: no scanned pages – unchanged" in out


def test_meldungen_deutsch(tmp_path, rng, capsys, monkeypatch):
    monkeypatch.setenv("MRC_LANGUAGE", "de")
    path = write_scan_pdf(tmp_path / "deutsch.pdf", [letter_page(rng), blank_back(rng)])
    mrc.process(path, SETTINGS)
    out = capsys.readouterr().out
    assert "1 Seite(n), 1 leere entfernt, Textebene per Tesseract" in out
    assert results(out)[0]["text_layer"] == "ocr"  # Ergebniszeile bleibt sprachunabhängig


def test_alle_meldungen_in_beiden_sprachen():
    import string
    for key, (en, de) in mrc.MESSAGES.items():
        fields = lambda text: {f for _, f, _, _ in string.Formatter().parse(text) if f}
        assert fields(en) == fields(de), key
