import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main  # noqa: E402
from app.config import AppConfig  # noqa: E402


def test_cloud_llm_provider_uses_selected_configured_key():
    cfg = AppConfig(
        llm_provider="openai",
        gemini_api_key="gemini-key",
        openai_api_key="openai-key",
    )

    assert main._require_cloud_llm_provider(cfg) == "openai"


def test_cloud_llm_provider_falls_back_to_configured_cloud_key():
    cfg = AppConfig(
        llm_provider="local",
        gemini_api_key="gemini-key",
        openai_api_key="",
    )

    assert main._require_cloud_llm_provider(cfg) == "gemini"


def test_cloud_llm_provider_rejects_missing_cloud_keys():
    cfg = AppConfig(llm_provider="gemini", gemini_api_key="", openai_api_key="")

    with pytest.raises(RuntimeError, match="Cloud LLM cleanup requires"):
        main._require_cloud_llm_provider(cfg)


def test_parse_pdf_rejects_cloud_llm_without_configured_key(monkeypatch):
    monkeypatch.setattr(main, "get_project", lambda project_id: object())
    monkeypatch.setattr(main, "load_config", lambda: AppConfig(gemini_api_key="", openai_api_key=""))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            main.parse_pdf(
                "project-1",
                BackgroundTasks(),
                cleaner="llm",
            )
        )

    assert exc_info.value.status_code == 400
    assert "Cloud LLM cleanup requires" in exc_info.value.detail
