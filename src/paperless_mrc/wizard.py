# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Philoneous
"""Einrichtungsassistent (paperless-mrc-setup), aufgerufen von install.sh.

Fragt die wichtigsten Einstellungen (catalog.OPTIONS, level „basic“), auf Wunsch auch die Details, und schreibt sie
in paperless.conf. Bei einer bestehenden Einrichtung können die Einstellungen übernommen werden; dann fragt er nur
Optionen, die seit der letzten Einrichtung hinzugekommen sind (catalog.REVISION, gemerkt in setup.json).

Standardwerte werden nicht eingetragen (ein späteres Update mit besserem Standard greift dann auch hier); wer einen
Wert auf den Standard zurücksetzt, dessen Zeile wird entfernt. Vorher wird paperless.conf gesichert.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import sys
import textwrap
import time
from pathlib import Path

from paperless_mrc import catalog
from paperless_mrc.catalog import Option

LANG_PATTERN = re.compile(r"^[a-z]{3}(_[a-z]+)*(\+[a-z]{3}(_[a-z]+)*)*$")
TRUE = ("true", "1", "t", "y", "yes")

TEXT = {
    "intro": ("paperless-mrc setup – press Enter to keep the value in brackets.",
              "Einrichtung von paperless-mrc – Enter übernimmt den Wert in Klammern."),
    "existing": ("paperless-mrc is already set up. Current settings (only those that differ from the default):",
                 "paperless-mrc ist bereits eingerichtet. Aktuelle Einstellungen (nur die vom Standard abweichenden):"),
    "none_changed": ("  (all defaults)", "  (alles Standard)"),
    "keep": ("Keep these settings and only go through new options?",
             "Diese Einstellungen übernehmen und nur neue Optionen durchgehen?"),
    "no_new": ("No new options since the last setup.", "Seit der letzten Einrichtung gibt es keine neuen Optionen."),
    "new_count": ("{n} new option(s) since the last setup:", "{n} neue Option(en) seit der letzten Einrichtung:"),
    "advanced": ("Adjust detailed settings as well? (the defaults are chosen for the best readability)",
                 "Auch Detaileinstellungen anpassen? (die Standardwerte sind auf beste Lesbarkeit ausgelegt)"),
    "group": ("Adjust “{group}”?", "„{group}“ anpassen?"),
    "yes_no": ("[Y/n]", "[J/n]"),
    "no_yes": ("[y/N]", "[j/N]"),
    "invalid": ("Please enter a valid value.", "Bitte einen gültigen Wert eingeben."),
    "range": ("range {lo}–{hi}", "Bereich {lo}–{hi}"),
    "max_dpi": ("0 = off, or 150–1200", "0 = aus, oder 150–1200"),
    "choices": ("one of: {choices}", "eins von: {choices}"),
    "token_keep": ("(Enter = keep the stored token)", "(Enter = gespeichertes Token behalten)"),
    "token_empty": ("(Enter = skip, add it later)", "(Enter = überspringen, später eintragen)"),
    "token_ok": ("Token accepted by Paperless.", "Token von Paperless angenommen."),
    "token_bad": ("Paperless did not accept the token ({error}) – it is saved anyway; check it later.",
                  "Paperless hat das Token nicht angenommen ({error}) – es wird trotzdem gespeichert; bitte später "
                  "prüfen."),
    "saved": ("Settings saved in {conf} (backup next to it).", "Einstellungen in {conf} gespeichert (Sicherung "
                                                                 "daneben)."),
    "unchanged": ("Settings unchanged.", "Einstellungen unverändert."),
}


class Prompter:
    """Fragen über das Terminal (auch bei „curl … | bash“ über /dev/tty) oder aus vorgegebenen Antworten (Tests)."""

    def __init__(self, de: bool, inp=None, out=None):
        self.de = de
        self.inp = inp or sys.stdin
        self.out = out or sys.stdout
        self.tty = inp is None and self.inp.isatty()

    def text(self, key: str, **values) -> str:
        return TEXT[key][1 if self.de else 0].format(**values)

    def say(self, message: str = "") -> None:
        print(message, file=self.out, flush=True)

    def ask(self, prompt: str, secret: bool = False) -> str:
        if secret and self.tty:
            return getpass.getpass(prompt + " ", stream=self.out).strip()
        print(prompt + " ", end="", file=self.out, flush=True)
        line = self.inp.readline()
        if not line:
            raise EOFError
        return line.strip()

    def yes(self, question: str, default: bool) -> bool:
        hint = self.text("yes_no" if default else "no_yes")
        while True:
            answer = self.ask(f"{question} {hint}").lower()
            if not answer:
                return default
            if answer in ("y", "yes", "j", "ja"):
                return True
            if answer in ("n", "no", "nein"):
                return False
            self.say(self.text("invalid"))


# ----------------------------------------------------------------------------- paperless.conf


def read_conf(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_conf(path: Path, changes: dict[str, str | None]) -> bool:
    """Zeilen ersetzen, anhängen (None: entfernen). Gibt zurück, ob sich etwas geändert hat."""
    lines = path.read_text().splitlines() if path.exists() else []
    original = list(lines)
    for key, value in changes.items():
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        index = next((i for i in range(len(lines) - 1, -1, -1) if pattern.match(lines[i])), None)
        if value is None:
            if index is not None:
                del lines[index]
        elif index is not None:
            lines[index] = f"{key}={value}"
        else:
            if "# paperless-mrc" not in lines:
                lines += ["", "# paperless-mrc"]
            header = lines.index("# paperless-mrc")
            end = header + 1
            while end < len(lines) and lines[end].strip() and not lines[end].startswith("#"):
                end += 1
            lines.insert(end, f"{key}={value}")
    if lines == original:
        return False
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d%H%M%S')}"))
    path.write_text("\n".join(lines) + "\n")
    return True


# ----------------------------------------------------------------------------- Werte


def bounds(option: Option) -> tuple[float, float] | None:
    if option.min_max:
        return option.min_max
    from paperless_mrc.main import RANGES
    return RANGES.get(option.key)


def fmt(value: float) -> str:
    return f"{value:g}"


def parse(option: Option, answer: str) -> str | None:
    """Antwort prüfen und normalisieren; None = ungültig."""
    if option.kind == "bool":
        lower = answer.lower()
        return "true" if lower in ("y", "yes", "j", "ja", "true") else "false" if lower in ("n", "no", "nein",
                                                                                                 "false") else None
    if option.kind in ("int", "float"):
        if option.key == "MRC_JOBS" and answer == "":
            return ""
        try:
            number = float(answer.replace(",", "."))
        except ValueError:
            return None
        if option.kind == "int" and number != int(number):
            return None
        if option.key == "MRC_MAX_DPI" and 0 < number < 150:
            return None
        lo_hi = bounds(option)
        if lo_hi and not lo_hi[0] <= number <= lo_hi[1]:
            return None
        return str(int(number)) if option.kind == "int" else fmt(number)
    if option.kind == "choice":
        return answer.lower() if answer.lower() in option.choices else None
    if option.key == "PAPERLESS_OCR_LANGUAGE":
        return answer if LANG_PATTERN.match(answer) else None
    return answer


def check_token(token: str, conf: dict[str, str]) -> str | None:
    """None, wenn Paperless das Token annimmt; sonst die Fehlermeldung."""
    from paperless_mrc.originals import Api
    port = conf.get("PAPERLESS_PORT") or "8000"
    try:
        Api(conf.get("MRC_API_URL") or f"http://localhost:{port}", token).request("GET", "ui_settings/")
        return None
    except Exception as exc:  # Netz, 401 …
        return str(exc)[:120]


class Wizard:
    def __init__(self, conf_path: Path, state_path: Path, prompter: Prompter, presets: dict[str, str]):
        self.conf_path = conf_path
        self.state_path = state_path
        self.p = prompter
        self.conf = read_conf(conf_path)
        self.answers: dict[str, str] = dict(presets)

    def current(self, option: Option) -> str:
        if option.key in self.answers:
            return self.answers[option.key]
        if option.key in self.conf:
            return self.conf[option.key]
        if option.key == "PAPERLESS_OCR_LANGUAGE":
            return "deu+eng" if self.p.de else "eng"
        return option.default

    def enabled(self, option: Option) -> bool:
        """Abhängige Option nur fragen, wenn die Voraussetzung an ist (Ja/Nein: ja; Zahl: ungleich 0)."""
        if not option.requires:
            return True
        required = catalog.BY_KEY[option.requires]
        value = self.current(required).lower()
        if required.kind == "bool":
            return value in TRUE
        try:
            return float(value) != 0
        except ValueError:
            return False

    def ask_option(self, option: Option, position: str = "") -> None:
        if not self.enabled(option):
            return
        de = 1 if self.p.de else 0
        self.p.say()
        self.p.say(f"{position}{option.title[de]}")
        self.p.say(textwrap.fill(option.help[de], width=100, initial_indent="  ", subsequent_indent="  "))
        current = self.current(option)
        if option.kind == "bool":
            self.answers[option.key] = "true" if self.p.yes("  →", current.lower() in TRUE) else "false"
            return
        if option.secret:
            hint = self.p.text("token_keep" if current else "token_empty")
            answer = self.p.ask(f"  {hint}:", secret=True)
            if answer:
                self.answers[option.key] = answer
                error = check_token(answer, {**self.conf, **self.answers})
                self.p.say("  " + (self.p.text("token_ok") if error is None else self.p.text("token_bad", error=error)))
            return
        extra = ""
        if option.key == "MRC_MAX_DPI":
            extra = self.p.text("max_dpi")
        elif option.kind == "choice":
            extra = self.p.text("choices", choices=", ".join(option.choices))
        elif bounds(option):
            lo, hi = bounds(option)
            extra = self.p.text("range", lo=fmt(lo), hi=fmt(hi))
        while True:
            answer = self.p.ask(f"  {extra + ' ' if extra else ''}[{current}]:")
            value = parse(option, answer) if answer else current  # Enter: Wert in Klammern übernehmen
            if value is not None:
                self.answers[option.key] = value
                return
            self.p.say("  " + self.p.text("invalid"))

    def changed_summary(self) -> list[str]:
        de = 1 if self.p.de else 0
        lines = []
        for option in catalog.OPTIONS:
            value = self.conf.get(option.key)
            if value is None or value == option.default or option.key == "MRC_LANGUAGE":
                continue
            shown = "••••" if option.secret else value
            lines.append(f"  {option.title[de]}: {shown}")
        return lines

    def ask_advanced(self, options: list[Option]) -> None:
        de = 1 if self.p.de else 0
        groups: dict[tuple[str, str], list[Option]] = {}
        for option in options:
            groups.setdefault(option.group, []).append(option)
        for group, members in groups.items():
            if any(self.enabled(o) for o in members) and self.p.yes(self.p.text("group", group=group[de]), False):
                for option in members:
                    self.ask_option(option)

    def run(self, mode: str) -> None:
        state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        existing = bool(state) or "PAPERLESS_PRE_CONSUME_SCRIPT" in self.conf
        # Ohne setup.json, aber schon eingerichtet (vor dem Assistenten): alle Optionen der Revision 1 gelten als bekannt
        seen = state.get("revision", 1 if existing else 0)
        questions = [o for o in catalog.OPTIONS if o.key != "MRC_LANGUAGE"]

        if mode == "interactive":
            self.p.say(self.p.text("intro"))
            only_new = False
            if existing:
                self.p.say()
                self.p.say(self.p.text("existing"))
                for line in self.changed_summary() or [self.p.text("none_changed")]:
                    self.p.say(line)
                only_new = self.p.yes(self.p.text("keep"), True)
            if only_new:
                new = [o for o in questions if o.since > seen]
                if not new:
                    self.p.say(self.p.text("no_new"))
                else:
                    self.p.say(self.p.text("new_count", n=len(new)))
                    for option in new:
                        self.ask_option(option)
            else:
                basic = [o for o in questions if o.level == "basic" and not o.requires]
                for number, option in enumerate(basic, 1):
                    self.ask_option(option, f"({number}/{len(basic)}) ")
                    for follow in (o for o in questions if o.level == "basic" and o.requires == option.key):
                        self.ask_option(follow)
                self.p.say()
                if self.p.yes(self.p.text("advanced"), False):
                    self.ask_advanced([o for o in questions if o.level == "advanced"])
        self.save()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"revision": catalog.REVISION}))

    def save(self) -> None:
        changes: dict[str, str | None] = {}
        for key, value in self.answers.items():
            option = catalog.BY_KEY[key]
            if key.startswith("PAPERLESS_"):  # Paperless' eigene Einstellungen: nur schreiben, was gewählt wurde
                if self.conf.get(key) != value:
                    changes[key] = value
                continue
            if value == option.default or (option.key == "MRC_JOBS" and value == ""):
                if key in self.conf:
                    changes[key] = None  # zurück auf den Standard: Zeile entfernen
            elif self.conf.get(key) != value:
                changes[key] = value
        if "PAPERLESS_OCR_LANGUAGE" not in self.conf and "PAPERLESS_OCR_LANGUAGE" not in changes:
            changes["PAPERLESS_OCR_LANGUAGE"] = self.current(catalog.BY_KEY["PAPERLESS_OCR_LANGUAGE"])
        if write_conf(self.conf_path, changes):
            self.p.say(self.p.text("saved", conf=self.conf_path))
        else:
            self.p.say(self.p.text("unchanged"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paperless-mrc-setup")
    parser.add_argument("--conf", type=Path, default=Path("/opt/paperless/paperless.conf"))
    parser.add_argument("--state", type=Path, default=Path(sys.prefix).parent / "setup.json")
    parser.add_argument("--lang", choices=("en", "de"))
    parser.add_argument("--yes", action="store_true", help="no questions (keep existing settings)")
    args = parser.parse_args(argv)

    conf = read_conf(args.conf)
    lang = args.lang or os.environ.get("MRC_LANGUAGE") or conf.get("MRC_LANGUAGE") or "en"
    de = lang.lower().startswith("de")
    presets = {}
    if os.environ.get("KEEP_ORIGINAL", "").lower() in ("1", "true", "yes", "0", "false", "no"):
        presets["MRC_KEEP_ORIGINAL"] = "true" if os.environ["KEEP_ORIGINAL"].lower() in TRUE else "false"
    if args.lang and conf.get("MRC_LANGUAGE", "en") != args.lang:
        presets["MRC_LANGUAGE"] = args.lang  # „en“ = Standard: Zeile wird entfernt

    inp = out = None
    interactive = not args.yes
    if interactive and not sys.stdin.isatty():
        try:  # „curl … | bash“: Fragen über das Terminal
            inp = open("/dev/tty")
            out = open("/dev/tty", "w")
        except OSError:
            interactive = False
    prompter = Prompter(de, inp, out)
    if inp is not None:
        prompter.tty = True
    try:
        Wizard(args.conf, args.state, prompter, presets).run("interactive" if interactive else "quiet")
    except (EOFError, KeyboardInterrupt):
        print(file=prompter.out)
        print("Aborted – nothing changed." if not de else "Abgebrochen – nichts geändert.", file=prompter.out)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
