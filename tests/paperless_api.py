# SPDX-License-Identifier: AGPL-3.0-or-later
"""Nachbau der Teile der Paperless-ngx-API (3.3.0), die originals.py nutzt – mit denselben Regeln:
Token-Auth, seitenweise Listen mit „next“, Auswahlfelder (select_options mit ids, Wert = id), Versionsliste im
Dokument (neueste zuerst, is_root), Root-Version nicht löschbar, update_version verarbeitet die Datei wie
consume_file (hier: Aufruf des Pre-Consume-Hooks und SHA-256 der Datei als Prüfsumme)."""

import email.parser
import email.policy
import hashlib
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TOKEN = "testtoken"


class Paperless:
    def __init__(self, tmp: Path, consume_hook=None):
        self.tmp = tmp
        self.consume_hook = consume_hook  # (Pfad der hochgeladenen Datei) -> None, wie das Pre-Consume-Skript
        self.fields: list[dict] = []
        self.docs: dict[int, dict] = {}
        self.next_id = 100
        self.calls: list[str] = []
        self.tasks: dict[str, int] = {}  # TASK_ID → angelegtes Dokument
        self.fail_bulk_edit = 0  # so viele bulk_edit-Aufrufe scheitern lassen
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def add_document(self, doc_id: int, path: Path, task_id: str = "task-1") -> dict:
        self.tasks[task_id] = doc_id
        doc = {"id": doc_id, "custom_fields": [], "versions": [
            {"id": doc_id, "added": _iso(datetime.now(timezone.utc)), "version_label": None,
             "checksum": hashlib.sha256(path.read_bytes()).hexdigest(), "is_root": True}]}
        self.docs[doc_id] = doc
        return doc

    def view(self, doc: dict) -> dict:
        versions = sorted(doc["versions"], key=lambda v: (v["is_root"], -v["id"]))  # neueste zuerst, Root zuletzt
        return {**doc, "versions": versions}

    def _handler(self):
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, payload=None):
                body = json.dumps(payload).encode() if payload is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self):
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def _auth(self):
                if self.headers.get("Authorization") != f"Token {TOKEN}":
                    self._send(401, {"detail": "Invalid token."})
                    return False
                return True

            def _page(self, items, query):
                size = int(query.get("page_size", ["25"])[0])
                page = int(query.get("page", ["1"])[0])
                chunk = items[(page - 1) * size: page * size]
                nxt = None
                if page * size < len(items):
                    nxt = f"{api.url}{urlparse(self.path).path}?page_size={size}&page={page + 1}" + "".join(
                        f"&{k}={v[0]}" for k, v in query.items() if k not in ("page", "page_size"))
                return {"count": len(items), "next": nxt, "results": chunk}

            def do_GET(self):
                if not self._auth():
                    return
                url = urlparse(self.path)
                query = parse_qs(url.query)
                api.calls.append(f"GET {url.path}")
                if url.path == "/api/custom_fields/":
                    return self._send(200, self._page(api.fields, query))
                if url.path == "/api/tasks/":  # API v10: seitenweise, related_document_ids
                    task_id = query.get("task_id", [""])[0]
                    items = [{"task_id": task_id, "status": "success", "related_document_ids": [api.tasks[task_id]]}
                             ] if task_id in api.tasks else []
                    return self._send(200, self._page(items, query))
                if url.path == "/api/documents/":
                    docs = list(api.docs.values())
                    if "custom_fields__id__all" in query:
                        fid = int(query["custom_fields__id__all"][0])
                        docs = [d for d in docs if any(cf["field"] == fid for cf in d["custom_fields"])]
                    return self._send(200, self._page([api.view(d) for d in docs], query))
                m = re.fullmatch(r"/api/documents/(\d+)/", url.path)
                if m and int(m.group(1)) in api.docs:
                    return self._send(200, api.view(api.docs[int(m.group(1))]))
                self._send(404, {"detail": "Not found."})

            def do_POST(self):
                if not self._auth():
                    return
                path = urlparse(self.path).path
                api.calls.append(f"POST {path}")
                body = self._body()
                if path == "/api/custom_fields/":
                    data = json.loads(body)
                    opts = (data.get("extra_data") or {}).get("select_options")
                    if data.get("data_type") == "select" and (not opts or not all(o.get("label") for o in opts)):
                        return self._send(400, {"error": "extra_data.select_options must be a valid list"})
                    for o in opts or []:
                        o.setdefault("id", f"rnd{api._id()}")
                    field = {"id": api._id(), **data}
                    api.fields.append(field)
                    return self._send(201, field)
                if path == "/api/documents/bulk_edit/":
                    if api.fail_bulk_edit:
                        api.fail_bulk_edit -= 1
                        return self._send(500, "Error performing bulk edit, check logs for more detail.")
                    data = json.loads(body)
                    assert data["method"] == "modify_custom_fields"
                    params = data["parameters"]
                    for raw_id, value in params.get("add_custom_fields", {}).items():
                        field = next(f for f in api.fields if f["id"] == int(raw_id))
                        if field["data_type"] == "select" and value not in [
                                o["id"] for o in field["extra_data"]["select_options"]]:
                            return self._send(400, ["Value must be an id of an element in select_options"])
                        for doc_id in data["documents"]:
                            doc = api.docs[doc_id]
                            doc["custom_fields"] = [cf for cf in doc["custom_fields"] if cf["field"] != int(raw_id)]
                            doc["custom_fields"].append({"field": int(raw_id), "value": value})
                    for fid in params.get("remove_custom_fields", []):
                        for doc_id in data["documents"]:
                            doc = api.docs[doc_id]
                            doc["custom_fields"] = [cf for cf in doc["custom_fields"] if cf["field"] != int(fid)]
                    return self._send(200, {"result": "OK"})
                m = re.fullmatch(r"/api/documents/(\d+)/update_version/", path)
                if m and int(m.group(1)) in api.docs:
                    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                        f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode() + body)
                    parts = {p.get_param("name", header="content-disposition"): p for p in msg.iter_parts()}
                    content = parts["document"].get_payload(decode=True)
                    label = parts["version_label"].get_payload(decode=True).decode() if "version_label" in parts else None
                    upload = api.tmp / f"upload-{api._id()}.pdf"
                    upload.write_bytes(content)
                    if api.consume_hook:  # wie consume_file: Pre-Consume-Skript auf der Arbeitskopie
                        api.consume_hook(upload)
                    doc = api.docs[int(m.group(1))]
                    doc["versions"].append({"id": api._id(), "added": _iso(datetime.now(timezone.utc)),
                                            "version_label": label, "is_root": False,
                                            "checksum": hashlib.sha256(upload.read_bytes()).hexdigest()})
                    return self._send(200, "task-id")
                self._send(404, {"detail": "Not found."})

            def do_PATCH(self):
                if not self._auth():
                    return
                path = urlparse(self.path).path
                api.calls.append(f"PATCH {path}")
                m = re.fullmatch(r"/api/custom_fields/(\d+)/", path)
                field = next((f for f in api.fields if m and f["id"] == int(m.group(1))), None)
                if field is None:
                    return self._send(404, {"detail": "Not found."})
                field.update(json.loads(self._body()))
                self._send(200, field)

            def do_DELETE(self):
                if not self._auth():
                    return
                path = urlparse(self.path).path
                api.calls.append(f"DELETE {path}")
                m = re.fullmatch(r"/api/documents/(\d+)/versions/(\d+)/", path)
                doc = api.docs.get(int(m.group(1))) if m else None
                version = next((v for v in doc["versions"] if v["id"] == int(m.group(2))), None) if doc else None
                if version is None:
                    return self._send(404, {"detail": "Not found."})
                if version["is_root"]:
                    return self._send(400, "Cannot delete the root/original version. Delete the document instead.")
                doc["versions"].remove(version)
                self._send(200, {"result": "OK", "current_version_id": doc["id"]})

        return Handler


def _iso(stamp: datetime) -> str:
    return stamp.isoformat().replace("+00:00", "Z")


def age(doc: dict, label: str, days: float) -> None:
    """Version mit diesem Label künstlich altern lassen."""
    for v in doc["versions"]:
        if v["version_label"] == label:
            v["added"] = _iso(datetime.now(timezone.utc) - timedelta(days=days))
