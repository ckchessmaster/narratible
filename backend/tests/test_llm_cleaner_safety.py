"""Safety tests for LLM-assisted cleanup."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import cleaner  # noqa: E402
from app.cleaner import (  # noqa: E402
    CleanedTextResponse,
    ReviewedChapterEntry,
    _apply_chapter_review,
    _assess_cleaning_risk,
    _call_gemini_with_retries,
    _embedded_generation_sampling_kwargs,
    _llm_output_integrity_issues,
    _parse_llm_clean_output,
    _safe_llm_chunk_text,
    _split_text_for_llm,
    get_cleaning_profile,
    llm_clean_text,
)


class _FakeOpenAI:
    response = CleanedTextResponse(main_text="", notes_text="")

    def __init__(self, api_key):
        self.beta = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(parse=self._parse)
            )
        )

    def _parse(self, **kwargs):
        message = SimpleNamespace(parsed=self.response)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _patch_openai(monkeypatch, response: CleanedTextResponse):
    _FakeOpenAI.response = response
    monkeypatch.setattr(cleaner, "OpenAI", _FakeOpenAI)

    def fake_load_config():
        return SimpleNamespace(
            openai_api_key="test-key",
            llm_temperature=0.1,
            cloud_llm_chunk_size=16000,
        )

    import app.config as config

    monkeypatch.setattr(config, "load_config", fake_load_config)


def test_llm_integrity_rejects_placeholder_summary_output():
    source = " ".join(f"word{i}" for i in range(120))
    issues = _llm_output_integrity_issues(source, "word0 word1 ...(rest of text omitted)")
    assert "placeholder or summary language" in issues
    assert any(issue.startswith("word count shrank") for issue in issues)


def test_balanced_profile_allows_more_repair_than_safe_profile():
    source = " ".join(f"word{i}" for i in range(100))
    candidate = " ".join(f"word{i}" for i in range(55))

    safe_issues = _llm_output_integrity_issues(source, candidate, profile_id="safe")
    balanced_issues = _llm_output_integrity_issues(source, candidate, profile_id="balanced")

    assert get_cleaning_profile("balanced").label == "Balanced"
    assert safe_issues
    assert balanced_issues == []


def test_cleaning_risk_recommends_low_risk_acceptance():
    risk = _assess_cleaning_risk(
        {
            "word_count_ratio": 1.02,
            "anchor_required": 2,
            "anchor_matches": 2,
        },
        [],
        "accepted",
    )
    assert risk["risk_level"] == "low"
    assert risk["recommended_action"] == "accept"


def test_cleaning_risk_marks_fallback_high_risk():
    risk = _assess_cleaning_risk(
        {
            "word_count_ratio": 0.4,
            "anchor_required": 2,
            "anchor_matches": 0,
        },
        ["missing source anchor phrases"],
        "fallback",
    )
    assert risk["risk_level"] == "high"
    assert risk["recommended_action"] == "review"


def test_embedded_generation_uses_greedy_decoding_for_zero_temperature():
    assert _embedded_generation_sampling_kwargs(0.0) == {"do_sample": False}


def test_embedded_generation_samples_for_positive_temperature():
    assert _embedded_generation_sampling_kwargs(0.1) == {
        "temperature": 0.1,
        "do_sample": True,
    }


def test_safe_llm_chunk_falls_back_to_source_when_anchors_are_missing():
    source = "Alpha beta gamma delta epsilon. " * 30
    main_text, notes_text, issues = _safe_llm_chunk_text(
        source,
        "A completely different cleaned passage with none of the original anchors.",
        "invented note",
    )
    assert main_text == source.strip()
    assert notes_text == ""
    assert "missing source anchor phrases" in issues


def test_llm_clean_text_uses_heuristic_chunk_when_openai_response_is_truncated(monkeypatch):
    source = (
        "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu. " * 12
        + "Omega closes the passage faithfully."
    )
    _patch_openai(
        monkeypatch,
        CleanedTextResponse(
            main_text="Alpha beta gamma. ...(rest of text omitted)",
            notes_text="",
        ),
    )

    assert llm_clean_text(source, provider="openai") == source.strip()


def test_llm_clean_text_can_return_chunk_evaluation(monkeypatch):
    source = (
        "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu. " * 12
        + "Omega closes the passage faithfully."
    )
    _patch_openai(
        monkeypatch,
        CleanedTextResponse(
            main_text="Alpha beta gamma. ...(rest of text omitted)",
            notes_text="",
        ),
    )

    cleaned_text, evaluation = llm_clean_text(
        source,
        provider="openai",
        return_evaluation=True,
    )

    assert cleaned_text == source.strip()
    assert evaluation["profile"] == "safe"
    assert evaluation["fallback_count"] == 1
    assert evaluation["chunks"][0]["status"] == "fallback"


def test_llm_clean_text_accepts_structured_openai_output_with_source_anchors(monkeypatch):
    source = (
        "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu. " * 12
        + "Omega closes the passage faithfully."
    )
    cleaned = source.replace("Alpha", "# Alpha", 1)
    _patch_openai(monkeypatch, CleanedTextResponse(main_text=cleaned, notes_text=""))

    assert llm_clean_text(source, provider="openai") == cleaned.strip()


def test_gemini_retry_helper_retries_transient_unavailable(monkeypatch):
    attempts = []
    progress_messages = []

    class TransientGeminiError(Exception):
        status_code = 503

    def flaky_call():
        attempts.append(1)
        if len(attempts) == 1:
            raise TransientGeminiError("503 UNAVAILABLE: high demand")
        return "ok"

    monkeypatch.setattr(cleaner.time, "sleep", lambda seconds: None)

    result = _call_gemini_with_retries(
        flaky_call,
        lambda message, progress: progress_messages.append((message, progress)),
        42,
    )

    assert result == "ok"
    assert len(attempts) == 2
    assert progress_messages == [
        ("Gemini temporarily unavailable, retrying in 10s... (attempt 1/5)", 42)
    ]


def test_parse_llm_clean_output_reads_json_fallback():
    main_text, notes_text = _parse_llm_clean_output(
        '{"main_text": "Clean body", "notes_text": "Footnote body"}'
    )
    assert main_text == "Clean body"
    assert notes_text == "Footnote body"


def test_split_text_for_llm_respects_paragraph_boundaries_when_possible():
    text = "First paragraph stays together.\n\nSecond paragraph also stays whole."
    assert _split_text_for_llm(text, 1000) == [text]


def test_split_text_for_llm_splits_oversized_paragraphs():
    text = " ".join(f"word{i}" for i in range(350))
    chunks = _split_text_for_llm(text, 1000)
    assert len(chunks) > 1
    assert all(len(chunk) <= 1000 for chunk in chunks)


def test_chapter_review_rejects_unrelated_title_without_toc_support():
    chapters = [{"title": "Chapter One", "raw_text": "Body text."}]
    reviewed = [
        ReviewedChapterEntry(
            title="A Sponsored Message From The Model",
            section_type="chapter",
            note=None,
        )
    ]

    result = _apply_chapter_review(chapters, reviewed)
    assert result is not None
    assert result[0]["title"] == "Chapter One"


def test_chapter_review_accepts_title_when_supported_by_toc():
    chapters = [{"title": "Delight?", "raw_text": "Body text."}]
    reviewed = [
        ReviewedChapterEntry(
            title="When I Don't Desire God: How to Fight for Joy",
            section_type="chapter",
            note=None,
        )
    ]

    result = _apply_chapter_review(
        chapters,
        reviewed,
        contents_reference="When I Don't Desire God: How to Fight for Joy 17",
    )
    assert result is not None
    assert result[0]["title"] == "When I Don't Desire God: How to Fight for Joy"
