from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.desktop_runtime import (
    DesktopRuntimeCallbacks,
    clear_desktop_runtime,
    register_desktop_runtime,
)


@pytest.fixture(autouse=True)
def clear_runtime_callbacks():
    clear_desktop_runtime()
    yield
    clear_desktop_runtime()


@pytest.fixture
def desktop_calls():
    calls = []
    register_desktop_runtime(
        DesktopRuntimeCallbacks(
            open_app=lambda: calls.append("app"),
            open_diagnostics=lambda: calls.append("diagnostics"),
            open_log_folder=lambda: calls.append("logs"),
            request_shutdown=lambda: calls.append("shutdown"),
        )
    )
    return calls


def test_health_reports_desktop_capabilities_only_when_registered(desktop_calls):
    client = TestClient(main.app)

    assert client.get("/api/health").json()["desktop"]["available"] is True

    clear_desktop_runtime()

    assert client.get("/api/health").json()["desktop"]["available"] is False


def test_desktop_logs_returns_filtered_tail_and_offset(tmp_path, monkeypatch, desktop_calls):
    log_file = tmp_path / "narratible.log"
    log_file.write_text(
        "2026-08-27 INFO [app] ready\n2026-08-27 ERROR [app] parse failed\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "LOG_FILE", log_file)

    response = TestClient(main.app).get(
        "/api/desktop/logs?level=error&contains=parse",
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "log_file": str(log_file),
        "lines": ["2026-08-27 ERROR [app] parse failed"],
        "line_count": 1,
        "next_offset": log_file.stat().st_size,
    }


def test_desktop_log_watch_delegates_filters(monkeypatch, desktop_calls):
    captured = {}

    async def fake_watch(path: Path, **kwargs):
        captured["path"] = path
        captured.update(kwargs)
        return {"lines": ["new line"], "next_offset": 42, "line_count": 1}

    monkeypatch.setattr(main, "watch_file_lines", fake_watch)

    response = TestClient(main.app).get(
        "/api/desktop/logs/watch?start_offset=12&seconds=1&max_lines=25&level=warning&contains=slow"
    )

    assert response.status_code == 200
    assert response.json()["lines"] == ["new line"]
    assert captured == {
        "path": main.LOG_FILE,
        "start_offset": 12,
        "seconds": 1.0,
        "max_lines": 25,
        "level": "warning",
        "contains": "slow",
    }


def test_desktop_actions_invoke_registered_callbacks(desktop_calls):
    client = TestClient(main.app)

    assert client.post("/api/desktop/open-log-folder").status_code == 200
    assert client.post("/api/desktop/quit").status_code == 202

    assert desktop_calls == ["logs", "shutdown"]


def test_desktop_controls_reject_unavailable_and_cross_site_requests(desktop_calls):
    client = TestClient(main.app)

    cross_site = client.get(
        "/api/desktop/logs",
        headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://example.com"},
    )
    assert cross_site.status_code == 403

    wrong_origin = client.get(
        "/api/desktop/logs",
        headers={"Origin": "https://example.com"},
    )
    assert wrong_origin.status_code == 403

    clear_desktop_runtime()
    unavailable = client.get("/api/desktop/logs")
    assert unavailable.status_code == 503