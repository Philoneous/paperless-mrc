# SPDX-License-Identifier: AGPL-3.0-or-later
"""Einrichtungsassistent (paperless-mrc-setup) mit vorgegebenen Antworten."""

import io
import json

import pytest
from paperless_api import TOKEN, Paperless

from paperless_mrc import catalog, wizard


def run(tmp_path, answers, conf_text="", state=None, lang="en", presets=None):
    conf = tmp_path / "paperless.conf"
    conf.write_text(conf_text)
    state_file = tmp_path / "setup.json"
    if state is not None:
        state_file.write_text(json.dumps(state))
    out = io.StringIO()
    prompter = wizard.Prompter(lang == "de", io.StringIO("".join(a + "\n" for a in answers)), out)
    w = wizard.Wizard(conf, state_file, prompter, presets or {})
    w.run("interactive")
    return wizard.read_conf(conf), out.getvalue(), json.loads(state_file.read_text())


def basic_answers(**overrides):
    """Antworten auf die wichtigsten Fragen in Katalog-Reihenfolge (leer = Vorgabe übernehmen)."""
    order = ["PAPERLESS_OCR_LANGUAGE", "MRC_REMOVE_BLANK_PAGES", "MRC_SKIP_PHOTOS", "MRC_MIXED_PDFS",
             "MRC_KEEP_TEXT_LAYER", "MRC_FIT_A4", "MRC_FIT_PAGE_SIZE", "MRC_KEEP_ORIGINAL"]
    answers = [overrides.get(k, "") for k in order]
    if overrides.get("MRC_KEEP_ORIGINAL") in ("y", "j"):
        answers += [overrides.get("MRC_KEEP_ORIGINAL_DAYS", ""), overrides.get("MRC_API_TOKEN", "")]
    return answers


def test_neuinstallation_nur_standard_schreibt_nur_sprache(tmp_path):
    conf, out, state = run(tmp_path, basic_answers() + ["n"], lang="de")
    assert conf == {"PAPERLESS_OCR_LANGUAGE": "deu+eng"}  # Standardwerte werden nicht eingetragen
    assert state == {"revision": catalog.REVISION}
    assert "Einrichtung von paperless-mrc" in out


def test_neuinstallation_mit_aenderungen_und_ungueltiger_eingabe(tmp_path):
    answers = basic_answers(PAPERLESS_OCR_LANGUAGE="fra+eng", MRC_SKIP_PHOTOS="n", MRC_FIT_PAGE_SIZE="Letter")
    answers.insert(0, "Französisch")  # ungültig → erneute Frage
    conf, out, _ = run(tmp_path, answers + ["n"])
    assert conf["PAPERLESS_OCR_LANGUAGE"] == "fra+eng"
    assert conf["MRC_SKIP_PHOTOS"] == "false" and conf["MRC_FIT_PAGE_SIZE"] == "letter"
    assert "Please enter a valid value" in out


def test_original_aufbewahren_mit_token_wird_geprueft(tmp_path):
    server = Paperless(tmp_path)
    try:
        answers = basic_answers(MRC_KEEP_ORIGINAL="y", MRC_KEEP_ORIGINAL_DAYS="14", MRC_API_TOKEN=TOKEN)
        conf, out, _ = run(tmp_path, answers + ["n"], conf_text=f"MRC_API_URL={server.url}\n")
    finally:
        server.close()
    assert conf["MRC_KEEP_ORIGINAL"] == "true" and conf["MRC_KEEP_ORIGINAL_DAYS"] == "14"
    assert conf["MRC_API_TOKEN"] == TOKEN and "Token accepted" in out
    assert TOKEN not in out  # Token wird nie angezeigt


def test_falsches_token_wird_gemeldet_aber_gespeichert(tmp_path):
    server = Paperless(tmp_path)
    try:
        answers = basic_answers(MRC_KEEP_ORIGINAL="y", MRC_API_TOKEN="falsch")
        conf, out, _ = run(tmp_path, answers + ["n"], conf_text=f"MRC_API_URL={server.url}\n")
    finally:
        server.close()
    assert conf["MRC_API_TOKEN"] == "falsch" and "did not accept" in out


def test_zahlen_ausserhalb_des_bereichs_werden_abgelehnt(tmp_path):
    answers = basic_answers() + ["y"]  # Details: ja
    # Gruppen der Details in Katalog-Reihenfolge: Qualität zuerst → anpassen
    answers += ["y", "500", "250", "", "", "", "", "", "", "", "n", "n", "n", "n"]
    conf, out, _ = run(tmp_path, answers)
    assert conf["MRC_SHARPEN"] == "250" and "range 0–300" in out
    assert "Sharpening radius" in out  # abhängig von einer Zahl (≠ 0), nicht von Ja/Nein


def test_bestehend_uebernehmen_ohne_neue_optionen(tmp_path):
    existing = "PAPERLESS_PRE_CONSUME_SCRIPT=/opt/x\nPAPERLESS_OCR_LANGUAGE=deu\nMRC_SHARPEN=120\nMRC_API_TOKEN=geheim\n"
    conf, out, state = run(tmp_path, ["y"], conf_text=existing, state={"revision": catalog.REVISION})
    assert conf["MRC_SHARPEN"] == "120" and "Sharpening (%): 120" in out
    assert "geheim" not in out and "No new options" in out
    assert state["revision"] == catalog.REVISION


def test_bestehend_ohne_setup_json_gilt_als_revision_1(tmp_path):
    conf, out, _ = run(tmp_path, ["y"], conf_text="PAPERLESS_PRE_CONSUME_SCRIPT=/opt/x\n")
    assert "No new options" in out  # Installationen vor dem Assistenten werden nicht mit allen Fragen überrollt


def test_update_fragt_nur_neue_optionen(tmp_path, monkeypatch):
    new = catalog.Option("MRC_NEU", "advanced", "bool", "false", title=("New thing", "Neues"),
                         help=("Explains it.", "Erklärt es."), since=catalog.REVISION + 1)
    monkeypatch.setattr(catalog, "OPTIONS", catalog.OPTIONS + [new])
    monkeypatch.setattr(catalog, "BY_KEY", {**catalog.BY_KEY, "MRC_NEU": new})
    monkeypatch.setattr(catalog, "REVISION", catalog.REVISION + 1)
    conf, out, state = run(tmp_path, ["y", "y"], conf_text="PAPERLESS_PRE_CONSUME_SCRIPT=/opt/x\nMRC_SHARPEN=120\n",
                           state={"revision": catalog.REVISION - 1})
    assert "1 new option(s)" in out and "New thing" in out and "OCR languages" not in out
    assert conf["MRC_NEU"] == "true" and conf["MRC_SHARPEN"] == "120"
    assert state["revision"] == catalog.REVISION


def test_bestehend_alles_durchgehen_und_auf_standard_zuruecksetzen(tmp_path):
    existing = "PAPERLESS_PRE_CONSUME_SCRIPT=/opt/x\nPAPERLESS_OCR_LANGUAGE=deu\nMRC_SKIP_PHOTOS=false\n"
    answers = ["n"] + basic_answers(MRC_SKIP_PHOTOS="y") + ["n"]
    conf, _, _ = run(tmp_path, answers, conf_text=existing)
    assert "MRC_SKIP_PHOTOS" not in conf  # Standard → Zeile entfernt
    assert conf["PAPERLESS_OCR_LANGUAGE"] == "deu"  # Enter übernimmt den bisherigen Wert


def test_abbruch_aendert_nichts(tmp_path):
    with pytest.raises(EOFError):
        run(tmp_path, ["fra"], conf_text="A=1\n")
    assert (tmp_path / "paperless.conf").read_text() == "A=1\n"
    assert not list(tmp_path.glob("paperless.conf.bak-*"))


def test_ohne_fragen_vorgaben_und_sprache(tmp_path):
    conf_path = tmp_path / "paperless.conf"
    conf_path.write_text("PAPERLESS_PRE_CONSUME_SCRIPT=/opt/x\n")
    out = io.StringIO()
    w = wizard.Wizard(conf_path, tmp_path / "setup.json", wizard.Prompter(False, io.StringIO(), out),
                      {"MRC_KEEP_ORIGINAL": "true", "MRC_LANGUAGE": "de"})
    w.run("quiet")
    conf = wizard.read_conf(conf_path)
    assert conf["MRC_KEEP_ORIGINAL"] == "true" and conf["MRC_LANGUAGE"] == "de"
    assert conf["PAPERLESS_OCR_LANGUAGE"] == "eng"
    assert list(tmp_path.glob("paperless.conf.bak-*"))  # Sicherung


def test_conf_zeilen_werden_ersetzt_und_kommentare_bleiben(tmp_path):
    path = tmp_path / "paperless.conf"
    path.write_text("# Kommentar\nPAPERLESS_X=1\n  MRC_SHARPEN=100\n#MRC_SHARPEN=50\n")
    wizard.write_conf(path, {"MRC_SHARPEN": "200", "MRC_NEU": "a", "PAPERLESS_X": None})
    text = path.read_text()
    assert "MRC_SHARPEN=200" in text and "#MRC_SHARPEN=50" in text and "PAPERLESS_X" not in text
    assert text.index("# paperless-mrc") < text.index("MRC_NEU=a")
