# SPDX-License-Identifier: AGPL-3.0-or-later
"""Notiz am Dokument (MRC_NOTE): Pre-Consume legt die Angaben ab, Post-Consume schreibt die Notiz."""

import json
from dataclasses import replace

import pytest
from conftest import blank_back, letter_page, page_number_only, write_scan_pdf
from paperless_api import TOKEN, Paperless

import paperless_mrc.main as mrc
from paperless_mrc import notes, originals

SETTINGS = mrc.Settings(language="deu", deskew=True, rotate=True, rotate_threshold=12.0, note=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MRC_ORIGINALS_DIR", str(tmp_path / "originals"))
    monkeypatch.setenv("MRC_NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("MRC_API_TOKEN", TOKEN)
    monkeypatch.setenv("TASK_ID", "task-1")
    monkeypatch.setenv("DOCUMENT_ID", "7")
    monkeypatch.setenv("MRC_LANGUAGE", "de")
    monkeypatch.delenv("MRC_KEEP_ORIGINAL_DAYS", raising=False)
    server = Paperless(tmp_path, consume_hook=lambda p: mrc.process(p, replace(SETTINGS, note=False)))
    monkeypatch.setenv("MRC_API_URL", server.url)
    yield tmp_path / "notes", server
    server.close()


def consume(tmp_path, server, images, settings=SETTINGS):
    path = write_scan_pdf(tmp_path / "brief.pdf", images)
    mrc.process(path, settings)
    server.add_document(7, path)
    assert originals.post_consume() == 0
    return server.docs[7]["notes"]


def test_notiz_nach_komprimierung(tmp_path, rng, env):
    folder, server = env
    written = consume(tmp_path, server, [letter_page(rng), blank_back(rng), page_number_only(rng)])
    assert len(written) == 1 and list(folder.iterdir()) == []  # abgelegte Angaben sind aufgeräumt
    text = written[0]["note"]
    assert text.startswith("**paperless-mrc** · ")
    assert "- Komprimiert: " in text and "→" in text and "(−" in text
    assert "- Seiten: 3 → 2" in text and "- Leere Seiten entfernt: 2" in text
    assert "- Textebene: mit Tesseract erkannt (deu)" in text and "- Dauer: " in text
    assert "Original" not in text  # Option aus
    assert "POST /api/documents/7/notes/" in server.calls


def test_notiz_mit_original(tmp_path, rng, env):
    _, server = env
    written = consume(tmp_path, server, [letter_page(rng)], replace(SETTINGS, keep_original=True))
    assert "- Original als Version „Original“ aufbewahrt" in written[0]["note"]
    assert len(written) == 1  # das hochgeladene Original selbst bekommt keine zweite Notiz


def test_unveraendert_nur_mit_option(tmp_path, env):
    _, server = env
    path = tmp_path / "text.txt"
    path.write_text("kein PDF")
    for setting, expected in ((False, 0), (True, 1)):
        mrc.process(path, replace(SETTINGS, note_unchanged=setting))
        server.add_document(7, path)
        originals.post_consume()
        assert len(server.docs[7]["notes"]) == expected
    assert "Nicht komprimiert: keine PDF" in server.docs[7]["notes"][0]["note"]


def test_fehler_wird_als_notiz_vermerkt(tmp_path, rng, env, monkeypatch):
    _, server = env
    path = write_scan_pdf(tmp_path / "fehler.pdf", [letter_page(rng)])
    monkeypatch.setattr(mrc, "encode_page", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simuliert")))
    monkeypatch.setenv("DOCUMENT_WORKING_PATH", str(path))
    for key, value in {"MRC_NOTE": "true", "PAPERLESS_OCR_LANGUAGE": "deu"}.items():
        monkeypatch.setenv(key, value)
    assert mrc.main() == 0
    server.add_document(7, path)
    originals.post_consume()
    assert "- Fehler – Datei unverändert: RuntimeError('simuliert')" in server.docs[7]["notes"][0]["note"]


def test_ohne_token_still_und_aufgeraeumt(tmp_path, rng, env, monkeypatch):
    folder, server = env
    monkeypatch.delenv("MRC_API_TOKEN")
    monkeypatch.setattr(originals, "CONF", tmp_path / "fehlt.conf")
    assert consume(tmp_path, server, [letter_page(rng)]) == []
    assert server.calls == [] and list(folder.iterdir()) == []


def test_ohne_task_id_nichts_abgelegt(tmp_path, rng, env, monkeypatch):
    folder, _ = env
    monkeypatch.delenv("TASK_ID")  # z. B. Aufruf außerhalb von Paperless
    mrc.process(write_scan_pdf(tmp_path / "a.pdf", [letter_page(rng)]), SETTINGS)
    assert not folder.exists()


def test_seitenbereiche():
    assert notes.page_ranges([8, 1, 2, 3, 5, 7]) == "1–3, 5, 7–8"
    assert notes.page_ranges([]) == ""


def test_render_einzelheiten_englisch():
    data = {"status": "compressed", "time": 0, "size_before": 5 * 1024 * 1024, "size_after": 512 * 1024,
            "pages": 4, "pages_before": 5, "blank_pages": [2], "photos_pages": [4], "rotated": [[3, 180]],
            "deskewed": [[1, -0.84]], "resized_pages": [1, 3], "fit_size": "A4",
            "text_kept_pages": [1], "text_ocr_pages": [3, 5], "languages": "deu+eng", "seconds": 75}
    text = notes.render(data, de=False, original=False)
    assert "- Compressed: 5.0 MB → 512 KB (−90 %)" in text
    assert "- Pages: 5 → 4" in text and "- Blank pages removed: 2" in text
    assert "- Rotated: page 3 (180°)" in text and "- Straightened: page 1 (−0.8°)" in text
    assert "- Page size corrected to A4: 1, 3" in text
    assert "- Text layer: kept on page 1, recognised with Tesseract (deu+eng) on pages 3, 5" in text
    assert "could not be attached" in text and "- Duration: 1 min 15 s" in text
    assert text.endswith("_Page numbers refer to the uploaded file._")
    assert json.dumps(data)  # nur JSON-fähige Werte


def test_dieselbe_datei_erneut_hochgeladen_wird_komprimiert(tmp_path, rng, env, monkeypatch):
    # Fall aus dem Betrieb: Original von #7 ist als Version angehängt, die Kopie liegt noch (Aufräumen stündlich);
    # dieselbe Datei kommt erneut als neues Dokument → nicht für das eigene Original halten
    _, server = env
    keep = replace(SETTINGS, keep_original=True)
    path = write_scan_pdf(tmp_path / "brief.pdf", [letter_page(rng)])
    original = path.read_bytes()
    mrc.process(path, keep)
    server.add_document(7, path)
    originals.post_consume()
    assert any(v["version_label"] == "Original" for v in server.docs[7]["versions"])

    again = tmp_path / "nochmal.pdf"
    again.write_bytes(original)
    monkeypatch.setenv("TASK_ID", "task-2")
    monkeypatch.setenv("DOCUMENT_ID", "8")
    mrc.process(again, keep)
    assert again.read_bytes() != original  # komprimiert
    server.add_document(8, again, task_id="task-2")
    originals.post_consume()
    assert "- Komprimiert: " in server.docs[8]["notes"][0]["note"]
