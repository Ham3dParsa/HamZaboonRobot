#!/usr/bin/env python3
"""Run the project-status editor on loopback with a browser UI.

Start it with:

    python -m issues.local_editor

The startup URL contains a one-time login token. The server binds only to
127.0.0.1 and delegates all changes to status_editor.py.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from issues import status_editor, validate

MAX_BODY_BYTES = 1_000_000
SESSION_COOKIE = "status_editor_session"
CSRF_COOKIE = "status_editor_csrf"
EDITABLE_FIELDS = {
    "issues": status_editor.ALLOWED_ISSUE_FIELDS,
    "phases": status_editor.ALLOWED_PHASE_FIELDS,
    "decisions": status_editor.ALLOWED_DECISION_FIELDS,
}
MULTILINE_FIELDS = {"problem", "solution", "note", "evidence", "summary"}


def _record_id(record_type: str, record: dict) -> str:
    return str(record["id"])


def _field_value(record: dict, field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, (list, dict, bool, int, float)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _coerce_value(raw: str, original: object) -> object:
    if isinstance(original, bool):
        lowered = raw.strip().lower()
        if lowered not in {"true", "false"}:
            raise ValueError("boolean fields must be true or false")
        return lowered == "true"
    if isinstance(original, int) and not isinstance(original, bool):
        return int(raw)
    if isinstance(original, (list, dict)):
        return json.loads(raw)
    return raw


def changes_from_form(form: dict[str, list[str]], records: dict[str, list[dict]]) -> dict:
    changes = {"issues": [], "phases": [], "decisions": []}
    by_id = {
        (record_type, _record_id(record_type, record)): record
        for record_type, record_list in records.items()
        for record in record_list
    }
    grouped: dict[tuple[str, str], dict] = {}
    for name, values in form.items():
        if not name.startswith(("issues:", "phases:", "decisions:")):
            continue
        record_type, record_id, field = name.split(":", 2)
        if field not in EDITABLE_FIELDS[record_type]:
            raise ValueError(f"unsupported field: {field}")
        if len(values) != 1:
            raise ValueError("each field must have one value")
        original = by_id[(record_type, record_id)].get(field, "")
        value = _coerce_value(values[0], original)
        grouped.setdefault((record_type, record_id), {"id": int(record_id) if record_id.isdigit() else record_id})[
            field
        ] = value
    for (record_type, _), change in grouped.items():
        changes[record_type].append(change)
    return changes


def _html_page(issues: list[dict], project_status: dict) -> str:
    records = {
        "issues": issues,
        "phases": project_status["phases"],
        "decisions": project_status["decisions"],
    }
    sections: list[str] = []
    for record_type, record_list in records.items():
        sections.append(f"<section><h2>{record_type.title()}</h2>")
        for record in record_list:
            record_id = _record_id(record_type, record)
            title = record.get("title", record.get("name", record_id))
            sections.append(f"<fieldset><legend>{record_id}: {_escape(str(title))}</legend>")
            for field in sorted(EDITABLE_FIELDS[record_type]):
                if field not in record:
                    continue
                value = _escape(_field_value(record, field))
                label = field.replace("_", " ")
                if field in MULTILINE_FIELDS or isinstance(record[field], (list, dict)):
                    sections.append(
                        f'<label>{_escape(label)}<textarea name="{record_type}:{record_id}:{field}">{value}</textarea></label>'
                    )
                else:
                    sections.append(
                        f'<label>{_escape(label)}<input name="{record_type}:{record_id}:{field}" value="{value}"></label>'
                    )
            sections.append("</fieldset>")
        sections.append("</section>")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>HamZaboon status editor</title>
<style>
body {{ font: 14px system-ui, sans-serif; margin: 2rem auto; max-width: 1100px; color: #172033; }}
fieldset {{ display: grid; gap: .45rem; margin: .8rem 0; border: 1px solid #cbd5e1; border-radius: .5rem; }}
label {{ display: grid; gap: .2rem; }} input, textarea {{ font: inherit; padding: .35rem; }}
textarea {{ min-height: 3rem; }} section {{ margin-bottom: 2rem; }}
button {{ padding: .55rem .8rem; margin-right: .5rem; cursor: pointer; }}
#result {{ white-space: pre-wrap; background: #f8fafc; padding: 1rem; overflow: auto; }}
</style></head><body>
<h1>HamZaboon project status editor</h1>
<p>Changes are validated against canonical JSON. Preview before applying.</p>
<form id="editor">{''.join(sections)}
<button type="submit">Preview changes</button>
<button id="apply" type="button" disabled>Apply preview</button>
</form><pre id="result">No preview yet.</pre>
<script>
const form = document.getElementById("editor");
const result = document.getElementById("result");
const apply = document.getElementById("apply");
let previewed = false;
async function send(path) {{
  const body = {{}};
  for (const [key, value] of new FormData(form)) {{
    (body[key] ??= []).push(value);
  }}
  const response = await fetch(path, {{
    method: "POST", headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify(body)
  }});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "request failed");
  return data;
}}
form.addEventListener("submit", async (event) => {{
  event.preventDefault(); apply.disabled = true; previewed = false;
  try {{ const data = await send("/preview"); result.textContent = data.diff;
    previewed = data.changed; apply.disabled = !previewed;
  }} catch (error) {{ result.textContent = error.message; }}
}});
apply.addEventListener("click", async () => {{
  if (!previewed || !confirm("Apply the validated preview?")) return;
  try {{ const data = await send("/apply"); result.textContent = data.message; apply.disabled = true; previewed = false; }}
  catch (error) {{ result.textContent = error.message; }}
}});
</script></body></html>"""


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class EditorServer:
    def __init__(self) -> None:
        self.login_token = secrets.token_urlsafe(32)
        self.sessions: dict[str, str] = {}
        self.pending_previews: dict[str, str] = {}
        self.lock = threading.Lock()

    def authenticate(self, token: str) -> str | None:
        if not hmac.compare_digest(token, self.login_token):
            return None
        session = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions[session] = csrf
            self.login_token = secrets.token_urlsafe(32)
        return session

    def csrf_for(self, session: str) -> str | None:
        with self.lock:
            return self.sessions.get(session)

    def remember_preview(self, session: str, documents: dict[Path, str]) -> None:
        digest = _documents_digest(documents)
        with self.lock:
            self.pending_previews[session] = digest

    def consume_preview(self, session: str, documents: dict[Path, str]) -> bool:
        digest = _documents_digest(documents)
        with self.lock:
            if self.pending_previews.get(session) != digest:
                return False
            del self.pending_previews[session]
            return True


def _documents_digest(documents: dict[Path, str]) -> str:
    hasher = hashlib.sha256()
    for path, content in documents.items():
        hasher.update(str(path).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(content.encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()


class EditorHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer

    def _editor_server(self) -> EditorServer:
        return self.server.editor_server  # type: ignore[attr-defined]

    def _cookies(self) -> SimpleCookie:
        cookies = SimpleCookie()
        cookies.load(self.headers.get("Cookie", ""))
        return cookies

    def _session(self) -> tuple[str, str] | None:
        cookies = self._cookies()
        session = cookies.get(SESSION_COOKIE)
        csrf = cookies.get(CSRF_COOKIE)
        if session is None or csrf is None:
            return None
        expected = self._editor_server().csrf_for(session.value)
        if expected is None or not hmac.compare_digest(expected, csrf.value):
            return None
        return session.value, csrf.value

    def _send(self, status: HTTPStatus, content: str, content_type: str = "text/html") -> None:
        payload = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status: HTTPStatus, payload: dict) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False), "application/json")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            token = parse_qs(parsed.query).get("token", [""])[0]
            session = self._editor_server().authenticate(token)
            if session is None:
                self._send(HTTPStatus.UNAUTHORIZED, "Invalid login token", "text/plain")
                return
            csrf = self._editor_server().csrf_for(session)
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}={session}; HttpOnly; SameSite=Strict")
            self.send_header("Set-Cookie", f"{CSRF_COOKIE}={csrf}; SameSite=Strict")
            self.end_headers()
            return
        if parsed.path != "/":
            self._send(HTTPStatus.NOT_FOUND, "Not found", "text/plain")
            return
        if self._session() is None:
            self._send(HTTPStatus.UNAUTHORIZED, "Open the startup login URL first", "text/plain")
            return
        self._send(HTTPStatus.OK, _html_page(validate.load_data(), validate.load_project_status()))

    def _read_json(self) -> tuple[list[dict], dict]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("request body is missing or too large")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        form = {key: value if isinstance(value, list) else [value] for key, value in payload.items()}
        return status_editor.apply_changes(
            validate.load_data(),
            validate.load_project_status(),
            changes_from_form(
                form,
                {
                    "issues": validate.load_data(),
                    "phases": validate.load_project_status()["phases"],
                    "decisions": validate.load_project_status()["decisions"],
                },
            ),
        )

    def do_POST(self) -> None:
        session_data = self._session()
        if session_data is None:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication required"})
            return
        session, _ = session_data
        try:
            updated_issues, updated_status = self._read_json()
            documents = status_editor.generated_documents(updated_issues, updated_status)
            if self.path == "/preview":
                diff = status_editor.preview_documents(documents)
                self._editor_server().remember_preview(session, documents)
                self._json(HTTPStatus.OK, {"changed": diff != "No changes.", "diff": diff})
                return
            if self.path == "/apply":
                if not self._editor_server().consume_preview(session, documents):
                    self._json(
                        HTTPStatus.CONFLICT,
                        {"error": "preview the exact changes before applying them"},
                    )
                    return
                status_editor.apply_documents(documents)
                self._json(HTTPStatus.OK, {"message": "Applied and synchronized status changes."})
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})


def run(host: str, port: int, open_browser: bool) -> None:
    editor_server = EditorServer()
    server = ThreadingHTTPServer((host, port), EditorHandler)
    server.editor_server = editor_server  # type: ignore[attr-defined]
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}/login?{urlencode({'token': editor_server.login_token})}"
    print(f"Local project-status editor: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("the editor must bind to loopback")
    run(args.host, args.port, not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
