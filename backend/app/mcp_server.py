import argparse
import sys
from collections.abc import Callable, Mapping
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP as MCPServer
except ImportError:
    from mcp.server import MCPServer

from .config import load_config
from .cleaner import regex_clean_text
from .epub import build_epub
from .projects import (
    get_project,
    list_projects,
    load_chapters,
    save_chapters,
    update_chapter,
    update_project,
    delete_project as delete_project_dir,
    PROJECTS_DIR,
    _project_path,
)
from .runtime_engines import nvidia_preflight, runtime_status
from .runtime_state import (
    LOG_FILE,
    current_file_offset,
    load_engine_manifest,
    load_task_snapshot,
    save_task_snapshot,
    tail_file_lines,
    watch_file_lines,
)
from .tts import get_available_voices


TaskProvider = Callable[[], Mapping[str, Mapping[str, Any]]]
CancelTaskFn = Callable[[str], bool]


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
    cancel_task_fn: CancelTaskFn | None = None,
) -> MCPServer:
    try:
        mcp = MCPServer(
            "narratible",
            version="0.2.0",
            instructions=(
                "Tools and resources for full management of the local Narratible app, "
                "including project metadata, chapter editing, TTS voices and engines, "
                "EPUB generation, background task cancellation, and live log monitoring."
            ),
        )
    except TypeError:
        mcp = MCPServer(
            "narratible",
            instructions=(
                "Tools and resources for full management of the local Narratible app, "
                "including project metadata, chapter editing, TTS voices and engines, "
                "EPUB generation, background task cancellation, and live log monitoring."
            ),
        )

    # ── Inspection Tools ──────────────────────────────────────────────────────

    @mcp.tool()
    def app_info() -> dict[str, Any]:
        """Return local narratible runtime paths, configuration state, and counts."""
        cfg = load_config()
        projects = list_projects()
        task_payload = _task_payload(get_tasks)
        return {
            "name": "narratible",
            "mcp_enabled": cfg.mcp_enabled,
            "projects_dir": str(PROJECTS_DIR),
            "log_file": str(LOG_FILE),
            "project_count": len(projects),
            "task_count": len(task_payload["tasks"]),
            "task_source": task_payload["source"],
            "default_tts_engine": cfg.default_tts_engine,
            "llm_provider": cfg.llm_provider,
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
        """Return saved chapter metadata and summaries for a project."""
        return load_chapters(project_id)

    @mcp.tool()
    def get_chapter_content(project_id: str, chapter_id: str) -> dict[str, Any]:
        """Return the full text and metadata for a specific chapter."""
        chapters = load_chapters(project_id)
        for idx, chap in enumerate(chapters):
            if str(chap.get("id")) == str(chapter_id) or str(idx) == str(chapter_id):
                return chap
        raise ValueError(f"Chapter '{chapter_id}' not found in project '{project_id}'.")

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
    def list_available_voices(engine: str = "edge-tts") -> list[dict[str, Any]]:
        """List available voices for a given TTS engine (edge-tts, kokoro, f5-tts, chatterbox)."""
        return get_available_voices(engine)

    @mcp.tool()
    def get_runtime_status() -> dict[str, Any]:
        """Return GPU preflight information, local engine installation states, and hardware info."""
        return {
            "preflight": nvidia_preflight(),
            "status": runtime_status(),
            "manifest": load_engine_manifest(),
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

    # ── Action & Mutation Tools ───────────────────────────────────────────────

    @mcp.tool()
    def cancel_task(task_id: str) -> dict[str, Any]:
        """Abort or request cancellation of a running background task (parse, TTS, or modernization)."""
        cancelled = False
        if cancel_task_fn is not None:
            cancelled = cancel_task_fn(task_id)
        else:
            snapshot = load_task_snapshot()
            tasks = snapshot.get("tasks", {})
            if task_id in tasks:
                tasks[task_id]["is_cancelled"] = True
                cancelled = True
            for prefix in ("parse-", "tts-", "modernize-"):
                key = f"{prefix}{task_id}"
                if key in tasks:
                    tasks[key]["is_cancelled"] = True
                    cancelled = True
            if cancelled:
                save_task_snapshot(tasks)

        return {
            "task_id": task_id,
            "cancelled": cancelled,
            "message": "Task cancellation requested." if cancelled else f"Task '{task_id}' not found in active tasks.",
        }

    @mcp.tool()
    def update_project_metadata(
        project_id: str,
        title: str | None = None,
        author: str | None = None,
        description: str | None = None,
        language: str | None = None,
        tts_engine: str | None = None,
        tts_voice: str | None = None,
        tts_speed: float | None = None,
    ) -> dict[str, Any]:
        """Update metadata settings for a project."""
        get_project(project_id)
        patch = {}
        if title is not None:
            patch["title"] = title
        if author is not None:
            patch["author"] = author
        if description is not None:
            patch["description"] = description
        if language is not None:
            patch["language"] = language
        if tts_engine is not None:
            patch["tts_engine"] = tts_engine
        if tts_voice is not None:
            patch["tts_voice"] = tts_voice
        if tts_speed is not None:
            patch["tts_speed"] = tts_speed

        return update_project(project_id, patch).model_dump()

    @mcp.tool()
    def delete_narratible_project(project_id: str, confirm: bool = False) -> dict[str, Any]:
        """Permanently delete a project and all its chapters, audio, and exports. Requires confirm=True."""
        if not confirm:
            raise ValueError("confirm must be True to permanently delete a project.")
        delete_project_dir(project_id)
        return {
            "project_id": project_id,
            "status": "deleted",
            "message": f"Project '{project_id}' was deleted successfully.",
        }

    @mcp.tool()
    def update_chapter_content(
        project_id: str,
        chapter_id: str,
        title: str | None = None,
        text: str | None = None,
        include_in_audio: bool | None = None,
    ) -> dict[str, Any]:
        """Update title, text, or inclusion flag for a project chapter."""
        get_project(project_id)
        patch = {}
        if title is not None:
            patch["title"] = title
        if text is not None:
            patch["text"] = text
        if include_in_audio is not None:
            patch["include_in_audio"] = include_in_audio

        return update_chapter(project_id, chapter_id, patch)

    @mcp.tool()
    def clean_chapter_text(
        project_id: str,
        chapter_id: str,
        profile: str = "balanced",
        apply: bool = False,
    ) -> dict[str, Any]:
        """Run regex cleaning rules on a chapter's text, optionally updating the chapter in place."""
        chapters = load_chapters(project_id)
        target_chapter = None
        for idx, chap in enumerate(chapters):
            if str(chap.get("id")) == str(chapter_id) or str(idx) == str(chapter_id):
                target_chapter = chap
                break
        if target_chapter is None:
            raise ValueError(f"Chapter '{chapter_id}' not found in project '{project_id}'.")

        original_text = target_chapter.get("text", "")
        cleaned_text = regex_clean_text(original_text)
        if apply and cleaned_text != original_text:
            target_chapter["text"] = cleaned_text
            save_chapters(project_id, chapters)

        return {
            "project_id": project_id,
            "chapter_id": chapter_id,
            "profile": profile,
            "applied": apply,
            "original_length": len(original_text),
            "cleaned_length": len(cleaned_text),
            "preview": cleaned_text[:400],
        }

    @mcp.tool()
    def export_project_epub(project_id: str) -> dict[str, Any]:
        """Build an EPUB export file for the given project."""
        meta = get_project(project_id)
        chapters = load_chapters(project_id)
        if not chapters:
            raise ValueError(f"Project '{project_id}' has no chapters.")

        exports_dir = _project_path(project_id) / "exports"
        exports_dir.mkdir(exist_ok=True)
        safe_title = "".join(c for c in meta.title if c.isalnum() or c in (" ", "-", "_")).strip() or project_id
        output_path = exports_dir / f"{safe_title}.epub"

        cover_path = None
        if meta.cover_image:
            candidate = _project_path(project_id) / meta.cover_image
            if candidate.exists():
                cover_path = candidate

        build_epub(
            output_path=output_path,
            title=meta.title,
            author=meta.author,
            language=meta.language,
            description=meta.description,
            publisher=meta.publisher,
            subject=meta.subject,
            isbn=meta.isbn,
            series=meta.series,
            chapters=chapters,
            cover_image_path=cover_path,
        )

        return {
            "status": "success",
            "output_path": str(output_path),
            "filename": output_path.name,
            "file_size": output_path.stat().st_size,
        }

    # ── Resources ─────────────────────────────────────────────────────────────

    @mcp.resource("narratible://logs/latest", mime_type="text/plain")
    def latest_logs() -> str:
        """Recent backend logs as a text resource."""
        return "\n".join(tail_file_lines(LOG_FILE, lines=200))

    @mcp.resource("narratible://projects", mime_type="application/json")
    def all_projects_resource() -> list[dict[str, Any]]:
        """List of all local Narratible projects."""
        return [p.model_dump() for p in list_projects()]

    @mcp.resource("narratible://projects/{project_id}", mime_type="application/json")
    def single_project_resource(project_id: str) -> dict[str, Any]:
        """Project metadata and chapter list."""
        meta = get_project(project_id).model_dump()
        meta["chapters"] = load_chapters(project_id)
        return meta

    @mcp.resource("narratible://projects/{project_id}/chapters/{chapter_id}", mime_type="application/json")
    def single_chapter_resource(project_id: str, chapter_id: str) -> dict[str, Any]:
        """Full text and details for a specific chapter."""
        chapters = load_chapters(project_id)
        for idx, chap in enumerate(chapters):
            if str(chap.get("id")) == str(chapter_id) or str(idx) == str(chapter_id):
                return chap
        raise ValueError(f"Chapter '{chapter_id}' not found in project '{project_id}'.")

    @mcp.resource("narratible://runtime/status", mime_type="application/json")
    def runtime_status_resource() -> dict[str, Any]:
        """Managed AI engines, GPU preflight, and hardware specs."""
        return {
            "preflight": nvidia_preflight(),
            "status": runtime_status(),
            "manifest": load_engine_manifest(),
        }

    # ── Prompts ───────────────────────────────────────────────────────────────

    @mcp.prompt()
    def diagnose_pipeline_error(task_id: str) -> list[dict[str, Any]]:
        """Prompt template to diagnose a failed parsing, OCR, or TTS task."""
        payload = _task_payload(get_tasks)
        task = payload["tasks"].get(task_id, {})
        recent_errors = tail_file_lines(LOG_FILE, lines=40, level="ERROR")
        error_context = (
            f"Task ID: {task_id}\n"
            f"Task Status: {task.get('status', 'unknown')}\n"
            f"Stage: {task.get('stage', 'unknown')}\n"
            f"Message: {task.get('message', 'none')}\n"
            f"Recent Log Errors:\n" + ("\n".join(recent_errors) if recent_errors else "No error lines found in log.")
        )
        return [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": (
                        f"Please analyze the following task failure in the Narratible audiobook processing pipeline:\n\n"
                        f"{error_context}\n\n"
                        f"Identify the likely root cause (e.g. missing dependencies, CUDA out of memory, malformed PDF, "
                        f"LLM API quota, network timeout) and explain how the user or agent can recover from it."
                    ),
                },
            }
        ]

    @mcp.prompt()
    def audit_chapter_cleaning(project_id: str, chapter_id: str) -> list[dict[str, Any]]:
        """Prompt template to inspect a chapter's text for OCR and cleaning artifacts."""
        chapters = load_chapters(project_id)
        target_chapter = None
        for idx, chap in enumerate(chapters):
            if str(chap.get("id")) == str(chapter_id) or str(idx) == str(chapter_id):
                target_chapter = chap
                break
        if not target_chapter:
            raise ValueError(f"Chapter '{chapter_id}' not found in project '{project_id}'.")
        text_snippet = target_chapter.get("text", "")[:4000]
        return [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": (
                        f"Audit the following extracted chapter text for Narratible audiobook narration:\n"
                        f"Chapter: {target_chapter.get('title', 'Untitled')}\n\n"
                        f"--- Text Sample ---\n{text_snippet}\n--- End Text Sample ---\n\n"
                        f"Check for:\n"
                        f"1. Remaining page numbers, running headers, or footnote anchors.\n"
                        f"2. Broken hyphenation across line breaks.\n"
                        f"3. OCR noise or corrupt characters.\n"
                        f"4. Missing section breaks or dialogue formatting issues.\n"
                        f"Suggest specific edits or cleaning rules to improve TTS listening quality."
                    ),
                },
            }
        ]

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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run MCP server even if disabled in application settings.",
    )
    args = parser.parse_args()

    cfg = load_config()
    if not cfg.mcp_enabled and not args.force:
        sys.stderr.write(
            "Error: MCP server is disabled in Narratible settings.\n"
            "Enable it in Settings or pass --force to run anyway.\n"
        )
        sys.exit(1)

    mcp = create_mcp_server()
    if args.transport == "stdio":
        mcp.run("stdio")
    elif args.transport == "streamable-http":
        mcp.run(
            "streamable-http",
            host=args.host,
            port=args.port,
            streamable_http_path="/mcp",
            stateless_http=True,
        )
    else:
        mcp.run("sse", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
