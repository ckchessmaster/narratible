"""Tests for the managed local-AI runtime contract."""

import json
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main, runtime_engines, runtime_state, runtime_workers, subprocess_utils, tts  # noqa: E402


def _write_catalog(path: Path, *, allow_cpu_fallback: bool = False) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "worker_protocol_version": 1,
                "python_version": "3.12",
                "pytorch": {
                    "version": "2.11.0",
                    "torchaudio_version": "2.11.0",
                    "backend": "cu128",
                    "index_url": "https://download.pytorch.org/whl/cu128",
                    "allow_cpu_fallback": allow_cpu_fallback,
                },
                "profiles": [
                    {
                        "id": "kokoro",
                        "label": "Kokoro",
                        "kind": "tts",
                        "default_install": True,
                        "requires_cuda": True,
                        "model_download": "installer",
                        "estimated_download_mb": 3100,
                        "estimated_disk_mb": 6200,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_catalog_rejects_cpu_fallback(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.json"
    _write_catalog(catalog, allow_cpu_fallback=True)
    monkeypatch.setenv("NARRATIBLE_RUNTIME_CATALOG", str(catalog))

    with pytest.raises(ValueError, match="disable CPU PyTorch fallback"):
        runtime_engines.load_runtime_catalog()


def test_catalog_rejects_cpu_sourced_profile_lock(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.json"
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text('version = "2.11.0+cpu"\n', encoding="utf-8")
    _write_catalog(catalog)
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    payload["profiles"][0].update(
        lock_file="uv.lock",
        lock_sha256=runtime_engines.hashlib.sha256(lock_path.read_bytes()).hexdigest(),
    )
    catalog.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("NARRATIBLE_RUNTIME_CATALOG", str(catalog))

    with pytest.raises(ValueError, match="forbidden CPU PyTorch source"):
        runtime_engines.load_runtime_catalog()


def test_real_kokoro_lock_contains_worker_audio_dependency():
    catalog = runtime_engines.load_runtime_catalog()
    profile = next(item for item in catalog["profiles"] if item["id"] == "kokoro")
    lock_text = (runtime_engines.catalog_path().parent / profile["lock_file"]).read_text(
        encoding="utf-8"
    )

    assert 'name = "soundfile"' in lock_text
    assert 'specifier = "==0.14.0"' in lock_text
    assert "+cpu" not in lock_text


def test_real_catalog_exposes_managed_clone_profiles():
    profiles = {
        profile["id"]: profile
        for profile in runtime_engines.load_runtime_catalog()["profiles"]
    }

    assert profiles["f5-tts"]["lock_file"] == "f5-tts/uv.lock"
    assert profiles["chatterbox"]["lock_file"] == "chatterbox/uv.lock"
    assert profiles["qwen3-tts"]["availability"] == "coming_soon"
    for profile_id in ("f5-tts", "chatterbox"):
        lock_text = (
            runtime_engines.catalog_path().parent / profiles[profile_id]["lock_file"]
        ).read_text(encoding="utf-8")
        assert "2.11.0+cu128" in lock_text
        assert "+cpu" not in lock_text


def test_frozen_runtime_python_uses_bundled_marker(tmp_path, monkeypatch):
    tools_root = tmp_path / "runtime-tools"
    expected = tools_root / "python-managed" / "cpython-3.12" / "python.exe"
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"python")
    (tools_root / "python-path.txt").write_text(
        "python-managed/cpython-3.12/python.exe",
        encoding="ascii",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_engines, "runtime_tools_root", lambda: tools_root)

    assert runtime_engines.runtime_python() == expected


def test_frozen_runtime_python_rejects_marker_escape(tmp_path, monkeypatch):
    tools_root = tmp_path / "runtime-tools"
    tools_root.mkdir()
    (tools_root / "python-path.txt").write_text(
        "../../backend/.venv/Scripts/python.exe",
        encoding="ascii",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_engines, "runtime_tools_root", lambda: tools_root)

    with pytest.raises(runtime_engines.RuntimeSetupError, match="outside the runtime tools"):
        runtime_engines.runtime_python()


def test_nvidia_preflight_parses_driver_without_importing_torch(monkeypatch):
    captured = {}

    def fake_run(command, **_kwargs):
        captured.update(_kwargs)
        assert command[0] == "nvidia-smi"
        assert "driver_version" in command[1]
        return SimpleNamespace(
            returncode=0,
            stdout="0, NVIDIA GeForce RTX 3060 Ti, 610.47, 8192\n",
            stderr="",
        )

    monkeypatch.setattr(runtime_engines.subprocess, "run", fake_run)
    result = runtime_engines.nvidia_preflight(force=True)

    assert result == {
        "supported": True,
        "reason": None,
        "gpus": [
            {
                "index": 0,
                "name": "NVIDIA GeForce RTX 3060 Ti",
                "driver_version": "610.47",
                "vram_mb": 8192,
            }
        ],
    }
    if sys.platform == "win32":
        assert captured["creationflags"] == runtime_engines.subprocess.CREATE_NO_WINDOW


def test_hidden_process_kwargs_suppress_windows_console():
    options = subprocess_utils.hidden_process_kwargs()

    if sys.platform == "win32":
        assert options["creationflags"] == runtime_engines.subprocess.CREATE_NO_WINDOW
        assert options["startupinfo"].wShowWindow == runtime_engines.subprocess.SW_HIDE
    else:
        assert options == {}


def test_windows_job_configuration_accepts_pointer_width_handles():
    if sys.platform != "win32":
        pytest.skip("Windows Job Objects are Windows-only")
    script = (
        "from app.subprocess_utils import configure_child_process_job;"
        "result=configure_child_process_job();"
        "print(result);"
        "raise SystemExit(0 if isinstance(result,bool) else 1)"
    )
    result = runtime_engines.subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        **subprocess_utils.hidden_process_kwargs(),
    )

    assert result.returncode == 0, result.stderr


def test_nvidia_preflight_reports_missing_driver_tool(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(runtime_engines.subprocess, "run", fake_run)
    result = runtime_engines.nvidia_preflight(force=True)

    assert result["supported"] is False
    assert result["gpus"] == []
    assert "nvidia-smi was not found" in result["reason"]


def test_engine_manifest_round_trip_is_atomic(tmp_path, monkeypatch):
    manifest_path = tmp_path / "engines-manifest.json"
    monkeypatch.setattr(runtime_state, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(runtime_state, "ENGINE_MANIFEST_FILE", manifest_path)
    manifest = {
        "schema_version": 1,
        "active_app_version": "1.7.0",
        "profiles": {"kokoro": {"status": "verified", "version": "0.9.4"}},
    }

    runtime_state.save_engine_manifest(manifest)

    assert runtime_state.load_engine_manifest() == manifest
    assert not manifest_path.with_name("engines-manifest.json.tmp").exists()


def test_runtime_status_merges_catalog_and_manifest(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.json"
    _write_catalog(catalog)
    monkeypatch.setenv("NARRATIBLE_RUNTIME_CATALOG", str(catalog))
    monkeypatch.setattr(
        runtime_engines,
        "load_engine_manifest",
        lambda: {
            "schema_version": 1,
            "active_app_version": "1.7.0",
            "profiles": {
                "kokoro": {
                    "status": "verified",
                    "version": "0.9.4",
                    "last_error": None,
                }
            },
        },
    )

    result = runtime_engines.runtime_status()

    assert result["manifest_app_version"] == "1.7.0"
    assert result["profiles"][0]["status"] == "verified"
    assert result["profiles"][0]["installed_version"] == "0.9.4"


def test_runtime_api_exposes_status_and_preflight(monkeypatch):
    expected_status = {"profiles": [{"id": "kokoro", "status": "not_installed"}]}
    expected_preflight = {"supported": False, "reason": "No NVIDIA GPU", "gpus": []}
    monkeypatch.setattr(main, "runtime_status", lambda: expected_status)
    monkeypatch.setattr(main, "nvidia_preflight", lambda: expected_preflight)

    assert asyncio.run(main.api_runtime_engines()) == expected_status
    assert asyncio.run(main.api_runtime_preflight()) == expected_preflight


def test_install_profile_syncs_frozen_lock_and_activates_atomically(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    uv_path = tmp_path / "tools" / "uv.exe"
    python_path = tmp_path / "tools" / "python.exe"
    uv_path.parent.mkdir()
    uv_path.write_bytes(b"uv")
    python_path.write_bytes(b"python")
    captured = {}
    saved = {}

    def fake_run(command, *, env=None):
        captured["command"] = command
        captured["env"] = env
        staging_path = Path(env["UV_PROJECT_ENVIRONMENT"])
        (staging_path / "Scripts").mkdir(parents=True)
        (staging_path / "Scripts" / "python.exe").write_bytes(b"python")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runtime_engines, "runtime_root", lambda: runtime_dir)
    monkeypatch.setattr(runtime_engines, "uv_executable", lambda: uv_path)
    monkeypatch.setattr(runtime_engines, "runtime_python", lambda: python_path)
    monkeypatch.setattr(runtime_engines, "_run_command", fake_run)
    monkeypatch.setattr(
        runtime_engines,
        "verify_profile_environment",
        lambda profile_id, env_path, **_kwargs: {"torch": "2.11.0+cu128", "cuda": "12.8"},
    )
    monkeypatch.setattr(
        runtime_engines,
        "load_engine_manifest",
        lambda: {
            "schema_version": 1,
            "active_app_version": "1.6.0",
            "profiles": {"kokoro": {"active_env": "C:/old/kokoro"}},
        },
    )
    monkeypatch.setattr(runtime_engines, "save_engine_manifest", lambda value: saved.update(value))

    result = runtime_engines.install_profile("kokoro")

    assert "--frozen" in captured["command"]
    assert "--no-managed-python" in captured["command"]
    assert captured["env"]["UV_PYTHON_DOWNLOADS"] == "never"
    assert captured["env"]["UV_CACHE_DIR"] == str(runtime_dir / "cache" / "uv")
    assert Path(result["active_env"]).is_dir()
    assert result["rollback_env"] == "C:/old/kokoro"
    assert result["torch_version"] == "2.11.0+cu128"
    assert result["cuda_version"] == "12.8"
    assert saved["active_app_version"] == runtime_engines.APP_VERSION


def test_install_profile_reuses_verified_matching_lock(monkeypatch):
    lock_hash = runtime_engines.load_runtime_catalog()["profiles"][0]["lock_sha256"]
    current = {
        "status": "verified",
        "lock_sha256": lock_hash,
        "active_env": "C:/managed/kokoro",
    }
    manifest = {"schema_version": 1, "active_app_version": "1.6.0", "profiles": {"kokoro": current}}
    saved = {}
    monkeypatch.setattr(runtime_engines, "load_engine_manifest", lambda: manifest)
    monkeypatch.setattr(
        runtime_engines,
        "verify_profile_environment",
        lambda *_args, **_kwargs: {"torch": "2.11.0+cu128", "cuda": "12.8"},
    )
    monkeypatch.setattr(runtime_engines, "save_engine_manifest", lambda value: saved.update(value))
    monkeypatch.setattr(
        runtime_engines,
        "_run_command",
        lambda *_args, **_kwargs: pytest.fail("Matching lock should not invoke uv sync"),
    )

    result = runtime_engines.install_profile("kokoro")

    assert result["active_env"] == "C:/managed/kokoro"
    assert result["torch_version"] == "2.11.0+cu128"
    assert saved["active_app_version"] == runtime_engines.APP_VERSION


def test_runtime_status_marks_stale_profile_for_update(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runtime_engines,
        "load_runtime_catalog",
        lambda: {
            "schema_version": 1,
            "worker_protocol_version": 1,
            "python_version": "3.12",
            "pytorch": {"backend": "cu128"},
            "profiles": [
                {
                    "id": "kokoro",
                    "label": "Kokoro",
                    "lock_file": "kokoro/uv.lock",
                    "lock_sha256": "current-lock",
                }
            ],
        },
    )
    monkeypatch.setattr(
        runtime_engines,
        "load_engine_manifest",
        lambda: {
            "schema_version": 1,
            "active_app_version": "1.7.0",
            "profiles": {
                "kokoro": {
                    "status": "verified",
                    "lock_sha256": "stale-lock",
                    "active_env": "C:/managed/kokoro",
                }
            },
        },
    )

    assert runtime_engines.runtime_status()["profiles"][0]["status"] == "needs_update"


def test_update_installed_profiles_skips_profiles_user_never_installed(monkeypatch):
    monkeypatch.setattr(
        runtime_engines,
        "load_engine_manifest",
        lambda: {
            "schema_version": 1,
            "profiles": {"kokoro": {"status": "verified"}},
        },
    )
    calls = []
    monkeypatch.setattr(
        runtime_engines,
        "install_profile",
        lambda profile_id, progress: calls.append(profile_id) or {"status": "verified"},
    )

    result = runtime_engines.update_installed_profiles()

    assert calls == ["kokoro"]
    assert result == {"kokoro": {"status": "verified"}}


def test_profile_verification_rejects_cpu_only_torch(tmp_path, monkeypatch):
    env_path = tmp_path / "kokoro"
    python_path = env_path / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_bytes(b"python")
    monkeypatch.setattr(
        runtime_engines,
        "_run_command",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=3, stdout="", stderr=""),
    )

    with pytest.raises(runtime_engines.RuntimeSetupError, match="CPU-only PyTorch"):
        runtime_engines.verify_profile_environment("kokoro", env_path)


def test_kokoro_verification_requires_cuda_and_prefetches_model(tmp_path, monkeypatch):
    env_path = tmp_path / "kokoro"
    python_path = env_path / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_bytes(b"python")
    captured = {}

    def fake_run(command, **_kwargs):
        captured["script"] = command[-1]
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"torch": "2.11.0+cu128", "cuda": "12.8"}) + "\n",
            stderr="",
        )

    monkeypatch.setattr(runtime_engines, "_run_command", fake_run)

    result = runtime_engines.verify_profile_environment(
        "kokoro",
        env_path,
        require_device=True,
        prefetch_model=True,
        cuda_index=1,
    )

    assert result["cuda"] == "12.8"
    assert "torch.cuda.is_available()" in captured["script"]
    assert "device='cuda:1'" in captured["script"]
    assert "KPipeline" in captured["script"]


def test_runtime_install_api_runs_task_to_completion(monkeypatch):
    main._tasks.clear()
    monkeypatch.setattr(
        main,
        "runtime_status",
        lambda: {"profiles": [{"id": "kokoro", "label": "Kokoro", "installable": True, "status": "not_installed"}]},
    )
    monkeypatch.setattr(
        main,
        "install_profile",
        lambda profile_id, progress: {
            "status": "verified",
            "active_env": f"C:/runtime/{profile_id}",
        },
    )
    background_tasks = BackgroundTasks()

    response = asyncio.run(main.api_install_runtime_engine("kokoro", background_tasks))
    asyncio.run(background_tasks())

    task = main._tasks[response["task_id"]]
    assert task["status"] == "done"
    assert task["progress"] == 100
    assert task["runtime"]["active_env"] == "C:/runtime/kokoro"


def test_runtime_api_rejects_unavailable_profile(monkeypatch):
    monkeypatch.setattr(
        main,
        "runtime_status",
        lambda: {"profiles": [{"id": "f5-tts", "label": "F5-TTS", "installable": False, "status": "not_available"}]},
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main.api_install_runtime_engine("f5-tts", BackgroundTasks()))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "F5-TTS is not installable yet."


def test_remove_profile_rejects_manifest_path_outside_runtime_root(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_engines, "runtime_root", lambda: tmp_path / "managed")
    monkeypatch.setattr(
        runtime_engines,
        "load_engine_manifest",
        lambda: {
            "schema_version": 1,
            "profiles": {"kokoro": {"active_env": str(tmp_path / "unmanaged")}},
        },
    )

    with pytest.raises(runtime_engines.RuntimeSetupError, match="outside the managed root"):
        runtime_engines.remove_profile("kokoro")


def test_managed_kokoro_routes_synthesis_to_runtime_worker(tmp_path, monkeypatch):
    captured = {}

    async def fake_synthesize_kokoro(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(runtime_engines, "installed_profile_state", lambda _profile: {"status": "verified"})
    monkeypatch.setattr(runtime_workers, "synthesize_kokoro", fake_synthesize_kokoro)
    monkeypatch.setattr("app.config.get_device_string", lambda: "cuda:0")

    asyncio.run(
        tts.synthesize_speech(
            "First sentence. Second sentence.",
            tmp_path / "chapter.wav",
            engine="kokoro",
            voice="af_heart",
            speed=1.1,
        )
    )

    assert captured["device"] == "cuda:0"
    assert captured["voice"] == "af_heart"
    assert captured["segments"][0]["text"] == "First sentence."
    assert captured["output_path"] == tmp_path / "chapter.wav"


@pytest.mark.parametrize("engine", ["f5-tts", "chatterbox"])
def test_managed_clone_engine_routes_to_runtime_worker(engine, tmp_path, monkeypatch):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"audio")
    captured = {}

    async def fake_synthesize_clone(profile_id, **kwargs):
        captured["profile_id"] = profile_id
        captured.update(kwargs)

    monkeypatch.setattr(
        runtime_engines,
        "installed_profile_state",
        lambda profile_id: {"status": "verified"} if profile_id == engine else None,
    )
    monkeypatch.setattr(runtime_workers, "synthesize_clone_engine", fake_synthesize_clone)
    monkeypatch.setattr("app.config.get_device_string", lambda: "cuda:0")

    asyncio.run(
        tts.synthesize_speech(
            "Clone this sentence.",
            tmp_path / "clone.wav",
            engine=engine,
            voice_sample_path=reference,
            voice_reference_text="Reference transcript.",
        )
    )

    assert captured["profile_id"] == engine
    assert captured["reference_path"] == reference
    assert captured["device"] == "cuda:0"


def test_runtime_worker_reuses_process_between_requests(tmp_path, monkeypatch):
    worker_script = tmp_path / "kokoro_worker.py"
    worker_script.write_text("# worker", encoding="utf-8")
    starts = []

    class FakeStdout:
        def __init__(self):
            self.lines = []

        def __iter__(self):
            return iter(())

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

        def close(self):
            pass

    class FakeStdin:
        def __init__(self, process):
            self.process = process

        def write(self, value):
            request = json.loads(value)
            if request.get("action") == "shutdown":
                self.process.returncode = 0
                return
            self.process.stdout.lines.append(
                json.dumps({"request_id": request["request_id"], "type": "result"}) + "\n"
            )

        def flush(self):
            pass

        def close(self):
            pass

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.stdout = FakeStdout()
            self.stdin = FakeStdin(self)
            self.stderr = FakeStdout()

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

    def fake_popen(*_args, **_kwargs):
        if sys.platform == "win32":
            assert _kwargs["creationflags"] == runtime_workers.subprocess.CREATE_NO_WINDOW
        process = FakeProcess()
        starts.append(process)
        return process

    monkeypatch.setattr(runtime_workers, "installed_profile_state", lambda _profile: {"python_executable": "python.exe"})
    monkeypatch.setattr(runtime_workers, "_worker_script", lambda _profile: worker_script)
    monkeypatch.setattr(runtime_workers.subprocess, "Popen", fake_popen)
    worker = runtime_workers.RuntimeWorker("kokoro")

    worker.request("synthesize", {"text": "one"})
    worker.request("synthesize", {"text": "two"})
    worker.stop()

    assert len(starts) == 1