import asyncio

from app.runtime_state import load_task_snapshot, save_task_snapshot, tail_file_lines, watch_file_lines


def test_tail_file_lines_filters_recent_lines(tmp_path):
    log_file = tmp_path / "narratible.log"
    log_file.write_text(
        "\n".join(
            [
                "2026-01-01 00:00:00 INFO [app] started",
                "2026-01-01 00:00:01 WARNING [app] slow request",
                "2026-01-01 00:00:02 ERROR [app] parse boom",
            ]
        ),
        encoding="utf-8",
    )

    assert tail_file_lines(log_file, lines=2) == [
        "2026-01-01 00:00:01 WARNING [app] slow request",
        "2026-01-01 00:00:02 ERROR [app] parse boom",
    ]
    assert tail_file_lines(log_file, lines=10, level="error", contains="boom") == [
        "2026-01-01 00:00:02 ERROR [app] parse boom",
    ]


def test_watch_file_lines_returns_new_lines_from_offset(tmp_path):
    log_file = tmp_path / "narratible.log"
    log_file.write_text("old line\n", encoding="utf-8")
    start_offset = log_file.stat().st_size

    async def append_and_watch():
        async def append_later():
            await asyncio.sleep(0.05)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write("new line\n")

        writer = asyncio.create_task(append_later())
        result = await watch_file_lines(
            log_file,
            start_offset=start_offset,
            seconds=1,
            poll_interval=0.01,
        )
        await writer
        return result

    result = asyncio.run(append_and_watch())

    assert result["lines"] == ["new line"]
    assert result["line_count"] == 1
    assert result["next_offset"] > start_offset


def test_task_snapshot_round_trips_runtime_state(tmp_path, monkeypatch):
    tasks_file = tmp_path / "tasks.json"
    monkeypatch.setattr("app.runtime_state.RUNTIME_DIR", tmp_path)
    monkeypatch.setattr("app.runtime_state.TASKS_FILE", tasks_file)

    save_task_snapshot({"parse-1": {"status": "running", "progress": 50}})

    snapshot = load_task_snapshot()
    assert snapshot["updated_at"]
    assert snapshot["tasks"] == {"parse-1": {"status": "running", "progress": 50}}
