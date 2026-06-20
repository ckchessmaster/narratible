"""Tests for LLM-assisted text modernization."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.parsing_modules import modernizer  # noqa: E402
from app.parsing_modules.modernizer import (  # noqa: E402
    ModernizedTextResponse,
    _evaluate_modernization_chunk,
    _modernization_integrity_issues,
    get_modernization_profile,
    list_modernization_profiles,
    llm_modernize_text,
)


class _FakeOpenAI:
    responses: list[ModernizedTextResponse] = []

    def __init__(self, api_key):
        self.beta = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(parse=self._parse)
            )
        )

    def _parse(self, **kwargs):
        response = self.responses.pop(0)
        message = SimpleNamespace(parsed=response)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_modernization_profile_labels_are_clear():
    profiles = list_modernization_profiles()

    assert [profile["label"] for profile in profiles] == [
        "Light Update",
        "Standard Modern",
        "Plain Language",
    ]
    assert "changes the least" in profiles[0]["warning"].lower()
    assert "recommended default" in profiles[1]["warning"].lower()


def test_legacy_profile_aliases_still_resolve():
    assert get_modernization_profile("faithful").id == "light_update"
    assert get_modernization_profile("balanced").id == "standard_modern"
    assert get_modernization_profile("plain").id == "plain_language"


def test_modernization_integrity_rejects_summary_and_missing_protected_tokens():
    source = "In 1842, Eleanor traveled to London. " * 12
    candidate = "Here is a summarized modernized version: she traveled somewhere."

    issues = _modernization_integrity_issues(source, candidate)

    assert "meta or summary language" in issues
    assert any(issue.startswith("missing protected tokens") for issue in issues)


def test_modernization_integrity_flags_missing_middle_paragraph():
    source = (
        "The apostle begins with the condition of the nations, showing that conscience and creation leave people without excuse.\n\n"
        "He then turns to the covenant people, explaining that possession of the law cannot rescue those who break it.\n\n"
        "Finally, he gathers every mouth under judgment so that grace may be seen as entirely free in Christ."
    )
    candidate = (
        "The apostle starts with the nations, showing that conscience and creation leave people without excuse.\n\n"
        "Finally, he brings every mouth under judgment so grace can be seen as entirely free in Christ."
    )

    issues = _modernization_integrity_issues(source, candidate)

    assert any(issue.startswith("possible paragraph omission") for issue in issues)


def test_modernization_redo_similarity_guard_flags_near_duplicate_candidate():
    evaluation = _evaluate_modernization_chunk(
        0,
        "The old sentence remains here with careful wording.",
        "The old sentence remains here with careful wording.",
        "openai",
        "standard_modern",
        previous_candidates=["The old sentence remains here with careful wording."],
    )

    assert evaluation.similarity_to_previous == 1.0
    assert "very similar to previous candidate" in evaluation.integrity_issues
    assert evaluation.variants[0]["similarity_to_previous"] == 1.0


def test_llm_modernize_text_uses_chunked_processing(monkeypatch):
    monkeypatch.setattr(modernizer, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(
        modernizer,
        "load_config",
        lambda: SimpleNamespace(openai_api_key="test-key", cloud_llm_chunk_size=16000),
    )
    monkeypatch.setattr(
        modernizer,
        "_split_text_for_llm",
        lambda text, chunk_size: ["Old chunk one.", "Old chunk two."],
    )
    _FakeOpenAI.responses = [
        ModernizedTextResponse(modernized_text="Modern chunk one."),
        ModernizedTextResponse(modernized_text="Modern chunk two."),
    ]

    modernized_text, evaluation = llm_modernize_text(
        "Old chunk one. Old chunk two.",
        provider="openai",
        modernization_profile="standard_modern",
    )

    assert modernized_text == "Modern chunk one.\n\nModern chunk two."
    assert evaluation["profile"] == "standard_modern"
    assert evaluation["chunk_count"] == 2
    assert [chunk["source_text"] for chunk in evaluation["chunks"]] == [
        "Old chunk one.",
        "Old chunk two.",
    ]