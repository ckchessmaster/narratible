import argparse
from collections.abc import Callable, Mapping
from typing import Any

from mcp.server.fastmcp import FastMCP

from .projects import get_project, list_projects, load_chapters, PROJECTS_DIR
from .runtime_state import (
    LOG_FILE,
    current_file_offset,
    load_task_snapshot,
    tail_file_lines,
    watch_file_lines,
)


TaskProvider = Callable[[], Mapping[str, Mapping[str, Any]]]


def _task_payload(get_tasks: TaskProvider | None) -> dict[str, Any]:
    if get_tasks is not None:
        return {
            "updated_at": None,
            "tasks": dict(get_tasks()),
            "source": "process",
        }
    payload = load_task_snapshot()
    return {
        "updated_at": payload["updated_at"],
        "tasks": payload["tasks"],
        "source": "snapshot",
    }


def create_mcp_server(
    get_tasks: TaskProvider | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    streamable_http_path: str = "/mcp",
) -> FastMCP:
    mcp = FastMCP(
        "narratible",
        instructions=(
            "Tools for inspecting the local narratible app, including live log "
            "watching, project metadata, chapters, and background task status."
        ),
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
        stateless_http=True,
    )

    @mcp.tool()
    def app_info() -> dict[str, Any]:
        """Return local narratible runtime paths and counts."""
        projects = list_projects()
        task_payload = _task_payload(get_tasks)
        return {
            "name": "narratible",
            "projects_dir": str(PROJECTS_DIR),
            "log_file": str(LOG_FILE),
            "project_count": len(projects),
            "task_count": len(task_payload["tasks"]),
            "task_source": task_payload["source"],
        }

    @mcp.tool()
    def list_narratible_projects() -> list[dict[str, Any]]:
        """List all local narratible projects."""
        return [project.model_dump() for project in list_projects()]

    @mcp.tool()
    def get_narratible_project(project_id: str) -> dict[str, Any]:
        """Return metadata for a single narratible project."""
        return get_project(project_id).model_dump()

    @mcp.tool()
    def list_project_chapters(project_id: str) -> list[dict[str, Any]]:
        """Return saved chapter metadata and text for a project."""
        return load_chapters(project_id)

    @mcp.tool()
    def list_tasks() -> dict[str, Any]:
        """Return known parse/TTS background task states."""
        return _task_payload(get_tasks)

    @mcp.tool()
    def get_task_status(task_id: str) -> dict[str, Any]:
        """Return one parse/TTS background task state."""
        payload = _task_payload(get_tasks)
        task = payload["tasks"].get(task_id)
        if task is None:
            raise ValueError(f"Task '{task_id}' was not found.")
        return {
            "updated_at": payload["updated_at"],
            "source": payload["source"],
            "task_id": task_id,
            "task": task,
        }

    @mcp.tool()
    def get_log_cursor() -> dict[str, Any]:
        """Return the current log file byte offset for later watch_logs calls."""
        return {
            "log_file": str(LOG_FILE),
            "offset": current_file_offset(LOG_FILE),
        }

    @mcp.tool()
    def tail_logs(
        lines: int = 200,
        level: str | None = None,
        contains: str | None = None,
    ) -> dict[str, Any]:
        """Return recent backend log lines, optionally filtered by level/text."""
        log_lines = tail_file_lines(LOG_FILE, lines=lines, level=level, contains=contains)
        return {
            "log_file": str(LOG_FILE),
            "lines": log_lines,
            "line_count": len(log_lines),
            "next_offset": current_file_offset(LOG_FILE),
        }

    @mcp.tool()
    async def watch_logs(
        seconds: float = 10.0,
        start_offset: int | None = None,
        max_lines: int = 200,
        level: str | None = None,
        contains: str | None = None,
    ) -> dict[str, Any]:
        """Wait for new backend log lines and return them with the next offset."""
        return await watch_file_lines(
            LOG_FILE,
            start_offset=start_offset,
            seconds=seconds,
            max_lines=max_lines,
            level=level,
            contains=contains,
        )

    @mcp.resource("narratible://logs/latest")
    def latest_logs() -> str:
        """Recent backend logs as a text resource."""
        return "\n".join(tail_file_lines(LOG_FILE, lines=200))

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the narratible MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
        help="MCP transport to run. Use stdio for most local agent integrations.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for standalone HTTP transports.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for standalone HTTP transports.",
    )
    args = parser.parse_args()

    mcp = create_mcp_server(host=args.host, port=args.port)
    mcp.run(args.transport)


if __name__ == "__main__":
    main()
