"""Tests for the packaged desktop launcher."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import desktop_app  # noqa: E402


def test_run_server_disables_uvicorn_console_logging(monkeypatch):
    captured = {}

    def fake_run(application, **kwargs):
        captured["application"] = application
        captured.update(kwargs)

    monkeypatch.setattr(desktop_app.uvicorn, "run", fake_run)

    desktop_app._run_server(8123)

    assert captured["application"] is desktop_app.app
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8123
    assert captured["log_config"] is None