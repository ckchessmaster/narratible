import pytest

from app.desktop_runtime import (
    DesktopRuntimeCallbacks,
    DesktopRuntimeUnavailable,
    clear_desktop_runtime,
    desktop_capabilities,
    open_desktop_app,
    open_desktop_diagnostics,
    open_desktop_log_folder,
    register_desktop_runtime,
    request_desktop_shutdown,
)


@pytest.fixture(autouse=True)
def clear_runtime_callbacks():
    clear_desktop_runtime()
    yield
    clear_desktop_runtime()


def test_registered_desktop_runtime_exposes_and_invokes_capabilities():
    calls = []
    register_desktop_runtime(
        DesktopRuntimeCallbacks(
            open_app=lambda: calls.append("app"),
            open_diagnostics=lambda: calls.append("diagnostics"),
            open_log_folder=lambda: calls.append("logs"),
            request_shutdown=lambda: calls.append("shutdown"),
        )
    )

    assert desktop_capabilities() == {
        "available": True,
        "logs": True,
        "open_log_folder": True,
        "quit": True,
    }

    open_desktop_app()
    open_desktop_diagnostics()
    open_desktop_log_folder()
    request_desktop_shutdown()

    assert calls == ["app", "diagnostics", "logs", "shutdown"]


def test_unregistered_desktop_runtime_rejects_invocation():
    assert desktop_capabilities()["available"] is False

    with pytest.raises(DesktopRuntimeUnavailable, match="not available"):
        request_desktop_shutdown()