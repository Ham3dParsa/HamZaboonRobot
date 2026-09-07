"""xray-core child manager: one loopback HTTP proxy per server.

Spawns tools/egress/bin/xray.exe with a generated config (see xrayconf),
waits for the port, kills on rotate/stop. Windows-safe: NO_WINDOW on
Popen, atexit fallback kill, temp configs unlinked on every exit path
(they carry credentials).
"""
from __future__ import annotations

import atexit
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

_LIVE = []

BIN_DIR = pathlib.Path(__file__).resolve().parent / "bin"
XRAY = BIN_DIR / "xray.exe"


def free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def xray_available():
    return XRAY.exists()


def check_port(port, timeout=1.0):
    try:
        conn = socket.create_connection(("127.0.0.1", port),
                                        timeout=timeout)
        conn.close()
        return True
    except OSError:
        return False


def egress_ip_via_proxy(proxy_url, timeout=15):
    """Public egress IP as seen through proxy_url (http://127.0.0.1:P).

    Uses an explicit opener: Request.set_proxy does not take effect on
    the shared global opener (verified live 2026-09-07).
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(
        {"http": proxy_url, "https": proxy_url}))
    with opener.open("https://api.ipify.org", timeout=timeout) as resp:
        return resp.read().decode().strip()


def _cleanup_all():
    for tun in list(_LIVE):
        try:
            tun.stop()
        except Exception:  # noqa: BLE001 (exit path never raises)
            pass


atexit.register(_cleanup_all)


class Tunnel:
    """One xray child for one server dict (from parse_subscription)."""

    def __init__(self, server, link):
        self.server = server
        self.link = link
        self.port = None
        self.proc = None
        self.cfg_path = None

    def start(self, timeout=25):
        try:
            from . import xrayconf
        except ImportError:  # run as top-level script, not a package
            import xrayconf
        if not xray_available():
            raise RuntimeError("xray.exe missing in tools/egress/bin")
        node = xrayconf.parse_link(self.link)
        self.port = free_port()
        cfg = xrayconf.xray_config(node, self.port)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(cfg, tmp)
        tmp.close()
        self.cfg_path = tmp.name
        _LIVE.append(self)
        try:
            creation = 0
            if sys.platform == "win32":
                creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.proc = subprocess.Popen(
                [str(XRAY), "-c", self.cfg_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=creation)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError(
                        "xray exited early (bad link/config?)")
                if check_port(self.port):
                    return self.proxy_url
                time.sleep(0.4)
            raise RuntimeError("xray port never opened (timeout)")
        except Exception:
            self.stop()
            raise

    @property
    def proxy_url(self):
        return "http://127.0.0.1:%d" % self.port if self.port else ""

    def egress_ip(self, timeout=15):
        return egress_ip_via_proxy(self.proxy_url, timeout=timeout)

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=8)
            except Exception:  # noqa: BLE001 (kill must not raise)
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        self.proc = None
        if self.cfg_path:
            try:
                os.unlink(self.cfg_path)
            except OSError:
                pass
            self.cfg_path = None
        try:
            _LIVE.remove(self)
        except ValueError:
            pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
        return False
