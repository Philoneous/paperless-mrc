# SPDX-License-Identifier: AGPL-3.0-or-later
"""Original aufbewahren (MRC_KEEP_ORIGINAL) gegen eine nachgebaute Paperless-API (tests/paperless_api.py)."""

import hashlib
import json
from dataclasses import replace

import pytest
from conftest import letter_page, write_scan_pdf
from paperless_api import TOKEN, Paperless, age

import paperless_mrc.main as mrc
from paperless_mrc import originals

SETTINGS = mrc.Settings(language="deu", deskew=True, rotate=True, rotate_threshold=12.0)
KEEP = replace(SETTINGS, keep_original=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def env(tmp_path, monkeypatch):
    hold = tmp_path / "originals"
    monkeypatch.setenv("MRC_ORIGINALS_DIR", str(hold))
    monkeypatch.setenv("MRC_API_TOKEN", TOKEN)
    monkeypatch.setenv("TASK_ID", "task-1")
    monkeypatch.delenv("MRC_KEEP_ORIGINAL_DAYS", raising=False)
    monkeypatch.delenv("MRC_LANGUAGE", raising=False)
    server = Paperless(tmp_path, consume_hook=lambda p: mrc.process(p, SETTINGS))
    monkeypatch.setenv("MRC_API_URL", server.url)
    yield hold, server
    server.close()


def consume(tmp_path, rng, server, doc_id=7, settings=KEEP):
    """Wie Paperless: Pre-Consume auf der Arbeitskopie, Dokument anlegen, Post-Consume."""
    path = write_scan_pdf(tmp_path / f"brief{doc_id}.pdf", [letter_page(rng)])
    original = path.read_bytes()
    mrc.process(path, settings)
    server.add_document(doc_id, path)
    return path, original


def test_ohne_option_wird_nichts_aufbewahrt(tmp_path, rng, env, monkeypatch):
    hold, server = env
    path, original = consume(tmp_path, rng, server, settings=SETTINGS)
    assert path.read_bytes() != original  # komprimiert wie bisher
    assert not hold.exists()
    monkeypatch.setenv("DOCUMENT_ID", "7")
    assert originals.post_consume() == 0
    assert server.calls == []  # keine API-Aufrufe


def test_original_wird_angehaengt_geprueft_und_auf_wunsch_geloescht(tmp_path, rng, env, monkeypatch, capsys):
    hold, server = env
    path, original = consume(tmp_path, rng, server)
    assert path.read_bytes() != original
    assert (hold / "task-1.pdf").read_bytes() == original

    monkeypatch.setenv("DOCUMENT_ID", "7")
    assert originals.post_consume() == 0
    doc = server.docs[7]
    version = next(v for v in doc["versions"] if not v["is_root"])
    # Die hochgeladene Version lief durch das Pre-Consume-Skript und blieb das unveränderte Original
    assert version["version_label"] == "Original" and version["checksum"] == hashlib.sha256(original).hexdigest()
    assert "original_version" in capsys.readouterr().out
    field = server.fields[0]
    assert field["name"] == "Original (MRC)" and field["data_type"] == "select"
    assert [o["label"] for o in field["extra_data"]["select_options"]] == ["Delete after 30 days", "Keep", "Delete now"]
    assert doc["custom_fields"] == [{"field": field["id"], "value": "mrc-auto"}]

    # Erster Durchlauf: abgelegte Kopie freigeben (Version ist angekommen), Original bleibt innerhalb der Frist
    counts = originals.cleanup(originals.Api.from_env())
    assert counts == {"deleted": 0, "kept": 0, "waiting": 1, "released": 1, "attached": 0}
    assert list(hold.iterdir()) == []

    # „Jetzt löschen“ → Version weg, Feld entfernt, komprimierte Fassung (Root) bleibt
    doc["custom_fields"][0]["value"] = "mrc-delete"
    assert originals.cleanup(originals.Api.from_env())["deleted"] == 1
    assert [v["is_root"] for v in doc["versions"]] == [True] and doc["custom_fields"] == []


@pytest.mark.parametrize("value, age_days, deleted", [
    ("mrc-auto", 31, True), ("mrc-auto", 5, False), (None, 31, True),
    ("mrc-keep", 400, False), ("fremd", 400, False),
])
def test_frist_und_behalten(tmp_path, rng, env, monkeypatch, value, age_days, deleted):
    hold, server = env
    consume(tmp_path, rng, server)
    monkeypatch.setenv("DOCUMENT_ID", "7")
    originals.post_consume()
    doc = server.docs[7]
    age(doc, "Original", age_days)
    doc["custom_fields"][0]["value"] = value
    originals.cleanup(originals.Api.from_env())
    assert any(not v["is_root"] for v in doc["versions"]) is not deleted


def test_frist_einstellbar_und_beschriftung_folgt(tmp_path, rng, env, monkeypatch):
    hold, server = env
    consume(tmp_path, rng, server)
    monkeypatch.setenv("DOCUMENT_ID", "7")
    monkeypatch.setenv("MRC_LANGUAGE", "de")
    originals.post_consume()
    age(server.docs[7], "Original", 10)
    monkeypatch.setenv("MRC_KEEP_ORIGINAL_DAYS", "7")
    originals.cleanup(originals.Api.from_env())
    assert [v["is_root"] for v in server.docs[7]["versions"]] == [True]
    originals.ensure_field(originals.Api.from_env())
    assert server.fields[0]["extra_data"]["select_options"][0]["label"] == "Löschen nach 7 Tagen"


def test_ohne_task_id_bleibt_datei_unveraendert(tmp_path, rng, env, monkeypatch):
    hold, server = env
    monkeypatch.delenv("TASK_ID")
    monkeypatch.setenv("MRC_KEEP_ORIGINAL", "true")
    path = write_scan_pdf(tmp_path / "brief.pdf", [letter_page(rng)])
    before = path.read_bytes()
    monkeypatch.setenv("DOCUMENT_WORKING_PATH", str(path))
    monkeypatch.setenv("PAPERLESS_OCR_LANGUAGE", "deu")
    assert mrc.main() == 0
    assert path.read_bytes() == before  # Original nicht ablegbar → nicht komprimieren


def test_fehler_beim_anhaengen_bricht_nicht_ab_und_behaelt_original(tmp_path, rng, env, monkeypatch, capsys):
    hold, server = env
    server.fields.append({"id": 1, "name": "Original (MRC)", "data_type": "string", "extra_data": {}})
    consume(tmp_path, rng, server)
    monkeypatch.setenv("DOCUMENT_ID", "7")
    assert originals.post_consume() == 0
    assert "gehört nicht zu paperless-mrc" in capsys.readouterr().out
    assert (hold / "task-1.pdf").exists() and len(server.docs[7]["versions"]) == 1


def test_falsches_token_bricht_nicht_ab(tmp_path, rng, env, monkeypatch, capsys):
    hold, server = env
    consume(tmp_path, rng, server)
    monkeypatch.setenv("DOCUMENT_ID", "7")
    monkeypatch.setenv("MRC_API_TOKEN", "falsch")
    assert originals.post_consume() == 0
    assert "HTTP 401" in capsys.readouterr().out and (hold / "task-1.pdf").exists()


def test_aufraeumen_haengt_original_nachtraeglich_an(tmp_path, rng, env, monkeypatch):
    """Token fehlte beim Einlesen: Das Original bleibt abgelegt und wird beim Aufräumen angehängt."""
    hold, server = env
    consume(tmp_path, rng, server)
    monkeypatch.setenv("DOCUMENT_ID", "7")
    monkeypatch.setenv("MRC_API_TOKEN", "")
    assert originals.post_consume() == 0 and len(server.docs[7]["versions"]) == 1
    monkeypatch.setenv("MRC_API_TOKEN", TOKEN)
    counts = originals.cleanup(originals.Api.from_env())
    assert counts["attached"] == 1
    assert any(v["version_label"] == "Original" for v in server.docs[7]["versions"])
    assert originals.cleanup(originals.Api.from_env())["released"] == 1  # nächster Lauf: Kopie freigegeben


def test_aufraeumen_haelt_kopie_bis_version_angekommen(tmp_path, rng, env, monkeypatch):
    hold, server = env
    server.consume_hook = None
    consume(tmp_path, rng, server)
    monkeypatch.setenv("DOCUMENT_ID", "7")
    originals.post_consume()
    server.docs[7]["versions"] = [v for v in server.docs[7]["versions"] if v["is_root"]]  # Verarbeitung läuft noch
    counts = originals.cleanup(originals.Api.from_env())
    assert counts["released"] == 0 and counts["waiting"] == 1
    assert (hold / "task-1.pdf").exists() and server.docs[7]["custom_fields"]  # Feld bleibt, nichts gelöscht


def test_seitenweise_listen(tmp_path, rng, env, monkeypatch):
    hold, server = env
    for i in range(3):
        server.fields.append({"id": 50 + i, "name": f"Feld {i}", "data_type": "string", "extra_data": {}})
    api = originals.Api.from_env()
    assert len(api.get_all("custom_fields/?page_size=2")) == 3


def test_paperless_conf_wird_fuer_den_timer_gelesen(tmp_path, monkeypatch):
    conf = tmp_path / "paperless.conf"
    conf.write_text('# Kommentar\nMRC_API_TOKEN="abc"\nMRC_KEEP_ORIGINAL_DAYS=14\nPAPERLESS_PORT=8010\n')
    for key in ("MRC_API_TOKEN", "MRC_KEEP_ORIGINAL_DAYS", "PAPERLESS_PORT", "MRC_API_URL"):
        monkeypatch.setenv(key, "")  # merkt den alten Zustand, damit load_conf nichts in andere Tests trägt
        monkeypatch.delenv(key)
    monkeypatch.setenv("MRC_KEEP_ORIGINAL_DAYS", "3")  # Umgebung hat Vorrang
    originals.load_conf(conf)
    api = originals.Api.from_env()
    assert api.token == "abc" and api.base == "http://localhost:8010/api/" and originals.days() == 3


def test_feld_wird_nachgesetzt_ohne_zweiten_upload(tmp_path, rng, env, monkeypatch, capsys):
    """Version angehängt, aber Setzen des Felds scheitert: kein zweiter Upload, Aufräumen setzt das Feld nach."""
    hold, server = env
    consume(tmp_path, rng, server)
    monkeypatch.setenv("DOCUMENT_ID", "7")
    server.fail_bulk_edit = 1
    assert originals.post_consume() == 0
    assert "HTTP 500" in capsys.readouterr().out
    doc = server.docs[7]
    assert len(doc["versions"]) == 2 and doc["custom_fields"] == []
    counts = originals.cleanup(originals.Api.from_env())
    assert counts["attached"] == 0 and counts["released"] == 1
    assert len(doc["versions"]) == 2  # kein zweites Original
    assert doc["custom_fields"] == [{"field": server.fields[0]["id"], "value": "mrc-auto"}]


@pytest.mark.parametrize("mrc_language, ui_language, first_label", [
    ("", "de-de", "Löschen nach 30 Tagen"),   # folgt der in Paperless gewählten Sprache
    ("", "", "Delete after 30 days"),         # Browsersprache: für den Server unbekannt → Englisch
    ("en", "de-de", "Delete after 30 days"),  # MRC_LANGUAGE hat Vorrang
    ("de", "en-us", "Löschen nach 30 Tagen"),
])
def test_feldsprache(env, monkeypatch, mrc_language, ui_language, first_label):
    hold, server = env
    monkeypatch.setenv("MRC_LANGUAGE", mrc_language)
    server.ui_language = ui_language
    originals.ensure_field(originals.Api.from_env())
    assert server.fields[0]["extra_data"]["select_options"][0]["label"] == first_label


def test_ersetzen_scheitert_ablage_wird_zurueckgenommen(tmp_path, rng, env, monkeypatch):
    hold, server = env
    path = write_scan_pdf(tmp_path / "brief.pdf", [letter_page(rng)])
    before = path.read_bytes()

    def broken_replace(src, dst):
        raise OSError("Datenträger voll")
    monkeypatch.setattr(mrc.os, "replace", broken_replace)
    with pytest.raises(OSError):
        mrc.process(path, KEEP)
    assert path.read_bytes() == before
    assert list(hold.iterdir()) == []  # keine verwaiste Ablage, kein Rest der Zwischendatei
    assert not path.with_name(path.name + ".mrc-tmp").exists()


def test_gescheiterte_aufgabe_wird_einmal_gemeldet(tmp_path, rng, env, capsys):
    hold, server = env
    path = write_scan_pdf(tmp_path / "brief.pdf", [letter_page(rng)])
    mrc.process(path, KEEP)
    server.tasks["task-1"] = None  # Paperless hat die Verarbeitung abgebrochen
    capsys.readouterr()
    originals.cleanup(originals.Api.from_env())
    originals.cleanup(originals.Api.from_env())
    assert capsys.readouterr().out.count("never attached") == 1
    assert (hold / "task-1.pdf").exists()  # Original bleibt für den Nutzer liegen


def test_geloeschtes_dokument_kopie_bleibt_innerhalb_der_frist(tmp_path, rng, env, monkeypatch):
    hold, server = env
    server.consume_hook = None
    consume(tmp_path, rng, server)
    monkeypatch.setenv("DOCUMENT_ID", "7")
    originals.post_consume()
    del server.docs[7]  # in Paperless gelöscht (Papierkorb)
    assert originals.cleanup(originals.Api.from_env())["released"] == 0
    assert (hold / "task-1.pdf").exists()
    meta = json.loads((hold / "task-1.json").read_text())
    meta["uploaded"] -= 31 * 86400
    (hold / "task-1.json").write_text(json.dumps(meta))
    assert originals.cleanup(originals.Api.from_env())["released"] == 1
