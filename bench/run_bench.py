# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lesbarkeit je Einstellung: Testseite mit paperless-mrc umwandeln, nur das Bild rendern (Textebene unsichtbar),
jede Zeile neu per Tesseract erkennen und mit dem bekannten Text vergleichen (Zeichenfehlerrate, CER).
Zusätzlich SSIM der Zeile gegenüber dem Scan (Bildtreue) und Dateigröße.

    python run_bench.py <pages> <ergebnisordner> name=MRC_X=wert,MRC_Y=wert ...
"""
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image
from skimage.metrics import structural_similarity

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def cer(ref: str, hyp: str) -> float:
    ref, hyp = " ".join(ref.split()), " ".join(hyp.split())
    prev = list(range(len(hyp) + 1))
    for i, a in enumerate(ref, 1):
        cur = [i]
        for j, b in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return prev[-1] / max(len(ref), 1)


def render(pdf: Path, dpi: int) -> Image.Image:
    with pymupdf.open(pdf) as doc:
        pix = doc[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def ocr(img: Image.Image, tmp: Path) -> str:
    p = tmp / "crop.png"
    img.save(p)
    return subprocess.run(["tesseract", str(p), "-", "-l", "deu+eng", "--psm", "7"], capture_output=True,
                          text=True).stdout.strip()


def score(pdf: Path, scan: Image.Image, blocks, hi, dpi, tmp):
    img = render(pdf, dpi)
    rows = []
    for b in blocks:
        box = [round(v * dpi / hi) for v in b["box"]]
        crop = img.crop(box)
        ref = scan.crop(box)
        ssim = structural_similarity(np.asarray(ref.convert("L")), np.asarray(crop.convert("L")), data_range=255)
        rows.append(dict(cat=b["cat"], cer=cer(b["text"], ocr(crop, tmp)), ssim=ssim))
    return rows


def main():
    pages, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    meta = json.loads((pages / "blocks.json").read_text())
    import paperless_mrc.main as mrc

    base = replace(mrc.Settings.from_env(), deskew=False, rotate=False, jobs=1, skip_photos=False, language="deu+eng")
    results = json.loads((out / "results.json").read_text()) if (out / "results.json").exists() else {}
    for spec in sys.argv[3:]:
        name, _, assigns = spec.partition("=")
        changes = {}
        for a in filter(None, assigns.split(",")):
            k, v = a.split(":")
            changes[k] = type(getattr(base, k))(float(v)) if not isinstance(getattr(base, k), str) else v
        settings = replace(base, **changes)
        for dpi in (200, 300):
            key = f"{name}@{dpi}"
            if key in results:
                continue
            tmp = out / "tmp"
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir()
            src = pages / f"scan_{dpi}.pdf"
            scan = Image.open(pages / f"clean_{dpi}.png").convert("RGB")  # Vorlage vor der Scan-Simulation
            if name == "scan":
                pdf, size = src, src.stat().st_size
            else:
                pdf = tmp / "doc.pdf"
                shutil.copy(src, pdf)
                mrc.process(pdf, settings)
                size = pdf.stat().st_size
                (out / "pdf").mkdir(exist_ok=True)
                shutil.copy(pdf, out / "pdf" / f"{key}.pdf")
                if size == src.stat().st_size:
                    print("UNVERÄNDERT", key)
            rows = score(pdf, scan, meta["blocks"], meta["hi"], dpi, tmp)
            results[key] = dict(size=size, rows=rows, settings=changes)
            (out / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
            print(key, size // 1024, "KB", "CER %.3f" % np.mean([r["cer"] for r in rows]), flush=True)


if __name__ == "__main__":
    os.environ.setdefault("MRC_LANGUAGE", "de")
    main()
