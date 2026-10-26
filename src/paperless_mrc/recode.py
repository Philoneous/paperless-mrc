# SPDX-License-Identifier: AGPL-3.0-or-later
"""Startet recode_pdf (archive-pdf-tools) mit einstellbarer Empfindlichkeit der Textmaske.

Aufruf: python -m paperless_mrc.recode FAKTOR <recode_pdf-Argumente>

recode_pdf entscheidet per Sauvola-Binarisierung, welche Pixel in die scharfe Textmaske kommen
(k = 0,1 in erkannten Textzeilen, 0,34 sonst; fest im Code). FAKTOR skaliert beide k-Werte:
kleiner = empfindlicher, auch hellgraue Striche landen in der Maske statt im verkleinerten
Hintergrund. 1 = unverändert.
"""

import runpy
import shutil
import sys
from pathlib import Path


def main() -> None:
    factor = float(sys.argv.pop(1))
    if factor != 1.0:
        import internetarchivepdf.mrc as mrc

        original = getattr(mrc, "threshold_image", None)
        if original is not None:  # bei anderer archive-pdf-tools-Version: unverändert weiter
            mrc.threshold_image = lambda img, dpi, k=0.34: original(img, dpi, k * factor)
    script = Path(sys.executable).parent / "recode_pdf"
    sys.argv[0] = str(script if script.exists() else shutil.which("recode_pdf"))
    runpy.run_path(sys.argv[0], run_name="__main__")


if __name__ == "__main__":
    main()
