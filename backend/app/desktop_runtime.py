from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock


class DesktopRuntimeUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class DesktopRuntimeCallbacks:
    open_app: Callable[[], None]
    open_diagnostics: Callable[[], None]
    open_log_folder: Callable[[], None]
    request_shutdown: Callable[[], None]


_lock = RLock()
_callbacks: DesktopRuntimeCallbacks | None = None


def register_desktop_runtime(callbacks: DesktopRuntimeCallbacks) -> None:
    global _callbacks
    with _lock:
        _callbacks = callbacks


def clear_desktop_runtime() -> None:
    global _callbacks
    with _lock:
        _callbacks = None


def desktop_capabilities() -> dict[str, bool]:
    with _lock:
        available = _callbacks is not None
    return {
        "available": available,
        "logs": available,
        "open_log_folder": available,
        "quit": available,
    }


def _require_callbacks() -> DesktopRuntimeCallbacks:
    with _lock:
        callbacks = _callbacks
    if callbacks is None:
        raise DesktopRuntimeUnavailable("Desktop controls are not available in this runtime.")
    return callbacks


def open_desktop_app() -> None:
    _require_callbacks().open_app()


def open_desktop_diagnostics() -> None:
    _require_callbacks().open_diagnostics()


def open_desktop_log_folder() -> None:
    _require_callbacks().open_log_folder()


def request_desktop_shutdown() -> None:
    _require_callbacks().request_shutdown()