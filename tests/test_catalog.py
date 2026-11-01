# SPDX-License-Identifier: AGPL-3.0-or-later
"""Der Einstellungskatalog muss zum Code passen – sonst würde der Installer neue Optionen nicht anbieten."""

import re
from pathlib import Path

import pytest

import paperless_mrc.main as mrc
from paperless_mrc import catalog

SRC = Path(mrc.__file__).parent


def keys_read_by_code() -> set[str]:
    keys = set()
    for path in SRC.glob("*.py"):
        text = path.read_text()
        keys |= set(re.findall(r'_env_(?:num|bool|choice)\(\s*"([A-Z0-9_]+)"', text))
        keys |= set(re.findall(r'os\.environ(?:\.get)?\(\s*"([A-Z0-9_]+)"', text))
        keys |= set(re.findall(r'os\.environ\["([A-Z0-9_]+)"\]', text))
        keys |= set(re.findall(r'fallback="([A-Z0-9_]+)"', text))
    return keys - {"KEEP_ORIGINAL"}  # Installer-Schalter, kein Eintrag in paperless.conf


def test_jede_gelesene_einstellung_steht_im_katalog():
    missing = keys_read_by_code() - set(catalog.BY_KEY) - catalog.NOT_SETTINGS
    assert not missing, f"Im Katalog nachtragen (since=REVISION+1, REVISION erhöhen): {sorted(missing)}"


def test_katalog_enthaelt_nur_gelesene_einstellungen():
    unknown = set(catalog.BY_KEY) - keys_read_by_code()
    assert not unknown, f"Nicht mehr im Code gelesen: {sorted(unknown)}"


def test_revision_passt_zur_neuesten_option():
    assert catalog.REVISION == max(o.since for o in catalog.OPTIONS)


def test_standardwerte_wie_im_code(monkeypatch):
    for key in list(catalog.BY_KEY) + ["PAPERLESS_THREADS_PER_WORKER"]:
        monkeypatch.delenv(key, raising=False)
    s = mrc.Settings.from_env()
    fields = {"MRC_REMOVE_BLANK_PAGES": s.remove_blank, "MRC_SKIP_PHOTOS": s.skip_photos,
              "MRC_MIXED_PDFS": s.mixed_pdfs, "MRC_KEEP_TEXT_LAYER": s.keep_text_layer, "MRC_FIT_A4": s.fit_a4,
              "MRC_FIT_PAGE_SIZE": s.fit_size, "MRC_KEEP_ORIGINAL": s.keep_original, "MRC_SHARPEN": s.sharpen,
              "MRC_SHARPEN_RADIUS": s.sharpen_radius, "MRC_MASK_FACTOR": s.mask_sensitivity,
              "MRC_BG_DOWNSAMPLE": s.bg_downsample, "MRC_BG_COMPRESSION_RATE": s.bg_rate,
              "MRC_MAX_DPI": s.max_dpi, "MRC_PHOTO_PAPER_PERCENT": s.photo_paper_percent,
              "MRC_PHOTO_MIN_WORDS": s.photo_min_words, "MRC_VECTOR_PAGES": s.vector_pages,
              "MRC_VECTOR_MIN_ITEMS": s.vector_min_items, "MRC_VECTOR_DPI": s.vector_dpi,
              "MRC_ROTATE_CHECK": s.rotate_check, "MRC_DESKEW_MIN_ANGLE": s.deskew_min,
              "MRC_DESKEW_MAX_ANGLE": s.deskew_max, "MRC_DESKEW_MIN_CONFIDENCE": s.deskew_confidence,
              "MRC_BLANK_INK_PERCENT": s.blank_ink_percent, "MRC_BLANK_INK_CONTRAST": s.blank_ink_contrast,
              "MRC_BLANK_PAPER_PERCENT": s.blank_paper_percent, "PAPERLESS_OCR_DESKEW": s.deskew,
              "PAPERLESS_OCR_ROTATE_PAGES": s.rotate, "PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD": s.rotate_threshold,
              "MRC_POPPLER_CHECK": s.poppler_check, "MRC_TIMING": s.timing, "PAPERLESS_OCR_LANGUAGE": s.language}
    for key, value in fields.items():
        option = catalog.BY_KEY[key]
        if option.kind == "bool":
            assert option.default == ("true" if value else "false"), key
        elif option.kind in ("int", "float"):
            assert float(option.default) == float(value), key
        else:
            assert option.default == value, key
    from paperless_mrc import originals
    assert int(catalog.BY_KEY["MRC_KEEP_ORIGINAL_DAYS"].default) == originals.days()


@pytest.mark.parametrize("option", [o for o in catalog.OPTIONS if o.kind in ("int", "float")], ids=lambda o: o.key)
def test_zahlen_haben_einen_bereich(option):
    if option.key == "MRC_JOBS":
        return
    assert option.key in mrc.RANGES or option.min_max, option.key
    lo, hi = option.min_max or mrc.RANGES[option.key]
    assert lo <= float(option.default) <= hi


@pytest.mark.parametrize("option", catalog.OPTIONS, ids=lambda o: o.key)
def test_texte_zweisprachig_und_abhaengigkeiten_gueltig(option):
    assert all(option.title) and all(option.help) and all(option.group)
    if option.requires:
        assert catalog.BY_KEY[option.requires].kind in ("bool", "int", "float")
    if option.kind == "choice":
        assert option.default in option.choices
