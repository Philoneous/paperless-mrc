# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Philoneous
"""Original aufbewahren (optional, MRC_KEEP_ORIGINAL=true; Standard aus).

Paperless-ngx 3 kennt Dokumentversionen; die erste (Root) lässt sich nicht löschen. Deshalb:
1. Pre-Consume (main.process): Vor dem Ersetzen wird das Original unter MRC_ORIGINALS_DIR/<TASK_ID>.pdf abgelegt.
   Klappt das nicht, bleibt die Datei unkomprimiert. Paperless speichert die komprimierte Fassung als Dokument.
2. Post-Consume (paperless-mrc-post, gleiche TASK_ID): Das Original wird als Version „Original“ angehängt und das
   Auswahlfeld „Original (MRC)“ auf „Löschen nach N Tagen“ gesetzt. Diese Version durchläuft das Pre-Consume-Skript
   erneut und wird dort an ihrer Prüfsumme erkannt (Marker <sha256>.version) und nicht komprimiert.
3. Aufräumen (paperless-mrc-cleanup, systemd-Timer): löscht die Version „Original“ bei „Jetzt löschen“ oder nach
   Ablauf der Frist, entfernt dann das Feld. „Behalten“ behält sie dauerhaft. Gelöscht wird nur bei eindeutiger
   Lage; die abgelegte Kopie erst, wenn die Version mit passender Prüfsumme in Paperless angekommen ist.

API (Paperless-ngx 3.3.0): POST documents/<id>/update_version/, DELETE documents/<id>/versions/<vid>/,
POST documents/bulk_edit/ (modify_custom_fields), custom_fields/ (select_options mit eigenen ids).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

VERSION_LABEL = "Original"
FIELD_NAME = "Original (MRC)"
AUTO, KEEP, DELETE = "mrc-auto", "mrc-keep", "mrc-delete"  # feste ids der Auswahl (Beschriftung übersetzbar)
CONF = Path(os.environ.get("MRC_PAPERLESS_CONF", "/opt/paperless/paperless.conf"))
CONFIRM_WARN_HOURS = 24  # so lange darf das Anhängen der Version dauern, bevor gewarnt wird

LABELS = {
    AUTO: ("Delete after {days} days", "Löschen nach {days} Tagen"),
    KEEP: ("Keep", "Behalten"),
    DELETE: ("Delete now", "Jetzt löschen"),
}


def _german() -> bool:
    return os.environ.get("MRC_LANGUAGE", "en").strip().lower().startswith("de")


def options(days: int) -> list[dict]:
    lang = 1 if _german() else 0
    return [{"id": i, "label": LABELS[i][lang].format(days=days)} for i in (AUTO, KEEP, DELETE)]


def enabled() -> bool:
    return os.environ.get("MRC_KEEP_ORIGINAL", "false").strip().lower() in ("true", "1", "t", "y", "yes")


def days() -> int:
    from paperless_mrc.main import _env_num
    return _env_num("MRC_KEEP_ORIGINAL_DAYS", 30, int)


def hold_dir() -> Path:
    # Standard: neben der Python-Umgebung von paperless-mrc (/opt/paperless-mrc/originals)
    return Path(os.environ.get("MRC_ORIGINALS_DIR") or Path(sys.prefix).parent / "originals")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> float:
    return time.time()


# ----------------------------------------------------------------------------- Pre-Consume


def hold(path: Path, task_id: str) -> None:
    """Original ablegen, bevor die Arbeitskopie ersetzt wird. Wirft bei Fehlern (dann bleibt die Datei unverändert)."""
    if not task_id:
        raise RuntimeError("TASK_ID fehlt – Original kann nicht zugeordnet werden")
    folder = hold_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{task_id}.pdf"
    shutil.copyfile(path, target)
    if sha256(target) != sha256(path):
        raise RuntimeError("Kopie des Originals fehlerhaft")
    meta = {"name": path.name, "sha256": sha256(target), "held": _now()}
    (folder / f"{task_id}.json").write_text(json.dumps(meta))


def is_own_upload(path: Path) -> bool:
    """Ist die Datei ein Original, das paperless-mrc gerade als Version hochlädt? (dann nicht komprimieren)"""
    folder = hold_dir()
    return folder.is_dir() and (folder / f"{sha256(path)}.version").exists()


# ----------------------------------------------------------------------------- Paperless-API


class Api:
    def __init__(self, url: str, token: str):
        self.base = url.rstrip("/") + "/api/"
        self.token = token

    @classmethod
    def from_env(cls) -> Api:
        token = os.environ.get("MRC_API_TOKEN", "").strip()
        if not token:
            raise RuntimeError("MRC_API_TOKEN fehlt (in paperless.conf eintragen, siehe README)")
        port = os.environ.get("PAPERLESS_PORT", "8000").strip() or "8000"
        return cls(os.environ.get("MRC_API_URL", "").strip() or f"http://localhost:{port}", token)

    def request(self, method: str, path: str, data: dict | None = None,
                files: dict[str, tuple[str, bytes]] | None = None):
        url = path if path.startswith("http") else self.base + path
        headers = {"Authorization": f"Token {self.token}", "Accept": "application/json"}
        body = None
        if files is not None:
            boundary = uuid.uuid4().hex
            parts = []
            for key, value in (data or {}).items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
            for key, (name, content) in files.items():
                quoted = urllib.parse.quote(name)
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{quoted}"\r\n'
                             f"Content-Type: application/pdf\r\n\r\n".encode() + content + b"\r\n")
            body = b"".join(parts) + f"--{boundary}--\r\n".encode()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")[:300]
            raise RuntimeError(f"{method} {path}: HTTP {err.code} {detail}") from None
        return json.loads(raw) if raw else None

    def get_all(self, path: str) -> list[dict]:
        results, url = [], path
        while url:
            page = self.request("GET", url)
            results += page["results"]
            url = page.get("next")
        return results


def find_field(api: Api) -> dict | None:
    """Das Auswahlfeld von paperless-mrc – nur, wenn es wirklich unseres ist (Typ und Options-ids)."""
    for field in api.get_all("custom_fields/?page_size=100"):
        if field["name"] == FIELD_NAME:
            ids = {o.get("id") for o in (field.get("extra_data") or {}).get("select_options") or []}
            if field.get("data_type") != "select" or not {AUTO, KEEP, DELETE} <= ids:
                raise RuntimeError(f"Benutzerfeld „{FIELD_NAME}“ gehört nicht zu paperless-mrc (Typ/Optionen) – "
                                   "bitte umbenennen")
            return field
    return None


def ensure_field(api: Api) -> int:
    """Auswahlfeld anlegen bzw. die Beschriftung an Frist und Sprache anpassen; gibt die id zurück."""
    wanted = options(days())
    field = find_field(api)
    if field is None:
        field = api.request("POST", "custom_fields/", {"name": FIELD_NAME, "data_type": "select",
                                                      "extra_data": {"select_options": wanted}})
    else:
        current = field["extra_data"]["select_options"]
        merged = [next((w for w in wanted if w["id"] == o["id"]), o) for o in current]
        if merged != current:
            api.request("PATCH", f"custom_fields/{field['id']}/",
                        {"extra_data": {**field["extra_data"], "select_options": merged}})
    return field["id"]


def set_field(api: Api, doc_id: int, field_id: int, value: str | None) -> None:
    """Nur dieses Feld setzen (value) bzw. entfernen (None); andere Felder bleiben unberührt."""
    add = {str(field_id): value} if value is not None else {}
    remove = [field_id] if value is None else []
    api.request("POST", "documents/bulk_edit/", {"documents": [doc_id], "method": "modify_custom_fields",
                                                 "parameters": {"add_custom_fields": add,
                                                                "remove_custom_fields": remove}})


# ----------------------------------------------------------------------------- Post-Consume


def attach(api: Api, task_id: str, doc_id: int) -> bool:
    """Abgelegtes Original als Version anhängen und Feld setzen. False: nichts abgelegt für diesen Auftrag."""
    from paperless_mrc.main import log, t

    folder = hold_dir()
    meta_file = folder / f"{task_id}.json"
    if not task_id or not meta_file.exists():
        return False
    meta = json.loads(meta_file.read_text())
    field_id = ensure_field(api)
    marker = folder / f"{meta['sha256']}.version"
    marker.write_text(str(doc_id))  # vor dem Hochladen: die Version kann sofort verarbeitet werden
    try:
        api.request("POST", f"documents/{doc_id}/update_version/", {"version_label": VERSION_LABEL},
                    files={"document": (meta["name"], (folder / f"{task_id}.pdf").read_bytes())})
    except Exception:
        marker.unlink(missing_ok=True)
        raise
    set_field(api, doc_id, field_id, AUTO)
    meta.update(doc_id=doc_id, uploaded=_now())
    meta_file.write_text(json.dumps(meta))
    log(t("original_attached", doc=doc_id, days=days()))
    return True


def post_consume() -> int:
    """Einstieg paperless-mrc-post (PAPERLESS_POST_CONSUME_SCRIPT). Gibt immer 0 zurück: Ein Fehler hier darf die
    Verarbeitung in Paperless nicht scheitern lassen; das Original bleibt dann abgelegt (Aufräumen meldet es)."""
    from paperless_mrc.main import log, t

    task_id, doc = os.environ.get("TASK_ID", ""), os.environ.get("DOCUMENT_ID", "")
    if not (task_id and doc and (hold_dir() / f"{task_id}.json").exists()):
        return 0  # nichts abgelegt (Option aus, nicht komprimiert oder eigene Version)
    try:
        attach(Api.from_env(), task_id, int(doc))
    except Exception as exc:
        log(t("original_attach_failed", doc=doc, error=exc, folder=hold_dir()))
    return 0


# ----------------------------------------------------------------------------- Aufräumen


def load_conf(path: Path = CONF) -> None:
    """paperless.conf (KEY=VALUE) in die Umgebung laden – der Timer läuft außerhalb von Paperless."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _age_days(added: str) -> float:
    stamp = datetime.fromisoformat(added.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 86400


def document_of_task(api: Api, task_id: str) -> int | None:
    """Dokument, das eine Paperless-Aufgabe angelegt hat (API v10+: related_document_ids, v9: related_document)."""
    found = api.request("GET", f"tasks/?task_id={urllib.parse.quote(task_id)}")
    items = found.get("results", []) if isinstance(found, dict) else found or []
    for item in items:
        ids = item.get("related_document_ids") or ([item["related_document"]] if item.get("related_document") else [])
        if ids:
            return int(ids[0])
    return None


def cleanup(api: Api) -> dict:
    """Ein Durchlauf; gibt Zähler zurück (für Log und Tests)."""
    from paperless_mrc.main import log, t

    counts = {"deleted": 0, "kept": 0, "waiting": 0, "released": 0, "attached": 0}
    folder = hold_dir()
    held = []
    if folder.is_dir():
        for meta_file in folder.glob("*.json"):
            held.append((meta_file, json.loads(meta_file.read_text())))
    pending_docs = set()

    # Abgelegte Originale: freigeben, sobald die Version mit passender Prüfsumme in Paperless ist
    for meta_file, meta in held:
        task_id = meta_file.stem
        if "doc_id" not in meta:
            # Nicht angehängt (z. B. Token fehlte oder Paperless war nicht erreichbar): Dokument über die
            # Aufgabe suchen und nachholen
            doc_id = document_of_task(api, task_id)
            if doc_id is not None:
                attach(api, task_id, doc_id)
                counts["attached"] += 1
                pending_docs.add(doc_id)
            elif _now() - meta["held"] > CONFIRM_WARN_HOURS * 3600:
                log(t("original_orphan", file=folder / f"{task_id}.pdf"))
            continue
        try:
            doc = api.request("GET", f"documents/{meta['doc_id']}/")
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
            doc = None  # Dokument in Paperless gelöscht
        if doc is not None and not any(v["checksum"] == meta["sha256"] and not v["is_root"]
                                       for v in doc.get("versions", [])):
            pending_docs.add(meta["doc_id"])
            if _now() - meta["uploaded"] > CONFIRM_WARN_HOURS * 3600:
                log(t("original_not_arrived", doc=meta["doc_id"], file=folder / f"{task_id}.pdf"))
            continue
        for leftover in (folder / f"{task_id}.pdf", meta_file, folder / f"{meta['sha256']}.version"):
            leftover.unlink(missing_ok=True)
        counts["released"] += 1

    field = find_field(api)
    if field is None:
        return counts
    limit = days()
    for doc in api.get_all(f"documents/?custom_fields__id__all={field['id']}&page_size=100"):
        value = next((cf["value"] for cf in doc.get("custom_fields", []) if cf["field"] == field["id"]), None)
        originals = [v for v in doc.get("versions", []) if not v["is_root"] and v.get("version_label") == VERSION_LABEL]
        if not originals:
            if doc["id"] in pending_docs:
                counts["waiting"] += 1
            elif value != KEEP:
                set_field(api, doc["id"], field["id"], None)  # Original gibt es nicht (mehr): Feld entfernen
            continue
        if value == KEEP:
            counts["kept"] += 1
            continue
        if value == DELETE:
            due = True
        elif value in (AUTO, None):
            due = all(_age_days(v["added"]) >= limit for v in originals)
        else:
            log(t("original_unknown_value", doc=doc["id"], value=value))
            continue
        if not due:
            counts["waiting"] += 1
            continue
        for version in originals:
            api.request("DELETE", f"documents/{doc['id']}/versions/{version['id']}/")
        set_field(api, doc["id"], field["id"], None)
        counts["deleted"] += 1
        log(t("original_deleted", doc=doc["id"]))
    return counts


def cleanup_main() -> int:
    """Einstieg paperless-mrc-cleanup (systemd-Timer)."""
    from paperless_mrc.main import log, t

    load_conf()
    try:
        counts = cleanup(Api.from_env())
    except Exception as exc:
        log(t("cleanup_failed", error=exc))
        return 1
    log(t("cleanup_done", **counts))
    return 0
