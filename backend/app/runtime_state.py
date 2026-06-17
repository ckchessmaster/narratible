import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _app_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        app_data = Path(os.environ.get("APPDATA", Path.home())) / "narratible"
        app_data.mkdir(parents=True, exist_ok=True)
        return app_data
    return Path(__file__).parent.parent


APP_DATA_DIR = _app_data_dir()
RUNTIME_DIR = APP_DATA_DIR / "runtime"
LOG_DIR = APP_DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "narratible.log"
TASKS_FILE = RUNTIME_DIR / "tasks.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_task_snapshot(tasks: dict[str, dict]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _utc_now(),
        "tasks": tasks,
    }
    tmp_path = TASKS_FILE.with_name(f"{TASKS_FILE.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, TASKS_FILE)


def load_task_snapshot() -> dict[str, Any]:
    if not TASKS_FILE.exists():
        return {"updated_at": None, "tasks": {}}
    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "updated_at": data.get("updated_at"),
        "tasks": data.get("tasks") or {},
    }


def _validate_positive_int(name: str, value: int, maximum: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value < 1 or value > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}.")
    return value


def _matches_filters(line: str, level: str | None, contains: str | None) -> bool:
    if level:
        normalized_level = level.strip().upper()
        if not normalized_level:
            raise ValueError("level cannot be blank.")
        if f" {normalized_level} " not in line.upper() and f"{normalized_level}:" not in line.upper():
            return False
    if contains and contains.lower() not in line.lower():
        return False
    return True


def tail_file_lines(
    path: Path,
    *,
    lines: int = 200,
    level: str | None = None,
    contains: str | None = None,
    max_bytes: int = 2_000_000,
) -> list[str]:
    lines = _validate_positive_int("lines", lines, 1000)
    if not path.exists():
        return []

    file_size = path.stat().st_size
    with open(path, "rb") as f:
        f.seek(max(0, file_size - max_bytes))
        text = f.read().decode("utf-8", errors="replace")

    filtered = [
        line
        for line in text.splitlines()
        if _matches_filters(line, level, contains)
    ]
    return filtered[-lines:]


def current_file_offset(path: Path) -> int:
    if not path.exists():
        return 0
    return path.stat().st_size


async def watch_file_lines(
    path: Path,
    *,
    start_offset: int | None = None,
    seconds: float = 10.0,
    max_lines: int = 200,
    level: str | None = None,
    contains: str | None = None,
    poll_interval: float = 0.25,
    max_bytes_per_read: int = 250_000,
) -> dict[str, Any]:
    max_lines = _validate_positive_int("max_lines", max_lines, 1000)
    try:
        seconds = float(seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("seconds must be a number.") from exc
    if seconds < 0.1 or seconds > 60:
        raise ValueError("seconds must be between 0.1 and 60.")

    offset = current_file_offset(path) if start_offset is None else max(0, int(start_offset))
    deadline = time.monotonic() + seconds
    collected: list[str] = []

    while time.monotonic() < deadline and len(collected) < max_lines:
        if path.exists():
            file_size = path.stat().st_size
            if file_size < offset:
                offset = 0
            if file_size > offset:
                with open(path, "rb") as f:
                    f.seek(offset)
                    chunk = f.read(min(file_size - offset, max_bytes_per_read))
                offset += len(chunk)
                for line in chunk.decode("utf-8", errors="replace").splitlines():
                    if _matches_filters(line, level, contains):
                        collected.append(line)
                        if len(collected) >= max_lines:
                            break
        if collected:
            break
        await asyncio.sleep(poll_interval)

    return {
        "path": str(path),
        "start_offset": start_offset,
        "next_offset": offset,
        "lines": collected,
        "line_count": len(collected),
    }
