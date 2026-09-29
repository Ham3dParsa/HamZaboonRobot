"""CLI arbitrate tests (stub transports; one stub-HTTP end-to-end).

Covers: file I/O + receipt + exit codes, limit flag, missing key-var
fatal, unknown provider fatal, empty senses fatal, and the real
openai_compat transport against a loopback stub server (no external
network, ever).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from factory.linking import cli as _cli


def _write_screened(path):
    with open(path, "w", encoding="utf-8") as handle:
        for i in range(3):
            handle.write(json.dumps({
                "lemma": "run", "sense": {
                    "sense_id": "run#%d" % i, "id": "en-run-%d" % i,
                    "glosses": ["move fast"],
                    "examples": [{"text": "run fast"}],
                    "tags": ["verb"]}}) + "\n")


def _write_table(path):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("kaikki_sense_id\twordnet_sensekey\tmethod\tevidence\tprovenance\n")
        handle.write("en-run-0\trun%2:38:00::\tLINK:2-sig\te\tp\n")


def _stub_transport(answer):
    class _Adapter:
        def __init__(self):
            self.prompts = []

        def execute_arbitration(self, prompt):
            self.prompts.append(prompt)
            return answer
    return _Adapter()


def test_arbitrate_happy_writes_verdicts_and_receipt(tmp_path, monkeypatch,
                                                     capsys):
    screened = str(tmp_path / "s.jsonl")
    table = str(tmp_path / "t.tsv")
    out = str(tmp_path / "v.jsonl")
    _write_screened(screened)
    _write_table(table)
    answer = ('{"verdict": "LINK", "winner_index": 1, '
              '"kaikki_evidence": "move", "wordnet_evidence": "move"}')
    monkeypatch.setattr(_cli, "_build_transport",
                        lambda args, key: _stub_transport(answer))
    code = _cli.main(["arbitrate", "--in", screened, "--out", out,
                      "--table", table, "--provider", "stub",
                      "--model", "stub-m", "--limit", "2"])
    assert code == 0
    rows = [json.loads(line) for line in open(out, encoding="utf-8")]
    assert len(rows) == 2
    assert rows[0]["verdict"] == "link"
    assert rows[0]["target_synset"] == "run%2:38:00::"
    assert rows[0]["model"] == "stub-m"
    assert rows[1]["verdict"] is None  # no candidates -> abstain path
    err = capsys.readouterr().err
    assert "provider=stub" in err and "replay:" in err


def test_arbitrate_empty_senses_fatal(tmp_path):
    screened = str(tmp_path / "s.jsonl")
    open(screened, "w").close()
    code = _cli.main(["arbitrate", "--in", screened,
                      "--out", str(tmp_path / "v.jsonl"),
                      "--provider", "stub", "--model", "m",
                      "--endpoint", "http://127.0.0.1:9/v1"])
    assert code == 1


def test_arbitrate_missing_key_var_fatal(tmp_path, monkeypatch):
    screened = str(tmp_path / "s.jsonl")
    _write_screened(screened)
    monkeypatch.delenv("DEFINITELY_ABSENT_KEY_VAR_XYZ", raising=False)
    code = _cli.main(["arbitrate", "--in", screened,
                      "--out", str(tmp_path / "v.jsonl"),
                      "--provider", "stub", "--model", "m",
                      "--key-var", "DEFINITELY_ABSENT_KEY_VAR_XYZ"])
    assert code == 1


def test_arbitrate_unknown_provider_fatal(tmp_path):
    screened = str(tmp_path / "s.jsonl")
    _write_screened(screened)
    code = _cli.main(["arbitrate", "--in", screened,
                      "--out", str(tmp_path / "v.jsonl"),
                      "--provider", "no-such-provider-xyz",
                      "--model", "m"])
    assert code == 1


class _Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        answer = {"verdict": "NONE", "winner_index": None,
                  "kaikki_evidence": "move fast", "wordnet_evidence": ""}
        payload = {"choices": [{"message": {"content": json.dumps(answer)}}]}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_arbitrate_openai_transport_end_to_end(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = "http://127.0.0.1:%d/v1" % server.server_address[1]
        screened = str(tmp_path / "s.jsonl")
        table = str(tmp_path / "t.tsv")
        out = str(tmp_path / "v.jsonl")
        _write_screened(screened)
        _write_table(table)
        code = _cli.main(["arbitrate", "--in", screened, "--out", out,
                          "--table", table, "--provider", "stub-local",
                          "--model", "stub-m", "--endpoint", endpoint,
                          "--limit", "1"])
        assert code == 0
        rows = [json.loads(line) for line in open(out, encoding="utf-8")]
        assert rows[0]["verdict"] == "none"
    finally:
        server.shutdown()
        thread.join(timeout=5)
