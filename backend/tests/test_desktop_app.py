"""Tests for the packaged desktop launcher."""

import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import desktop_app  # noqa: E402
from backend.app.desktop_runtime import (  # noqa: E402
    desktop_capabilities,
    open_desktop_app,
    open_desktop_diagnostics,
    open_desktop_log_folder,
    request_desktop_shutdown,
)


def test_run_server_disables_uvicorn_console_logging(monkeypatch):
    captured = {"ran": False}

    class FakeServer:
        def __init__(self, config):
            captured["config"] = config

        def run(self):
            captured["ran"] = True

    def fake_config(application, **kwargs):
        captured["application"] = application
        captured.update(kwargs)
        return "config"

    monkeypatch.setattr(desktop_app.uvicorn, "Config", fake_config)
    monkeypatch.setattr(desktop_app.uvicorn, "Server", FakeServer)

    desktop_app._run_server(8123)

    assert captured["ran"] is True
    assert captured["application"] is desktop_app.app
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8123
    assert captured["log_config"] is None


def test_request_server_shutdown_sets_should_exit():
    class FakeServer:
        should_exit = False

    server = FakeServer()

    desktop_app._request_server_shutdown(server)

    assert server.should_exit is True


def test_tray_menu_routes_actions(monkeypatch):
    opened_urls = []
    calls = []
    pending_threads = []

    class FakeMenuItem:
        def __init__(self, text, action, default=False):
            self.text = text
            self.action = action
            self.default = default

    class FakeMenu:
        SEPARATOR = object()

        def __init__(self, *items):
            self.items = items

    class FakeIcon:
        def __init__(self, name, image, title, menu):
            self.name = name
            self.image = image
            self.title = title
            self.menu = menu
            self.stopped = False

        def stop(self):
            self.stopped = True

    class FakeImageFile:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def copy(self):
            return "icon-image"

    class FakeThread:
        def __init__(self, *, target, args, name, daemon):
            self.target = target
            self.args = args
            self.name = name
            self.daemon = daemon

        def start(self):
            pending_threads.append(self)

    server = SimpleNamespace(should_exit=False)
    fake_pystray = SimpleNamespace(Icon=FakeIcon, Menu=FakeMenu, MenuItem=FakeMenuItem)
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)
    monkeypatch.setattr("PIL.Image.open", lambda _path: FakeImageFile())
    monkeypatch.setattr(desktop_app.webbrowser, "open", opened_urls.append)
    monkeypatch.setattr(desktop_app, "_open_log_folder", lambda: calls.append("logs"))
    monkeypatch.setattr(desktop_app, "_ask_to_quit", lambda: True)
    monkeypatch.setattr(desktop_app.threading, "Thread", FakeThread)

    icon = desktop_app._create_tray_icon("http://127.0.0.1:8123", server)
    open_item, diagnostics_item, _, logs_item, quit_item = icon.menu.items

    assert open_item.default is True
    open_item.action(icon, open_item)
    diagnostics_item.action(icon, diagnostics_item)
    logs_item.action(icon, logs_item)
    quit_item.action(icon, quit_item)

    assert opened_urls == [
        "http://127.0.0.1:8123",
        "http://127.0.0.1:8123/?diagnostics=1",
    ]
    assert calls == ["logs"]
    assert len(pending_threads) == 1
    assert pending_threads[0].name == "narratible-quit-confirmation"
    assert pending_threads[0].daemon is True
    assert server.should_exit is False
    assert icon.stopped is False

    pending_threads[0].target(*pending_threads[0].args)

    assert server.should_exit is True
    assert icon.stopped is True


@pytest.mark.parametrize("server_error", [None, RuntimeError("startup failed")])
def test_desktop_app_registers_callbacks_and_always_cleans_up(monkeypatch, server_error):
    opened_urls = []
    calls = []

    class FakeServer:
        should_exit = False

        def run(self):
            assert desktop_capabilities()["available"] is True
            open_desktop_app()
            open_desktop_diagnostics()
            open_desktop_log_folder()
            request_desktop_shutdown()
            if server_error:
                raise server_error

    class FakeTray:
        def run(self):
            calls.append("tray-run")

        def stop(self):
            calls.append("tray-stop")

    server = FakeServer()
    monkeypatch.setattr(desktop_app, "_create_server", lambda _port: server)
    monkeypatch.setattr(desktop_app, "_create_tray_icon", lambda _url, _server: FakeTray())
    monkeypatch.setattr(desktop_app, "open_browser", lambda _url: calls.append("browser-ready"))
    monkeypatch.setattr(desktop_app.webbrowser, "open", opened_urls.append)
    monkeypatch.setattr(desktop_app, "_open_log_folder", lambda: calls.append("logs"))

    if server_error:
        with pytest.raises(RuntimeError, match="startup failed"):
            desktop_app._run_desktop_app(8123)
    else:
        desktop_app._run_desktop_app(8123)

    assert server.should_exit is True
    assert opened_urls == [
        "http://127.0.0.1:8123",
        "http://127.0.0.1:8123/?diagnostics=1",
    ]
    assert "logs" in calls
    assert "tray-stop" in calls
    assert desktop_capabilities()["available"] is False