"""Hermetic tests for the factory home WebUI console host/port flags.

Behavior spec: plain start binds all interfaces (0.0.0.0) on :5561
(loopback and LAN both work, no flags); HAMZABAN_WEBUI_HOST /
HAMZABAN_WEBUI_PORT (or --host / --port) override it for private-only
operation; explicit --host always wins. The boot receipt reproduces
the bound address exactly plus a LAN-visibility note on plain start.
No I/O, no sockets, no behavior change to any route.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.webui import server as webui


def test_default_binds_all_interfaces(monkeypatch):
    monkeypatch.delenv(webui.HOST_ENV_VAR, raising=False)
    monkeypatch.delenv(webui.PORT_ENV_VAR, raising=False)
    # Even with a detectable LAN address, plain start binds all
    # interfaces (loopback and LAN both work).
    monkeypatch.setattr(webui, "_detect_lan_ipv4",
                        lambda: "10.9.9.9")
    args = webui.parse_server_args([])
    assert args.host == "0.0.0.0"
    assert args.port == 5561
    assert isinstance(args.port, int)
    assert webui.ALL_INTERFACES == "0.0.0.0"
    assert webui.HOST == "127.0.0.1"
    assert webui.PORT == 5561


def test_env_overrides_default_bind(monkeypatch):
    monkeypatch.setenv(webui.HOST_ENV_VAR, "127.0.0.1")
    monkeypatch.setenv(webui.PORT_ENV_VAR, "5569")
    monkeypatch.setattr(webui, "_detect_lan_ipv4",
                        lambda: "10.9.9.9")
    args = webui.parse_server_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 5569
    assert isinstance(args.port, int)


def test_flags_override_env_bind(monkeypatch):
    monkeypatch.setenv(webui.HOST_ENV_VAR, "192.168.1.50")
    monkeypatch.setenv(webui.PORT_ENV_VAR, "5569")
    args = webui.parse_server_args(
        ["--host", "127.0.0.1", "--port", "5571"])
    assert args.host == "127.0.0.1"
    assert args.port == 5571
    assert isinstance(args.port, int)


def test_explicit_loopback_flag_binds_loopback_only(monkeypatch):
    monkeypatch.delenv(webui.HOST_ENV_VAR, raising=False)
    monkeypatch.delenv(webui.PORT_ENV_VAR, raising=False)
    args = webui.parse_server_args(["--host", "127.0.0.1"])
    assert args.host == "127.0.0.1"
    assert args.port == 5561


def test_bad_port_env_falls_back_to_standard(monkeypatch):
    monkeypatch.delenv(webui.HOST_ENV_VAR, raising=False)
    monkeypatch.setenv(webui.PORT_ENV_VAR, "not-a-port")
    args = webui.parse_server_args([])
    assert args.port == 5561
    assert isinstance(args.port, int)


def test_boot_receipt_shows_bound_address_and_lan_note():
    lines = webui.build_boot_lines("0.0.0.0", 5561, 123, "10.9.9.9")
    assert lines[0] == "webui boot host=0.0.0.0 port=5561 pid=123"
    assert "10.9.9.9" in lines[1]
    assert "LAN-visible" in lines[1]


def test_boot_receipt_reproduces_explicit_override_exactly():
    lines = webui.build_boot_lines("127.0.0.1", 5561, 123, "10.9.9.9")
    assert lines == ["webui boot host=127.0.0.1 port=5561 pid=123"]
