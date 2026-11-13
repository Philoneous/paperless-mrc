# SPDX-License-Identifier: AGPL-3.0-or-later
"""Startet Werkzeuge aus archive-pdf-tools (recode_pdf, pdf-to-hocr) unabhängig vom alten Modulnamen `fitz`.

archive-pdf-tools 1.5.7 importiert PyMuPDF als `fitz`. PyMuPDF hat `fitz` als veraltet markiert
(2.1: „deprecated and will be removed in future“); der Modulname ist dort nur noch ein Durchreicher
(`from pymupdf import *`). Wir tragen deshalb `pymupdf` selbst unter dem Namen `fitz` ein, bevor
das Werkzeug geladen wird – dann laufen die Werkzeuge weiter, auch wenn PyMuPDF `fitz` entfernt,
ohne PyMuPDF auf eine Version festzulegen.

Aufruf: python -m paperless_mrc.compat <werkzeug> <argumente>
"""

import runpy
import shutil
import sys
from pathlib import Path


def provide_fitz() -> None:
    """`import fitz` liefert ab jetzt pymupdf (auch wenn PyMuPDF kein `fitz` mehr mitbringt)."""
    import pymupdf

    sys.modules.setdefault("fitz", pymupdf)


def run_tool(name: str, args: list[str]) -> None:
    """Werkzeug-Skript im laufenden Prozess ausführen (wie der Kommandozeilenaufruf)."""
    provide_fitz()
    script = Path(sys.executable).parent / name
    path = str(script if script.exists() else shutil.which(name) or name)
    sys.argv = [path, *args]
    runpy.run_path(path, run_name="__main__")


def main() -> None:
    run_tool(sys.argv[1], sys.argv[2:])


if __name__ == "__main__":
    main()
