"""serve.py — HTTP server for FSRS Replay web app.

Endpoints:
  POST /api/simulate  — run simulation with JSON params, return JSON result
  GET  /*             — serve static files (index.html, archive/*, etc.)
"""

import http.server
import socketserver
import json
import os
import re
import sys
import threading
import webbrowser

DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 8000

# Import sim_runner (must be in same directory)
sys.path.insert(0, DIR)
from sim_runner import run_simulation

# Cache cards at module load
_cards_cache = None

def _load_cards():
    global _cards_cache
    if _cards_cache is not None:
        return _cards_cache
    path = os.path.join(DIR, "archive", "simulator_cards.js")
    if not os.path.exists(path):
        _cards_cache = []
        return _cards_cache
    with open(path, "r", encoding="utf-8") as f:
        js = f.read()
    match = re.search(r"var SIMULATOR_CARDS\s*=\s*(\[.*?\]);", js, re.DOTALL)
    if match:
        _cards_cache = json.loads(match.group(1))
    else:
        _cards_cache = []
    return _cards_cache


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def do_POST(self):
        if self.path == "/api/simulate":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                params = json.loads(body)

                cards = _load_cards()
                params["cards"] = cards

                result = run_simulation(params)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(result, ensure_ascii=False, default=str).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def _find_free_port(start=8000):
    for port in range(start, start + 10):
        try:
            httpd = socketserver.TCPServer(("", port), Handler)
            httpd.server_close()
            return port
        except OSError:
            continue
    return None


if __name__ == "__main__":
    port = _find_free_port(PORT)
    if port is None:
        print("ERROR: No free port found (tried 8000-8009)")
        exit(1)

    def _open():
        webbrowser.open(f"http://localhost:{port}/")

    print(f"FSRS Replay — v5.4 Engine")
    print(f"URL: http://localhost:{port}/")
    print(f"Directory: {DIR}")
    print("Close this window to stop the server.")
    print()

    threading.Timer(1.5, _open).start()

    with socketserver.TCPServer(("", port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            httpd.server_close()
