# SPDX-License-Identifier: AGPL-3.0-or-later
"""Startet recode_pdf (archive-pdf-tools) mit einstellbarer Empfindlichkeit der Textmaske.

Aufruf: python -m paperless_mrc.recode FAKTOR <recode_pdf-Argumente>

recode_pdf entscheidet per Sauvola-Binarisierung, welche Pixel in die scharfe Textmaske kommen
(k = 0,1 in erkannten Textzeilen, 0,34 sonst; fest im Code). FAKTOR skaliert beide k-Werte:
kleiner = empfindlicher, auch hellgraue Striche landen in der Maske statt im verkleinerten
Hintergrund. 1 = unverändert.
"""

import sys

from paperless_mrc.compat import provide_fitz, run_tool


def main() -> None:
    factor = float(sys.argv.pop(1))
    provide_fitz()  # vor dem Laden von internetarchivepdf, siehe compat.py
    if factor != 1.0:
        import internetarchivepdf.mrc as mrc

        original = getattr(mrc, "threshold_image", None)
        if original is not None:  # bei anderer archive-pdf-tools-Version: unverändert weiter
            mrc.threshold_image = lambda img, dpi, k=0.34: original(img, dpi, k * factor)
    run_tool("recode_pdf", sys.argv[1:])


if __name__ == "__main__":
    main()
