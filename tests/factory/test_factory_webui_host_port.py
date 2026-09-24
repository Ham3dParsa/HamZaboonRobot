"""Hermetic tests for the factory home WebUI console host/port flags.

Behavior spec: the server entry point serves loopback :5561 by default;
HAMZABAN_WEBUI_HOST / HAMZABAN_WEBUI_PORT (or --host / --port) override
it so the console can be reached on the local network (tablet access).
No I/O, no sockets, no behavior change to any route.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.webui import server as webui


def test_defaults_are_loopback_and_standard_port(monkeypatch):
    monkeypatch.delenv(webui.HOST_ENV_VAR, raising=False)
    monkeypatch.delenv(webui.PORT_ENV_VAR, raising=False)
    args = webui.parse_server_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 5561
    assert isinstance(args.port, int)
    assert webui.HOST == "127.0.0.1"
    assert webui.PORT == 5561


def test_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv(webui.HOST_ENV_VAR, "192.168.1.50")
    monkeypatch.setenv(webui.PORT_ENV_VAR, "5569")
    args = webui.parse_server_args([])
    assert args.host == "192.168.1.50"
    assert args.port == 5569
    assert isinstance(args.port, int)


def test_flags_override_env(monkeypatch):
    monkeypatch.setenv(webui.HOST_ENV_VAR, "192.168.1.50")
    monkeypatch.setenv(webui.PORT_ENV_VAR, "5569")
    args = webui.parse_server_args(
        ["--host", "0.0.0.0", "--port", "5571"])
    assert args.host == "0.0.0.0"
    assert args.port == 5571
    assert isinstance(args.port, int)


def test_bad_port_env_falls_back_to_standard(monkeypatch):
    monkeypatch.delenv(webui.HOST_ENV_VAR, raising=False)
    monkeypatch.setenv(webui.PORT_ENV_VAR, "not-a-port")
    args = webui.parse_server_args([])
    assert args.port == 5561
    assert isinstance(args.port, int)
