import asyncio
from pathlib import Path
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import app
from app.mcp_auth import generate_pat
from app.mcp_server import create_mcp_server
from app.projects import create_project, save_chapters, load_chapters, delete_project
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


def test_mcp_server_tools_and_mutation(tmp_path, monkeypatch):
    # Setup temporary projects dir
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.projects.PROJECTS_DIR", projects_dir)
    monkeypatch.setattr("app.mcp_server.PROJECTS_DIR", projects_dir)

    # In-memory tasks
    tasks = {"tts-proj1": {"status": "running", "progress": 20, "is_cancelled": False}}
    cancelled_tasks = []

    def cancel_fn(task_id: str) -> bool:
        if task_id in tasks:
            tasks[task_id]["is_cancelled"] = True
            cancelled_tasks.append(task_id)
            return True
        return False

    server = create_mcp_server(get_tasks=lambda: tasks, cancel_task_fn=cancel_fn)

    # Create a project and chapter
    proj = create_project("Test Book", "Author One")
    save_chapters(
        proj.id,
        [
            {
                "id": "c1",
                "title": "Chapter 1",
                "text": "para-\ngraph\n\n\n\nnext line",
                "include_in_audio": True,
            }
        ],
    )

    async def run_tool_tests():
        # 1. Test cancel_task
        await server.call_tool("cancel_task", {"task_id": "tts-proj1"})
        assert "tts-proj1" in cancelled_tasks
        assert tasks["tts-proj1"]["is_cancelled"] is True

        # 2. Test update_chapter_content
        await server.call_tool(
            "update_chapter_content",
            {
                "project_id": proj.id,
                "chapter_id": "c1",
                "title": "Chapter 1: The Beginning",
            },
        )
        chaps = load_chapters(proj.id)
        assert chaps[0]["title"] == "Chapter 1: The Beginning"

        # 3. Test clean_chapter_text
        await server.call_tool(
            "clean_chapter_text",
            {
                "project_id": proj.id,
                "chapter_id": "c1",
                "apply": True,
            },
        )
        chaps = load_chapters(proj.id)
        assert chaps[0]["text"] == "paragraph\n\nnext line"

        # 4. Test delete_narratible_project without confirm
        try:
            await server.call_tool("delete_narratible_project", {"project_id": proj.id, "confirm": False})
            assert False, "Should have failed without confirm=True"
        except Exception as e:
            assert "confirm must be True" in str(e)

    asyncio.run(run_tool_tests())

    # Clean up project
    delete_project(proj.id)


def test_mcp_http_auth_and_toggle(tmp_path, monkeypatch):
    tokens_file = tmp_path / "mcp_tokens.json"
    monkeypatch.setattr("app.mcp_auth.RUNTIME_DIR", tmp_path)
    monkeypatch.setattr("app.mcp_auth.TOKENS_FILE", tokens_file)

    # Generate a valid token
    _, raw_token = generate_pat("Test Client")

    with TestClient(app) as client:
        # 1. When MCP is disabled: should return 403
        monkeypatch.setattr("app.main.load_config", lambda: AppConfig(mcp_enabled=False))
        resp = client.get("/mcp", headers={"Authorization": f"Bearer {raw_token}"})
        assert resp.status_code == 403
        assert "disabled" in resp.json()["error"].lower()

        # 2. When MCP is enabled but no token provided: should return 401
        monkeypatch.setattr("app.main.load_config", lambda: AppConfig(mcp_enabled=True))
        resp = client.get("/mcp")
        assert resp.status_code == 401
        assert "unauthorized" in resp.json()["error"].lower()

        # 3. When MCP is enabled with invalid token: should return 401
        resp = client.get("/mcp", headers={"Authorization": "Bearer ntb_bogus"})
        assert resp.status_code == 401

        # 4. When MCP is enabled with valid token via header or query param
        resp = client.get("/mcp", headers={"Authorization": f"Bearer {raw_token}"})
        assert resp.status_code not in (401, 403)

        resp_query = client.get(f"/mcp?token={raw_token}")
        assert resp_query.status_code not in (401, 403)
