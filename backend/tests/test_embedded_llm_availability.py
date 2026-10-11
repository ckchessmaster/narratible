"""Embedded LLM requests use the managed runtime profile or fail fast when unavailable."""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import cleaner, main, runtime_engines, runtime_workers, tts  # noqa: E402


def _no_cloud_config(llm_provider: str = "gemini"):
    return SimpleNamespace(
        llm_provider=llm_provider,
        gemini_api_key="",
        openai_api_key="",
        embedded_llm_model="google/gemma-4-E2B-it",
        huggingface_token="",
        selected_gpu_index=0,
    )


def test_embedded_llm_available_false_when_not_installed_and_torch_missing(monkeypatch):
    monkeypatch.setattr(runtime_engines, "installed_profile_state", lambda _: None)
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *args, **kwargs: None if name == "torch" else real_find_spec(name, *args, **kwargs),
    )
    assert runtime_engines.embedded_llm_available() is False


def test_embedded_llm_available_true_when_managed_profile_installed(monkeypatch):
    monkeypatch.setattr(runtime_engines, "installed_profile_state", lambda profile_id: {"status": "verified"} if profile_id == "embedded-llm" else None)
    assert runtime_engines.embedded_llm_available() is True


def test_runtime_status_reports_embedded_llm_availability(monkeypatch):
    monkeypatch.setattr(runtime_engines, "embedded_llm_available", lambda: False)
    monkeypatch.setattr(runtime_engines, "load_engine_manifest", lambda: {"profiles": {}})
    assert runtime_engines.runtime_status()["embedded_llm_available"] is False


@pytest.mark.parametrize("provider", ["embedded", None])
def test_modernization_provider_rejects_unavailable_embedded(monkeypatch, provider):
    monkeypatch.setattr(main, "embedded_llm_available", lambda: False)
    monkeypatch.setattr(main, "load_config", lambda: _no_cloud_config())
    with pytest.raises(RuntimeError, match=r"requires the 'Local LLM Runtime \(CUDA\)' profile"):
        main._resolve_modernization_provider(provider)


def test_modernization_provider_rejects_local_setting_when_unavailable(monkeypatch):
    monkeypatch.setattr(main, "embedded_llm_available", lambda: False)
    monkeypatch.setattr(main, "load_config", lambda: _no_cloud_config("local"))
    with pytest.raises(RuntimeError, match=r"requires the 'Local LLM Runtime \(CUDA\)' profile"):
        main._resolve_modernization_provider(None)


def test_modernization_provider_allows_embedded_when_available(monkeypatch):
    monkeypatch.setattr(main, "embedded_llm_available", lambda: True)
    monkeypatch.setattr(main, "load_config", lambda: _no_cloud_config())
    assert main._resolve_modernization_provider("embedded") == "embedded"


def test_clean_text_rejects_embedded_before_queuing(monkeypatch):
    monkeypatch.setattr(main, "embedded_llm_available", lambda: False)
    monkeypatch.setattr(main, "get_project", lambda project_id: SimpleNamespace(title="Book"))
    queued = []
    monkeypatch.setattr(main, "_set_task", lambda *args, **kwargs: queued.append(args))

    req = main.CleanTextRequest(chapter_index=0, provider="embedded", background=True)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.api_clean_text("project-1", req, BackgroundTasks()))

    assert exc.value.status_code == 400
    assert "requires the 'Local LLM Runtime (CUDA)' profile" in exc.value.detail
    assert queued == []


def test_parse_rejects_embedded_cleaner_when_unavailable(monkeypatch):
    monkeypatch.setattr(main, "embedded_llm_available", lambda: False)
    monkeypatch.setattr(main, "get_project", lambda project_id: SimpleNamespace(title="Book"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.parse_pdf("project-1", BackgroundTasks(), cleaner="embedded", modules=[]))

    assert exc.value.status_code == 400


def test_call_embedded_llm_dispatches_to_runtime_worker_when_installed(monkeypatch):
    monkeypatch.setattr(runtime_engines, "installed_profile_state", lambda profile_id: {"status": "verified"} if profile_id == "embedded-llm" else None)
    monkeypatch.setattr(tts, "unload_tts", lambda: None)
    dispatched = {}

    def mock_generate(**kwargs):
        dispatched.update(kwargs)
        return "Cleaned text output"

    monkeypatch.setattr(runtime_workers, "generate_embedded_llm", mock_generate)

    cfg = _no_cloud_config()
    messages = [{"role": "user", "content": "hello"}]
    result = cleaner.call_embedded_llm(messages, cfg=cfg, max_new_tokens=500)

    assert result == "Cleaned text output"
    assert dispatched["model_name"] == "google/gemma-4-E2B-it"
    assert dispatched["max_new_tokens"] == 500
    assert dispatched["messages"] == messages
