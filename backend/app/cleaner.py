import re
import json
import time
import logging
from difflib import SequenceMatcher
from typing import Callable, Literal, Any
from openai import OpenAI
from pydantic import BaseModel
from .config import get_device_string
from .page_artifacts import remove_running_headers

class CleanedTextResponse(BaseModel):
    main_text: str
    notes_text: str

CleaningProfileId = Literal["safe", "balanced", "aggressive"]

class CleaningProfile(BaseModel):
    id: CleaningProfileId
    label: str
    description: str
    temperature: float
    cloud_chunk_size: int
    local_chunk_size: int
    min_word_ratio: float
    max_word_ratio: float
    required_anchor_matches_long: int
    prompt_guidance: str

class ChunkCleaningEvaluation(BaseModel):
    chunk_id: int
    provider: str
    profile: CleaningProfileId
    status: Literal["accepted", "fallback"]
    source_text: str
    candidate_text: str
    accepted_text: str
    notes_text: str
    integrity_issues: list[str]
    metrics: dict[str, Any]
    risk_level: Literal["low", "medium", "high"]
    risk_reasons: list[str]
    recommended_action: str

class TextCleaningEvaluation(BaseModel):
    provider: str
    profile: CleaningProfileId
    chunk_count: int
    accepted_count: int
    fallback_count: int
    chunks: list[ChunkCleaningEvaluation]

SectionType = Literal["front_matter", "chapter", "back_matter", "continuation"]

class ReviewedChapterEntry(BaseModel):
    title: str
    section_type: SectionType
    note: str | None = None

class ChapterReviewResponse(BaseModel):
    chapters: list[ReviewedChapterEntry]

logger = logging.getLogger(__name__)

MIN_LLM_CHUNK_SIZE = 1000
DEFAULT_CLOUD_LLM_CHUNK_SIZE = 16000
MAX_CLOUD_LLM_CHUNK_SIZE = 16000
DEFAULT_LOCAL_LLM_CHUNK_SIZE = 8000
MAX_LOCAL_LLM_CHUNK_SIZE = 12000
GEMINI_MAX_RETRIES = 5
GEMINI_RETRY_BASE_SECONDS = 10
GEMINI_RETRY_MAX_SECONDS = 90
GEMINI_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

CLEANING_PROFILES: dict[str, CleaningProfile] = {
    "safe": CleaningProfile(
        id="safe",
        label="Conservative",
        description="Preserves heuristic text unless the LLM output clearly keeps the source intact.",
        temperature=0.0,
        cloud_chunk_size=12000,
        local_chunk_size=6000,
        min_word_ratio=0.58,
        max_word_ratio=1.8,
        required_anchor_matches_long=2,
        prompt_guidance="Be conservative. Preserve wording and structure. Only fix obvious PDF/OCR artifacts.",
    ),
    "balanced": CleaningProfile(
        id="balanced",
        label="Balanced",
        description="Allows normal OCR and layout repair while still blocking truncation and summaries.",
        temperature=0.1,
        cloud_chunk_size=16000,
        local_chunk_size=8000,
        min_word_ratio=0.50,
        max_word_ratio=2.1,
        required_anchor_matches_long=1,
        prompt_guidance="Repair clear OCR and layout damage, but do not rewrite the author's prose.",
    ),
    "aggressive": CleaningProfile(
        id="aggressive",
        label="Restorative",
        description="Makes stronger OCR repairs; best for reviewed retries of damaged chunks.",
        temperature=0.2,
        cloud_chunk_size=16000,
        local_chunk_size=10000,
        min_word_ratio=0.42,
        max_word_ratio=2.5,
        required_anchor_matches_long=1,
        prompt_guidance="Make stronger repairs to damaged OCR while preserving meaning, order, and all recoverable text.",
    ),
}


def get_cleaning_profile(profile_id: str | None = None) -> CleaningProfile:
    return CLEANING_PROFILES.get((profile_id or "safe").lower(), CLEANING_PROFILES["safe"])


def list_cleaning_profiles() -> list[dict]:
    return [profile.model_dump() for profile in CLEANING_PROFILES.values()]


def _gemini_error_status_code(error: Exception) -> int | None:
    for source in (error, getattr(error, "response", None)):
        if source is None:
            continue
        status_code = getattr(source, "status_code", None)
        if status_code is None:
            continue
        try:
            return int(status_code)
        except (TypeError, ValueError):
            return None
    return None


def _is_gemini_free_tier_quota_error(error: Exception) -> bool:
    err_str = str(error).lower()
    return "free_tier" in err_str or "limit: 0" in err_str


def _is_transient_gemini_error(error: Exception) -> bool:
    status_code = _gemini_error_status_code(error)
    if status_code in GEMINI_TRANSIENT_STATUS_CODES:
        return True
    err_str = str(error).upper()
    return any(
        token in err_str
        for token in (
            "RESOURCE_EXHAUSTED",
            "UNAVAILABLE",
            "INTERNAL",
            "DEADLINE_EXCEEDED",
            "500",
            "502",
            "503",
            "504",
            "429",
        )
    )


def _gemini_retry_reason(error: Exception) -> str:
    status_code = _gemini_error_status_code(error)
    err_str = str(error).upper()
    if status_code == 429 or "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
        return "rate limited"
    if status_code == 503 or "UNAVAILABLE" in err_str or "503" in err_str:
        return "temporarily unavailable"
    return "temporarily failed"


def _sleep_with_cancel(seconds: int, cancel_check: Callable[[], bool] | None = None):
    for _ in range(seconds):
        if cancel_check and cancel_check():
            raise InterruptedError("User cancelled.")
        time.sleep(1)


def _call_gemini_with_retries(
    call: Callable[[], Any],
    report: Callable[[str, int], None],
    progress: int,
    *,
    cancel_check: Callable[[], bool] | None = None,
):
    last_error: Exception | None = None
    for attempt in range(GEMINI_MAX_RETRIES):
        try:
            return call()
        except Exception as api_err:
            if _is_gemini_free_tier_quota_error(api_err):
                raise RuntimeError(
                    "Gemini free-tier quota exhausted (limit is 0). "
                    "Enable billing on your Google AI account or switch to a paid tier: "
                    "https://ai.google.dev/gemini-api/docs/rate-limits"
                ) from api_err
            if not _is_transient_gemini_error(api_err):
                raise
            last_error = api_err
            if attempt >= GEMINI_MAX_RETRIES - 1:
                break
            wait = min(GEMINI_RETRY_MAX_SECONDS, (2 ** attempt) * GEMINI_RETRY_BASE_SECONDS)
            reason = _gemini_retry_reason(api_err)
            logger.warning(
                "Gemini request %s; retrying in %ss (attempt %s/%s).",
                reason,
                wait,
                attempt + 1,
                GEMINI_MAX_RETRIES,
            )
            report(
                f"Gemini {reason}, retrying in {wait}s... (attempt {attempt + 1}/{GEMINI_MAX_RETRIES})",
                progress,
            )
            _sleep_with_cancel(wait, cancel_check)
    raise RuntimeError(
        f"Gemini request failed after {GEMINI_MAX_RETRIES} attempts: {last_error}"
    ) from last_error


def _normalize_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _normalize_compact(text: str) -> str:
    return "".join(_normalize_words(text))


def _title_from_review(
    original_title: str,
    reviewed_title: str,
    contents_reference: str | None = None,
) -> str:
    original = (original_title or "").strip()
    reviewed = (reviewed_title or "").strip()
    if not reviewed:
        return original

    original_compact = _normalize_compact(original)
    reviewed_compact = _normalize_compact(reviewed)
    if not original_compact:
        return reviewed

    if original_compact == reviewed_compact:
        return reviewed

    if contents_reference:
        reference_compact = _normalize_compact(contents_reference)
        if reviewed_compact and reviewed_compact in reference_compact:
            return reviewed

    similarity = SequenceMatcher(None, original_compact, reviewed_compact).ratio()
    if similarity >= 0.72:
        return reviewed

    original_words = set(_normalize_words(original))
    reviewed_words = set(_normalize_words(reviewed))
    if original_words and original_words.issubset(reviewed_words) and len(reviewed_words) <= len(original_words) + 4:
        return reviewed

    logger.warning(
        "Rejecting low-confidence LLM chapter title change: %r -> %r",
        original,
        reviewed,
    )
    return original


def _split_oversized_paragraph(paragraph: str, chunk_size_chars: int) -> list[str]:
    pieces: list[str] = []
    current = ""

    for segment in re.split(r"(?<=[.!?;:])\s+", paragraph):
        if len(segment) > chunk_size_chars:
            words = segment.split()
            for word in words:
                if len(current) + len(word) + 1 > chunk_size_chars and current:
                    pieces.append(current.strip())
                    current = word
                else:
                    current = f"{current} {word}" if current else word
            continue

        if len(current) + len(segment) + 1 > chunk_size_chars and current:
            pieces.append(current.strip())
            current = segment
        else:
            current = f"{current} {segment}" if current else segment

    if current.strip():
        pieces.append(current.strip())

    return pieces


def _split_text_for_llm(text: str, chunk_size_chars: int) -> list[str]:
    chunk_size_chars = max(MIN_LLM_CHUNK_SIZE, chunk_size_chars)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush_current():
        nonlocal current, current_len
        if current:
            chunks.append("\n\n".join(current).strip())
            current = []
            current_len = 0

    for paragraph in paragraphs:
        paragraph_pieces = (
            [paragraph]
            if len(paragraph) <= chunk_size_chars
            else _split_oversized_paragraph(paragraph, chunk_size_chars)
        )
        for piece in paragraph_pieces:
            separator_len = 2 if current else 0
            if current and current_len + separator_len + len(piece) > chunk_size_chars:
                flush_current()
            current.append(piece)
            current_len += (2 if current_len else 0) + len(piece)

    flush_current()
    return chunks or ([text.strip()] if text.strip() else [])


def _has_llm_placeholder(text: str) -> bool:
    return bool(re.search(
        r"(\.\.\.\s*\(?\s*(rest|remainder|remaining)|\[\s*(rest|omitted|truncated|continued)|"
        r"(text|content)\s+(has\s+been\s+)?(omitted|truncated|summarized)|"
        r"i\s+(can'?t|cannot)\s+(continue|provide)|here\s+is\s+(a\s+)?(summary|cleaned))",
        text,
        re.IGNORECASE,
    ))


def _anchor_phrases(words: list[str], width: int = 5) -> list[str]:
    if len(words) < width:
        return [" ".join(words)] if words else []
    starts = [0, max(0, (len(words) - width) // 2), len(words) - width]
    anchors = []
    for start in starts:
        phrase = " ".join(words[start:start + width])
        if phrase and phrase not in anchors:
            anchors.append(phrase)
    return anchors


def _llm_output_metrics(source_text: str, main_text: str, notes_text: str = "", profile_id: str | None = None) -> dict[str, Any]:
    profile = get_cleaning_profile(profile_id)
    source_words = _normalize_words(source_text)
    output_text = f"{main_text}\n\n{notes_text}".strip()
    output_words = _normalize_words(output_text)
    anchors = _anchor_phrases(source_words) if len(source_words) >= 30 else []
    output_word_text = " ".join(output_words)
    anchor_matches = sum(1 for anchor in anchors if anchor in output_word_text)
    anchor_required = profile.required_anchor_matches_long if len(anchors) >= 3 and len(source_words) >= 80 else (1 if anchors else 0)
    return {
        "source_word_count": len(source_words),
        "output_word_count": len(output_words),
        "word_count_ratio": len(output_words) / max(1, len(source_words)) if source_words else 1.0,
        "anchor_count": len(anchors),
        "anchor_matches": anchor_matches,
        "anchor_required": anchor_required,
    }


def _llm_output_integrity_issues(source_text: str, main_text: str, notes_text: str = "", profile_id: str | None = None) -> list[str]:
    profile = get_cleaning_profile(profile_id)
    metrics = _llm_output_metrics(source_text, main_text, notes_text, profile.id)
    source_words = _normalize_words(source_text)
    output_text = f"{main_text}\n\n{notes_text}".strip()
    output_words = _normalize_words(output_text)
    issues: list[str] = []

    if source_words and not output_words:
        issues.append("empty output")
        return issues

    if _has_llm_placeholder(output_text):
        issues.append("placeholder or summary language")

    if len(source_words) >= 80:
        ratio = metrics["word_count_ratio"]
        if ratio < profile.min_word_ratio:
            issues.append(f"word count shrank to {ratio:.0%}")
        elif ratio > profile.max_word_ratio:
            issues.append(f"word count expanded to {ratio:.0%}")

    if metrics["anchor_required"]:
        if metrics["anchor_matches"] < metrics["anchor_required"]:
            issues.append("missing source anchor phrases")

    return issues


def _looks_like_title_or_header_line(line: str, known_titles: list[str] | None = None) -> bool:
    normalized_line = re.sub(r"\s+", " ", line.strip())
    if not normalized_line or len(normalized_line) > 120:
        return False
    if known_titles:
        normalized_known_titles = {
            re.sub(r"\s+", " ", title.strip()).lower()
            for title in known_titles
            if title and len(title.strip()) >= 8
        }
        if normalized_line.lower() in normalized_known_titles:
            return True

    words = re.findall(r"[A-Za-z][A-Za-z'-]*", normalized_line)
    if len(words) < 5 or len(words) > 16:
        return False
    if re.search(r"[.!?,;:]$", normalized_line):
        return False

    small_words = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "is", "nor", "of", "on", "or", "the", "to", "with"}
    titleish_words = 0
    for word in words:
        if word.lower() in small_words or word[:1].isupper():
            titleish_words += 1
    return titleish_words / len(words) >= 0.82


def _line_looks_unfinished(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.search(r"[.!?\])'\"]$", stripped):
        return False
    return bool(re.search(
        r"\b(?:a|an|and|as|at|because|by|for|from|in|into|is|of|or|that|the|to|with|without)$",
        stripped,
        re.IGNORECASE,
    )) or stripped[:1].islower() or stripped[-1:].islower()


def _line_continues_sentence(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(re.match(
        r"(?:a|an|and|as|because|but|for|from|in|is|it|of|or|that|the|this|those|to|we|which|who|with|you)\b",
        stripped,
        re.IGNORECASE,
    )) or stripped[:1].islower()


def _source_text_integrity_issues(text: str, known_titles: list[str] | None = None) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    issues: list[str] = []

    for i in range(1, len(lines) - 1):
        previous_line = lines[i - 1]
        current_line = lines[i]
        next_line = lines[i + 1]
        if (
            _looks_like_title_or_header_line(current_line, known_titles)
            and _line_looks_unfinished(previous_line)
            and _line_continues_sentence(next_line)
        ):
            issues.append("possible page header inserted mid-sentence")
            break

    if re.search(
        r"\b(?:of|for|from|in|into|to|with)\s*\n\s*"
        r"[A-Z][A-Za-z'-]+(?:\s+(?:[A-Z][A-Za-z'-]+|a|an|and|as|by|for|from|in|is|nor|of|on|or|the|to|with)){4,}\s*\n\s*"
        r"(?:that|this|these|those|it|them|which|who)\b",
        text,
    ):
        if "possible page header inserted mid-sentence" not in issues:
            issues.append("possible page header inserted mid-sentence")

    return issues


def _assess_cleaning_risk(metrics: dict[str, Any], integrity_issues: list[str], status: str) -> dict[str, Any]:
    reasons: list[str] = []
    ratio = metrics.get("word_count_ratio", 1.0)
    anchor_required = metrics.get("anchor_required", 0)
    anchor_matches = metrics.get("anchor_matches", 0)

    if status == "fallback":
        reasons.append("fell back to heuristic text")
    if integrity_issues:
        reasons.extend(integrity_issues)
    if abs(ratio - 1.0) > 0.25:
        reasons.append("large word-count delta")
    elif abs(ratio - 1.0) > 0.10:
        reasons.append("moderate word-count delta")
    if anchor_required and anchor_matches < anchor_required:
        reasons.append("missing anchors")

    severe_reasons = {
        "placeholder or summary language",
        "missing source anchor phrases",
        "possible page header inserted mid-sentence",
        "empty output",
        "missing anchors",
        "large word-count delta",
    }
    if any(reason in severe_reasons or reason.startswith("word count shrank") or reason.startswith("word count expanded") for reason in reasons):
        risk_level = "high"
        recommended_action = "review"
    elif reasons:
        risk_level = "medium"
        recommended_action = "review"
    else:
        risk_level = "low"
        recommended_action = "accept"

    return {
        "risk_level": risk_level,
        "risk_reasons": reasons,
        "recommended_action": recommended_action,
    }


def _safe_llm_chunk_text(source_text: str, main_text: str, notes_text: str = "", profile_id: str | None = None) -> tuple[str, str, list[str]]:
    issues = _llm_output_integrity_issues(source_text, main_text, notes_text, profile_id)
    if issues:
        return source_text.strip(), "", issues
    return main_text.strip(), notes_text.strip(), []


def _embedded_generation_sampling_kwargs(temperature: float) -> dict[str, Any]:
    if temperature <= 0:
        return {"do_sample": False}
    return {"temperature": temperature, "do_sample": True}


def _evaluate_llm_chunk(
    chunk_id: int,
    source_text: str,
    candidate_text: str,
    notes_text: str,
    provider: str,
    profile_id: str,
    known_titles: list[str] | None = None,
    source_integrity_issues: list[str] | None = None,
) -> ChunkCleaningEvaluation:
    profile = get_cleaning_profile(profile_id)
    accepted_text, accepted_notes, llm_issues = _safe_llm_chunk_text(source_text, candidate_text, notes_text, profile.id)
    source_issues = _source_text_integrity_issues(source_text, known_titles)
    accepted_issues = _source_text_integrity_issues(accepted_text, known_titles)
    issues = list(dict.fromkeys([*llm_issues, *(source_integrity_issues or []), *source_issues, *accepted_issues]))
    metrics = _llm_output_metrics(source_text, candidate_text, notes_text, profile.id)
    status = "fallback" if llm_issues else "accepted"
    risk = _assess_cleaning_risk(metrics, issues, status)
    return ChunkCleaningEvaluation(
        chunk_id=chunk_id,
        provider=provider,
        profile=profile.id,
        status=status,
        source_text=source_text.strip(),
        candidate_text=candidate_text.strip(),
        accepted_text=accepted_text,
        notes_text=accepted_notes,
        integrity_issues=issues,
        metrics=metrics,
        **risk,
    )


def _parse_llm_clean_output(response_text: str) -> tuple[str, str]:
    try:
        response_json = json.loads(response_text)
        if isinstance(response_json, dict):
            main_text_json = response_json.get("main_text")
            notes_text_json = response_json.get("notes_text", "")
            if isinstance(main_text_json, str):
                notes_text = notes_text_json.strip() if isinstance(notes_text_json, str) else ""
                return main_text_json.strip(), notes_text
    except json.JSONDecodeError:
        pass

    text_match = re.search(r'<text>(.*?)</text>', response_text, re.DOTALL)
    notes_match = re.search(r'<notes>(.*?)</notes>', response_text, re.DOTALL)
    main_text = text_match.group(1).strip() if text_match else response_text.strip()
    notes_text = notes_match.group(1).strip() if notes_match else ""

    if not text_match:
        main_text = re.sub(
            r'^(Here is the cleaned text.*?:|Based on the provided text.*?:\s*|Certainly.*?:|Absolutely.*?:)',
            '',
            main_text,
            flags=re.IGNORECASE | re.DOTALL,
        ).strip()

    if "The text has been" in main_text:
        main_text = re.sub(
            r'The text has been.*?(?:\n\n|\Z)',
            '',
            main_text,
            flags=re.IGNORECASE | re.DOTALL,
        ).strip()

    return main_text, notes_text


def _find_contents_text(chapters: list[dict], max_chars: int = 1500) -> str | None:
    """
    Locate a table-of-contents candidate among the chapters and return a
    snippet of its body text (up to max_chars) to use as a reference for
    repairing truncated chapter titles. Returns None if none is found.
    """
    toc_title_re = re.compile(r"^\s*(table of )?contents\s*$", re.IGNORECASE)
    # A TOC body typically has several segments ending in page numbers.
    page_ref_re = re.compile(r"\D\s\d{1,4}(\s|$)")

    for ch in chapters:
        title = (ch.get("title") or "").strip()
        body = ch.get("raw_text", "") or ""
        if toc_title_re.match(title):
            snippet = body[:max_chars].replace("\n", " ").strip()
            if snippet:
                return snippet
        # Body-based heuristic: many page-number references in a short span.
        if len(page_ref_re.findall(body[:max_chars])) >= 4:
            return body[:max_chars].replace("\n", " ").strip()
    return None


def _apply_chapter_review(
    chapters: list[dict],
    reviewed_list: list,
    contents_reference: str | None = None,
) -> list[dict] | None:
    """
    Apply an LLM chapter review to the heuristic chapter list.

    chapters: list of chapter dicts (title, raw_text, …).
    reviewed_list: list of ReviewedChapterEntry (same length as chapters).

    Returns a new chapter list, or None if the review can't be applied (caller
    should then fall back to the original chapters).

    Rules:
      - "continuation" entries are folded into the previous surviving entry.
      - consecutive "front_matter" entries collapse into one "Frontmatter".
      - consecutive "back_matter" entries collapse into one "Backmatter".
      - "chapter" entries keep their (corrected) title individually.
    """
    if len(reviewed_list) != len(chapters):
        return None

    work = [dict(ch) for ch in chapters]
    reviews = list(reviewed_list)

    # 1. Fold continuation breaks into the previous surviving entry (reverse order).
    for i in range(len(reviews) - 1, 0, -1):
        if reviews[i].section_type == "continuation":
            work[i - 1]["raw_text"] = (
                work[i - 1].get("raw_text", "") + "\n\n" + work[i].get("raw_text", "")
            )
            work.pop(i)
            reviews.pop(i)

    # 2. Group consecutive front/back matter and apply corrected titles.
    result: list[dict] = []
    prev_group: str | None = None  # "front_matter" | "back_matter" | None
    for ch, rv in zip(work, reviews):
        stype = rv.section_type
        if stype in ("front_matter", "back_matter"):
            label = "Frontmatter" if stype == "front_matter" else "Backmatter"
            if prev_group == stype:
                # merge into the last grouped section
                result[-1]["raw_text"] = (
                    result[-1].get("raw_text", "") + "\n\n" + ch.get("raw_text", "")
                )
            else:
                ch["title"] = label
                ch["confidence"] = 0.95
                ch["warnings"] = ["Chapter boundaries reviewed by LLM"]
                result.append(ch)
            prev_group = stype
        else:
            ch["title"] = _title_from_review(ch.get("title", ""), rv.title, contents_reference)
            ch["confidence"] = 0.95
            ch["warnings"] = ["Chapter boundaries reviewed by LLM"]
            result.append(ch)
            prev_group = None

    return result

_cached_pipe = None
_cached_pipe_kwargs = None

def unload_llm():
    """Explicitly unload LLM to free up VRAM."""
    global _cached_pipe, _cached_pipe_kwargs
    if _cached_pipe is not None:
        if hasattr(_cached_pipe, 'model'):
            del _cached_pipe.model
        if hasattr(_cached_pipe, 'tokenizer'):
            del _cached_pipe.tokenizer
        del _cached_pipe
        _cached_pipe = None
        _cached_pipe_kwargs = None
        
        try:
            import torch
            import gc
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()
        except ImportError:
            pass

def fix_soft_hyphenation(text: str) -> str:
    """Join words split by PDF line/page-break hyphenation.

    Examples: ``begin- ning`` -> ``beginning`` and
    ``sweet-\n\nest`` -> ``sweetest``.
    """
    letter = r"[^\W\d_]"
    return re.sub(
        rf"\b({letter}{{2,}})-\s+({letter}{{2,}})\b",
        r"\1\2",
        text,
    )


def regex_clean_text(text: str, known_titles: list[str] | None = None) -> str:
    """
    Basic heuristic cleanup of text.
    - Removes excessive newlines
    - Fixes hyphenated line-breaks
    - Attempts to strip page numbers
    """
    text = fix_soft_hyphenation(text)

    # Remove repeated running headers/footers and floating page numbers.
    text = remove_running_headers(text, known_titles=known_titles)

    # Condense multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()

def _build_cancel_stopping_criteria(cancel_check):
    """
    Return a transformers StoppingCriteriaList that halts generation as soon as
    cancel_check() returns True, or None when cancellation isn't wired up.

    This lets an in-flight embedded LLM generation stop promptly (freeing GPU
    activations) instead of running to completion after the user aborts.
    """
    if not cancel_check:
        return None
    try:
        from transformers import StoppingCriteria, StoppingCriteriaList
    except ImportError:
        return None

    class _CancelCriteria(StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs):
            try:
                return bool(cancel_check())
            except Exception:
                return False

    return StoppingCriteriaList([_CancelCriteria()])

def llm_review_chapters(
    chapters: list[dict],
    provider: str,
    cancel_check=None,
    progress_callback=None,
    prompt_save_path=None,  # Optional Path — saves prompt JSON for debug inspection
) -> list[dict]:
    """
    Validate and refine heuristic chapter boundaries using an LLM.
    Merges false-positive breaks and corrects malformed titles.
    Returns the original chapters list unchanged on any error (graceful fallback).
    """
    from .config import load_config
    cfg = load_config()

    def report(msg: str, pct: int = 20):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg, pct)

    if not chapters:
        return chapters

    if cancel_check and cancel_check():
        return chapters

    # Build compact prompt — first ~400 chars of each chapter's raw_text, hard-capped total.
    # A short lead-in window (tail of the previous chapter) is prepended so the LLM can see
    # both sides of every candidate break when judging false breaks / repairing titles.
    SNIPPET_LEN = 400
    LEADIN_LEN = 120
    MAX_PROMPT_BYTES = 28_000

    def build_chapter_lines(snippet_len: int, leadin_len: int) -> str:
        lines = []
        for i, ch in enumerate(chapters):
            snippet = ch.get("raw_text", "")[:snippet_len].replace("\n", " ").strip()
            leadin = ""
            if i > 0 and leadin_len > 0:
                prev_body = chapters[i - 1].get("raw_text", "")
                leadin = prev_body[-leadin_len:].replace("\n", " ").strip()
            prefix = f'[before: "…{leadin}"] ' if leadin else ""
            lines.append(f'{i + 1}. {prefix}"{ch["title"]}" — "{snippet}"')
        return "\n".join(lines)

    chapter_list = build_chapter_lines(SNIPPET_LEN, LEADIN_LEN)
    if len(chapter_list.encode()) > MAX_PROMPT_BYTES:
        ratio = MAX_PROMPT_BYTES / len(chapter_list.encode())
        reduced_snippet = max(50, int(SNIPPET_LEN * ratio))
        reduced_leadin = max(0, int(LEADIN_LEN * ratio))
        chapter_list = build_chapter_lines(reduced_snippet, reduced_leadin)

    contents_reference = _find_contents_text(chapters)

    SYSTEM_PROMPT = (
        "You are reviewing chapter boundaries detected in a PDF book by a visual heuristic. "
        "Your job is to classify each candidate, correct malformed titles (OCR artifacts), and "
        "reconstruct full titles that the heuristic truncated. Do not add or split chapters."
    )
    reference_block = ""
    if contents_reference:
        reference_block = (
            "REFERENCE TABLE OF CONTENTS (use it to restore correct, complete chapter titles "
            "when a candidate title is truncated or malformed):\n"
            f'"{contents_reference}"\n\n'
        )
    USER_PROMPT = (
        "Review the candidate chapters below. Each entry may include a [before: \"…\"] lead-in "
        "showing the end of the previous candidate, to help you judge the break.\n\n"
        "For each entry, set section_type to one of:\n"
        "  • \"front_matter\" — cover, title page, copyright, dedication, contents, preface/foreword "
        "BEFORE the first real chapter.\n"
        "  • \"chapter\" — a genuine body chapter.\n"
        "  • \"back_matter\" — notes, bibliography, indexes (scripture/person/subject), appendices "
        "AFTER the last real chapter.\n"
        "  • \"continuation\" — a FALSE chapter break (stray subheading, running footer, or "
        "page-number artifact) that belongs to the PRECEDING entry. The FIRST entry must never be "
        "\"continuation\".\n\n"
        "Also: correct any title that is an OCR artifact (e.g. letter-spaced 'G O D' → 'GOD') and "
        "restore the full title when it was truncated (e.g. 'Delight?' → the complete chapter title), "
        "using the reference table of contents and lead-in context where available.\n"
        "Do NOT add chapters or split existing ones.\n\n"
        f"{reference_block}"
        f"Candidates:\n{chapter_list}\n\n"
        'Return ONLY valid JSON in this exact format: '
        '{"chapters": [{"title": "...", "section_type": "chapter", "note": null}]}'
    )

    # Friendly label for the status line — avoids exposing the raw internal
    # provider keyword (e.g. "embedded"), which reads like a cut-off sentence.
    _provider_label = {
        "embedded": "the local model",
        "gemini": "Gemini",
        "openai": "OpenAI",
    }.get(provider, provider)
    report(f"Reviewing {len(chapters)} chapter candidate(s) with {_provider_label}…", 18)

    # Save prompt for debug inspection if a path was provided
    if prompt_save_path is not None:
        try:
            import json as _json
            from pathlib import Path as _Path
            _Path(prompt_save_path).write_text(
                _json.dumps(
                    {
                        "provider": provider,
                        "chapter_count": len(chapters),
                        "system_prompt": SYSTEM_PROMPT,
                        "user_prompt": USER_PROMPT,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as _e:
            logger.warning("Could not save debug prompt: %s", _e)

    try:
        reviewed: ChapterReviewResponse | None = None
        if provider == "gemini" and cfg.gemini_api_key:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=cfg.gemini_api_key)
            config = types.GenerateContentConfig(
                temperature=0.1,
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=ChapterReviewResponse,
            )
            response = _call_gemini_with_retries(
                lambda: client.models.generate_content(
                    model=getattr(cfg, "gemini_model", "gemma-4-31b-it"),
                    contents=USER_PROMPT,
                    config=config,
                ),
                report,
                20,
                cancel_check=cancel_check,
            )
            response_text = (response.text or "").strip()
            if not response_text:
                raise ValueError("Gemini returned an empty chapter review response.")
            reviewed = ChapterReviewResponse.model_validate_json(response_text)

        elif provider == "openai" and cfg.openai_api_key:
            client = OpenAI(api_key=cfg.openai_api_key)
            response = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                temperature=0.1,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": USER_PROMPT},
                ],
                response_format=ChapterReviewResponse,
            )
            reviewed = response.choices[0].message.parsed
            if reviewed is None:
                raise ValueError("OpenAI returned an empty chapter review response.")

        elif provider == "embedded":
            import os
            import torch
            from transformers import pipeline
            from .tts import unload_tts

            model_name = cfg.embedded_llm_model
            if not model_name:
                raise ValueError("No embedded LLM model configured. Select a model in Settings → Local AI.")

            hf_token = cfg.huggingface_token.strip() if cfg.huggingface_token else None
            if hf_token:
                os.environ["HF_TOKEN"] = hf_token
                os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

            device = get_device_string()
            if device == "cpu" or not torch.cuda.is_available():
                raise RuntimeError("The embedded LLM requires a CUDA-capable GPU.")

            pipe_kwargs = {
                "task": "text-generation",
                "model": model_name,
                "torch_dtype": torch.float16,
                "token": hf_token,
            }
            if getattr(cfg, "use_4bit_quantization", False):
                from transformers import BitsAndBytesConfig
                pipe_kwargs["model_kwargs"] = {
                    "quantization_config": BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16,
                    )
                }
                pipe_kwargs["device_map"] = "auto"
            else:
                pipe_kwargs["device"] = device

            global _cached_pipe, _cached_pipe_kwargs
            if _cached_pipe is None or str(_cached_pipe_kwargs) != str(pipe_kwargs):
                unload_tts()
                unload_llm()
                report(f"Loading model '{model_name.split('/')[-1]}' for chapter review…", 20)
                _cached_pipe = pipeline(**pipe_kwargs)
                _cached_pipe_kwargs = pipe_kwargs
            else:
                report("Using cached model weights for chapter review…", 20)

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT},
            ]
            report(
                f"Reviewing {len(chapters)} chapter(s) with the local model…",
                24,
            )

            # Stream generated tokens so the status bar advances during the
            # (otherwise opaque) single inference call. Ramp progress 24→26 as
            # tokens arrive, leaving 27 for the post-merge "complete" report.
            from transformers.generation.streamers import BaseStreamer

            MAX_REVIEW_TOKENS = 1024

            class _ReviewProgressStreamer(BaseStreamer):
                def __init__(self):
                    self.is_first = True
                    self.count = 0

                def put(self, value):
                    if self.is_first:
                        # First call carries the prompt tokens, not generation.
                        self.is_first = False
                        return
                    try:
                        n = value.numel() if hasattr(value, "numel") else len(value)
                    except TypeError:
                        n = 1
                    self.count += n
                    frac = min(1.0, self.count / MAX_REVIEW_TOKENS)
                    report(
                        f"Reviewing chapters with the local model… ({self.count} tokens)",
                        24 + int(frac * 2),
                    )

                def end(self):
                    pass

            review_streamer = _ReviewProgressStreamer()
            result = _cached_pipe(
                messages,
                max_new_tokens=MAX_REVIEW_TOKENS,
                temperature=0.1,
                do_sample=True,
                streamer=review_streamer,
                stopping_criteria=_build_cancel_stopping_criteria(cancel_check),
            )

            # If the user aborted mid-generation, bail out with the original
            # boundaries rather than parsing a truncated response.
            if cancel_check and cancel_check():
                return chapters
            raw_out = result[0]["generated_text"][-1]["content"].strip()

            json_match = re.search(r'\{.*\}', raw_out, re.DOTALL)
            if not json_match:
                raise ValueError("Embedded model returned no parseable JSON for chapter review.")
            reviewed = ChapterReviewResponse.model_validate_json(json_match.group())

        else:
            logger.warning("llm_review_chapters: provider '%s' not usable, skipping review.", provider)
            return chapters

        if reviewed is None:
            return chapters

        # Validate response length matches
        if len(reviewed.chapters) != len(chapters):
            logger.warning(
                "Chapter review returned %d entries for %d chapters — skipping review.",
                len(reviewed.chapters), len(chapters),
            )
            return chapters

        reviewed_chapters = _apply_chapter_review(
            chapters,
            list(reviewed.chapters),
            contents_reference=contents_reference,
        )
        if reviewed_chapters is None:
            return chapters

        report(f"Chapter review complete — {len(reviewed_chapters)} chapter(s) after merging.", 27)
        return reviewed_chapters

    except Exception as exc:
        logger.warning("llm_review_chapters failed (%s) — using original chapter boundaries.", exc)
        return chapters


def llm_clean_text(
    text_chunk: str,
    provider: str = "gemini",
    progress_callback=None,
    cancel_check=None,
    output_callback=None,
    known_titles: list[str] | None = None,
    cleaning_profile: str = "safe",
    return_evaluation: bool = False,
) -> str | tuple[str, dict]:
    """
    Uses an LLM to clean up OCR artifacts, footnotes, and margins.
    progress_callback: Optional callable(str, int) to report status string and progress percentage (0-100).
    cancel_check: Optional callable() -> bool to abort processing early.
    output_callback: Optional callable(str) -> to report chunks of text as they finish.
    """
    from .config import load_config
    import re
    cfg = load_config()
    profile = get_cleaning_profile(cleaning_profile)

    def report(msg: str, pct: int):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg, pct)

    # 1. Regex pre-pass
    report("Running fast regex pre-pass…", 5)
    raw_text_chunk = text_chunk
    text_chunk = regex_clean_text(text_chunk, known_titles=known_titles)

    if provider in ("gemini", "openai"):
        configured_chunk_size = getattr(cfg, "cloud_llm_chunk_size", DEFAULT_CLOUD_LLM_CHUNK_SIZE)
        chunk_size_chars = min(configured_chunk_size, profile.cloud_chunk_size, MAX_CLOUD_LLM_CHUNK_SIZE)
    else:
        configured_chunk_size = getattr(cfg, "llm_chunk_size", DEFAULT_LOCAL_LLM_CHUNK_SIZE)
        chunk_size_chars = min(configured_chunk_size, profile.local_chunk_size, MAX_LOCAL_LLM_CHUNK_SIZE)

    raw_chunks = _split_text_for_llm(raw_text_chunk, chunk_size_chars)
    chunks = _split_text_for_llm(text_chunk, chunk_size_chars)

    report(f"Split document into {len(chunks)} chunks for LLM processing.", 20)

    def build_prompt(chunk_text: str) -> str:
        return (
            "Please clean the following text extracted from a PDF. It has already had basic line breaks fixed. "
            f"Cleaning profile: {profile.label}. {profile.prompt_guidance}\n"
            "Your instructions:\n"
            "1. Output the cleaned main text inside <text>...</text> tags.\n"
            "2. Identify any footnotes and margin notes, and output them inside <notes>...</notes> tags.\n"
            "3. Strip entirely any running headers, footers, and floating page numbers.\n"
            "4. Preserve epigraph, poetry, scripture, and source attribution lines such as 'C. S. LEWIS', 'Till We Have Faces', 'PSALM 63:1', and spaced OCR forms like 'P S A L M 6 3 : 1'. Do not treat them as headers/footers.\n"
            "5. Fix OCR errors: Reconstruct mangled or fragmented words (e.g., 'T E R T U L L I A N' -> 'TERTULLIAN'). Correct obvious typos caused by bad scanning.\n"
            "6. Format all major structural headings (e.g., Chapters, Prefaces, Introductions, Prologues, Epilogues) by prefixing them with a Markdown '# ' (e.g., '# Chapter 1', '# Introduction').\n"
            "7. NEVER include any conversational preamble, summary, or analysis. DO NOT output 'Here is the cleaned text'.\n"
            "8. DO NOT omit, summarize, or truncate any text. Do not use placeholders like '...(rest of text)'. You MUST output the full text unaltered except for the requested formatting.\n\n"
            "Here is the text:\n\n"
            + chunk_text
        )

    SYSTEM_PROMPT = (
        "You are a strict text editor. NEVER output conversational filler or preamble. "
        "Output ONLY the intended text formatting, no analysis. Fix fragmented OCR characters into proper words. "
        "Never omit, truncate, or summarize text. "
        f"Profile guidance: {profile.prompt_guidance}"
    )

    cleaned_chunks = []
    all_notes = []
    evaluated_chunks: list[ChunkCleaningEvaluation] = []

    def parse_output(response_text: str):
        return _parse_llm_clean_output(response_text)

    def process_chunk_result(chunk_id, source_chunk, main_text, notes_text):
        raw_chunk_issues = (
            _source_text_integrity_issues(raw_chunks[chunk_id], known_titles)
            if chunk_id < len(raw_chunks)
            else []
        )
        evaluation = _evaluate_llm_chunk(
            chunk_id,
            source_chunk,
            main_text,
            notes_text,
            provider,
            profile.id,
            known_titles,
            raw_chunk_issues,
        )
        evaluated_chunks.append(evaluation)
        main_text = evaluation.accepted_text
        notes_text = evaluation.notes_text
        if evaluation.status == "fallback":
            logger.warning(
                "LLM cleanup chunk failed integrity checks (%s); using heuristic chunk.",
                "; ".join(evaluation.integrity_issues),
            )
            report("LLM output looked incomplete; kept heuristic text for this chunk.", 85)
        elif evaluation.integrity_issues:
            logger.warning(
                "Source cleanup chunk needs review (%s).",
                "; ".join(evaluation.integrity_issues),
            )
            report("Source text may have page-split artifacts; flagged this chunk for review.", 85)
        if main_text:
            cleaned_chunks.append(main_text)
        if notes_text:
            all_notes.append(notes_text)
        # Avoid duplicating output for streaming providers by only appending separators
        if provider != "embedded" and output_callback:
            output_callback(main_text + ("\n\n[Notes: " + notes_text + "]" if notes_text else "") + "\n\n")
        elif provider == "embedded" and output_callback:
            output_callback("\n\n---\n\n")

    if provider == "embedded":
        try:
            import torch
            import gc
            import os
            from transformers import pipeline
            from .tts import unload_tts
        except ImportError as e:
            raise ImportError(
                f"Embedded LLM dependencies failed to load ({e}). "
                "Ensure transformers and torch are installed."
            )

        # Ensure TTS models are out of VRAM before we allocate LLM
        unload_tts()

        hf_token = cfg.huggingface_token.strip() if cfg.huggingface_token else None
        if hf_token:
            os.environ["HF_TOKEN"] = hf_token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

        device = get_device_string()
        if device == "cpu" or not __import__('torch').cuda.is_available():
            raise RuntimeError(
                "The embedded LLM requires a CUDA-capable GPU. "
                "No GPU was detected on this system."
            )
        model_name = cfg.embedded_llm_model
        if not model_name:
            raise ValueError("No embedded LLM model configured. Select a model in Settings → Local AI.")

        # Detect first-run download
        try:
            import os as _os
            from pathlib import Path as _Path
            hf_cache = _Path(_os.environ.get("HF_HOME", _Path.home() / ".cache" / "huggingface"))
            safe_name = model_name.replace("/", "--")
            model_cache = hf_cache / "hub" / f"models--{safe_name}"
            is_first_run = not model_cache.exists()
        except Exception:
            is_first_run = False

        load_msg = (
            f"Downloading model '{model_name.split('/')[-1]}' from HuggingFace (first run)…"
            if is_first_run
            else f"Loading model '{model_name.split('/')[-1]}' into GPU VRAM…"
        )
        report(load_msg, 25)
        
        pipe_kwargs = {
            "task": "text-generation",
            "model": model_name,
            "torch_dtype": torch.float16,
            "token": hf_token
        }

        if getattr(cfg, "use_4bit_quantization", False):
            report("Initializing 4-bit quantization configs…", 26)
            from transformers import BitsAndBytesConfig
            pipe_kwargs["model_kwargs"] = {
                "quantization_config": BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    llm_int8_enable_fp32_cpu_offload=True,
                ),
                "offload_buffers": True
            }
            pipe_kwargs["device_map"] = "auto"
        else:
            pipe_kwargs["device"] = device

        global _cached_pipe, _cached_pipe_kwargs
        
        try:
            from transformers.generation.streamers import BaseStreamer
            
            class CallbackStreamer(BaseStreamer):
                def __init__(self, tokenizer, callback):
                    self.tokenizer = tokenizer
                    self.callback = callback
                    self.is_first = True
                    
                def put(self, value):
                    if self.is_first:
                        self.is_first = False
                        return # Skip the prompt part
                    # decode without skip_special_tokens to preserve <think>
                    text = self.tokenizer.decode(value, skip_special_tokens=False)
                    # We might get some garbage tokens, but let's just forward it
                    if self.callback and text:
                        self.callback(text)
                
                def end(self):
                    pass

            if _cached_pipe is None or str(_cached_pipe_kwargs) != str(pipe_kwargs):
                unload_llm()
                report("Moving weights to GPU… (may take a moment)", 28)
                _cached_pipe = pipeline(**pipe_kwargs)
                _cached_pipe_kwargs = pipe_kwargs
            else:
                report("Using cached LLM weights…", 28)

            pipe = _cached_pipe
            
            for i, chunk in enumerate(chunks):
                # Pre-emptively clear any residual fragmentation before starting the next heavy generation
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass

                if cancel_check and cancel_check():
                    report("Processing cancelled.", 0)
                    raise InterruptedError("User cancelled LLM clean text operation.")

                base_prog = 30 + int((i / len(chunks)) * 60)
                report(f"Processing chunk {i+1}/{len(chunks)}…", base_prog)
                
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(chunk)},
                ]
                
                streamer = CallbackStreamer(pipe.tokenizer, output_callback)

                result = pipe(
                    messages, 
                    max_new_tokens=4096, 
                    repetition_penalty=1.2, 
                    streamer=streamer,
                    stopping_criteria=_build_cancel_stopping_criteria(cancel_check),
                    **_embedded_generation_sampling_kwargs(profile.temperature),
                )

                # Generation may have been halted mid-way by an abort — stop now
                # instead of processing the truncated chunk output.
                if cancel_check and cancel_check():
                    report("Processing cancelled.", 0)
                    raise InterruptedError("User cancelled LLM clean text operation.")

                out = result[0]['generated_text']
                raw_out = out[-1]['content'].strip() if isinstance(out, list) else out.strip()
                
                main_text, notes_text = parse_output(raw_out)
                process_chunk_result(i, chunk, main_text, notes_text)
                
                # Free activation memory between chunks
                del streamer
                del messages
                del result
                if 'out' in locals():
                    del out
                if 'raw_out' in locals():
                    del raw_out
                
                try:
                    import torch
                    import gc
                    gc.collect()
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass

        except Exception as e:
            err_msg = str(e)
            if "403" in err_msg or "401" in err_msg or "gated" in err_msg.lower():
                raise RuntimeError(f"Gated Model Access Denied: Ensure your HF token is correct") from e
            raise

    elif provider == "gemini" and cfg.gemini_api_key:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=cfg.gemini_api_key)
        
        def build_cloud_prompt(chunk_text: str) -> str:
            return (
                "Please clean the following text extracted from a PDF. Ensure basic line breaks are fixed. "
                f"Cleaning profile: {profile.label}. {profile.prompt_guidance}\n"
                "Output the cleaned text into `main_text`. Output any footnotes/margin notes into `notes_text`. "
                "Strip running headers/footers/page numbers, but preserve epigraph, poetry, scripture, and source attribution lines such as 'C. S. LEWIS', 'Till We Have Faces', 'PSALM 63:1', and spaced OCR forms like 'P S A L M 6 3 : 1'.\n"
                "Fix OCR errors: Reconstruct mangled or fragmented words (e.g., 'T E R T U L L I A N' -> 'TERTULLIAN'). Catch obvious spelling errors.\n\n"
                "Here is the text:\n\n" + chunk_text
            )
            
        for i, chunk in enumerate(chunks):
            if cancel_check and cancel_check():
                raise InterruptedError("User cancelled.")

            base_prog = 30 + int((i / len(chunks)) * 60)
            report(f"Processing chunk {i+1}/{len(chunks)} via Gemini…", base_prog)
            
            config = types.GenerateContentConfig(
                temperature=profile.temperature,
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=CleanedTextResponse,
            )

            response = _call_gemini_with_retries(
                lambda: client.models.generate_content(
                    model=getattr(cfg, "gemini_model", "gemma-4-31b-it"),
                    contents=build_cloud_prompt(chunk),
                    config=config,
                ),
                report,
                base_prog,
                cancel_check=cancel_check,
            )
            try:
                response_text = (response.text or "").strip()
                if not response_text:
                    raise ValueError("Gemini returned an empty cleanup response.")
                res_obj = CleanedTextResponse.model_validate_json(response_text)
                process_chunk_result(i, chunk, res_obj.main_text, res_obj.notes_text)
            except Exception:
                main_text, notes_text = parse_output((response.text or "").strip())
                process_chunk_result(i, chunk, main_text, notes_text)
            
    elif provider == "openai" and cfg.openai_api_key:
        client = OpenAI(api_key=cfg.openai_api_key)
        
        def build_cloud_prompt(chunk_text: str) -> str:
            return (
                "Please clean the following text extracted from a PDF. Ensure basic line breaks are fixed. "
                f"Cleaning profile: {profile.label}. {profile.prompt_guidance}\n"
                "Output the cleaned text into `main_text`. Output any footnotes/margin notes into `notes_text`. "
                "Strip running headers/footers/page numbers, but preserve epigraph, poetry, scripture, and source attribution lines such as 'C. S. LEWIS', 'Till We Have Faces', 'PSALM 63:1', and spaced OCR forms like 'P S A L M 6 3 : 1'.\n"
                "Fix OCR errors: Reconstruct mangled or fragmented words (e.g., 'T E R T U L L I A N' -> 'TERTULLIAN'). Catch obvious spelling errors.\n\n"
                "Here is the text:\n\n" + chunk_text
            )

        for i, chunk in enumerate(chunks):
            if cancel_check and cancel_check():
                raise InterruptedError("User cancelled.")

            base_prog = 30 + int((i / len(chunks)) * 60)
            report(f"Processing chunk {i+1}/{len(chunks)} via OpenAI…", base_prog)
            response = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                temperature=profile.temperature,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_cloud_prompt(chunk)},
                ],
                response_format=CleanedTextResponse,
            )
            res_obj = response.choices[0].message.parsed
            if res_obj is None:
                raise ValueError("OpenAI returned an empty cleanup response.")
            process_chunk_result(i, chunk, res_obj.main_text, res_obj.notes_text)
    else:
        report(f"Provider '{provider}' not configured, falling back to regex…", 50)
        fallback_text = regex_clean_text(text_chunk)
        if return_evaluation:
            evaluation = TextCleaningEvaluation(
                provider=provider,
                profile=profile.id,
                chunk_count=0,
                accepted_count=0,
                fallback_count=0,
                chunks=[],
            )
            return fallback_text, evaluation.model_dump()
        return fallback_text

    report("Cleanup complete! Merging document…", 95)
    final_doc = "\n\n".join(cleaned_chunks)
    if all_notes:
        final_doc += "\n\n--- NOTES ---\n\n" + "\n\n".join(all_notes)

    if return_evaluation:
        fallback_count = sum(1 for chunk in evaluated_chunks if chunk.status == "fallback")
        evaluation = TextCleaningEvaluation(
            provider=provider,
            profile=profile.id,
            chunk_count=len(evaluated_chunks),
            accepted_count=len(evaluated_chunks) - fallback_count,
            fallback_count=fallback_count,
            chunks=evaluated_chunks,
        )
        return final_doc, evaluation.model_dump()

    return final_doc
