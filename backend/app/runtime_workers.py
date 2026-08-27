"""Persistent subprocess workers for isolated local-AI runtime profiles."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any, Callable
import uuid

from .runtime_engines import RuntimeSetupError, installed_profile_state
from .subprocess_utils import hidden_process_kwargs

logger = logging.getLogger(__name__)


def _worker_script(profile_id: str) -> Path:
    filename = profile_id.replace("-", "_") + "_worker.py"
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return bundle_root / "runtime_workers" / filename
    return Path(__file__).resolve().parent / "runtime_worker_scripts" / filename


class RuntimeWorker:
    def __init__(self, profile_id: str):
        self.profile_id = profile_id
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def _start(self) -> subprocess.Popen[str]:
        state = installed_profile_state(self.profile_id)
        if state is None:
            raise RuntimeSetupError(f"Runtime profile {self.profile_id} is not installed and verified.")
        worker_path = _worker_script(self.profile_id)
        if not worker_path.is_file():
            raise RuntimeSetupError(f"Runtime worker source is missing: {worker_path}")
        command_env = os.environ.copy()
        command_env["PYTHONUTF8"] = "1"
        process = subprocess.Popen(
            [state["python_executable"], "-u", str(worker_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=command_env,
            **hidden_process_kwargs(),
        )
        threading.Thread(target=self._drain_stderr, args=(process,), daemon=True).start()
        self._process = process
        return process

    def _drain_stderr(self, process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            logger.info("%s worker: %s", self.profile_id, line.rstrip())

    def _running_process(self) -> subprocess.Popen[str]:
        if self._process is None or self._process.poll() is not None:
            self.stop()
            return self._start()
        return self._process

    def request(
        self,
        action: str,
        payload: dict[str, Any],
        progress_cb: Callable[[str, int], None] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            process = self._running_process()
            if process.stdin is None or process.stdout is None:
                raise RuntimeSetupError(f"Runtime worker {self.profile_id} has no IPC streams.")
            request_id = uuid.uuid4().hex
            request = {"request_id": request_id, "action": action, **payload}
            try:
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
            except OSError as exc:
                self.stop()
                raise RuntimeSetupError(f"Runtime worker {self.profile_id} stopped unexpectedly.") from exc

            while True:
                line = process.stdout.readline()
                if not line:
                    return_code = process.poll()
                    self.stop()
                    raise RuntimeSetupError(
                        f"Runtime worker {self.profile_id} exited unexpectedly ({return_code})."
                    )
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Ignoring invalid %s worker output: %s", self.profile_id, line.rstrip())
                    continue
                if event.get("request_id") != request_id:
                    continue
                if event.get("type") == "progress":
                    if progress_cb is not None:
                        progress_cb(event.get("message", ""), int(event.get("progress", 0)))
                    continue
                if event.get("type") == "error":
                    raise RuntimeSetupError(event.get("message") or f"{self.profile_id} worker failed.")
                if event.get("type") == "result":
                    return event

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is None:
            try:
                if process.stdin is not None:
                    process.stdin.write(json.dumps({"action": "shutdown"}) + "\n")
                    process.stdin.flush()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


_workers: dict[str, RuntimeWorker] = {}


def _runtime_worker(profile_id: str) -> RuntimeWorker:
    worker = _workers.get(profile_id)
    if worker is None:
        worker = RuntimeWorker(profile_id)
        _workers[profile_id] = worker
    return worker


async def synthesize_kokoro(
    *,
    text: str,
    output_path: Path,
    voice: str,
    speed: float,
    device: str,
    segments: list[dict[str, Any]],
    progress_cb: Callable[[str, int], None] | None = None,
) -> None:
    await asyncio.to_thread(
        _runtime_worker("kokoro").request,
        "synthesize",
        {
            "text": text,
            "output_path": str(output_path),
            "voice": voice,
            "speed": speed,
            "device": device,
            "segments": segments,
        },
        progress_cb,
    )


async def synthesize_clone_engine(
    profile_id: str,
    *,
    output_path: Path,
    reference_path: Path,
    reference_text: str | None,
    speed: float,
    temperature: float,
    device: str,
    segments: list[dict[str, Any]],
    exaggeration: float = 0.5,
    cfg_weight: float = 0.3,
    progress_cb: Callable[[str, int], None] | None = None,
) -> None:
    await asyncio.to_thread(
        _runtime_worker(profile_id).request,
        "synthesize",
        {
            "output_path": str(output_path),
            "reference_path": str(reference_path),
            "reference_text": reference_text or "",
            "speed": speed,
            "temperature": temperature,
            "device": device,
            "segments": segments,
            "exaggeration": exaggeration,
            "cfg_weight": cfg_weight,
        },
        progress_cb,
    )


def shutdown_runtime_workers() -> None:
    for worker in list(_workers.values()):
        worker.stop()
    _workers.clear()