import os
from pathlib import Path

import pikepdf
import pymupdf
import pytest
from conftest import blank_back, letter_page, page_number_only, write_scan_pdf
from PIL import Image

from paperless_mrc import main as mrc

SETTINGS = mrc.Settings(language="deu", deskew=True, rotate=True, rotate_threshold=12.0)


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
    assert "bleibt unverändert" in capsys.readouterr().out


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
