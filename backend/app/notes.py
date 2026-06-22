"""Utilities for detecting and storing non-narrative notes."""

from __future__ import annotations

import re
from statistics import median
from typing import Any

from .page_artifacts import looks_like_small_text_content_line


EXTENDED_NOTE_DETECTION_MODULE_ID = "extended_note_detection"

_LEGACY_NOTES_RE = re.compile(
    r"\n{2,}\s*-{3,}\s*NOTES\s*-{3,}\s*\n+",
    re.IGNORECASE,
)
_NOTE_MARKER_RE = re.compile(r"^\s*(?P<marker>\d{1,3}|[*\u2020\u2021\u00a7])[\).]?\s+")
_REFERENCE_NOTE_RE = re.compile(
    r"\b(?:cf|see|ibid|john|matt|mark|luke|rom|cor|ps|prov|gen|exod|deut)\.?\b|"
    r"\b(?:[ivxlcdm]+|\d+|[i1]v)\.\s*\d+(?:-\d+)?\b",
    re.IGNORECASE,
)


def split_legacy_notes_section(text: str) -> tuple[str, str]:
    """Split old ``--- NOTES ---`` appendices out of chapter text."""

    text = text or ""
    match = _LEGACY_NOTES_RE.search(text)
    if not match:
        return text, ""
    return text[: match.start()].strip(), text[match.end() :].strip()


def strip_legacy_notes_section(text: str) -> str:
    main_text, _ = split_legacy_notes_section(text)
    return main_text.strip()


def extract_note_marker(text: str) -> str | None:
    match = _NOTE_MARKER_RE.match(text or "")
    return match.group("marker") if match else None


def looks_like_reference_note_text(text: str) -> bool:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return False
    return bool(_REFERENCE_NOTE_RE.search(text))


def make_note(
    text: str,
    *,
    note_type: str = "footnote",
    page: int | None = None,
    marker: str | None = None,
    anchor_text: str | None = None,
    anchor_offset: int | None = None,
    confidence: float = 0.8,
    source: str = "detector",
) -> dict[str, Any] | None:
    text = _normalize_note_text(text)
    if not text:
        return None
    note = {
        "type": note_type,
        "text": text,
        "marker": marker or extract_note_marker(text),
        "page": page,
        "anchor_text": anchor_text,
        "anchor_offset": anchor_offset,
        "confidence": confidence,
        "source": source,
    }
    return {key: value for key, value in note.items() if value is not None}


def _normalize_note_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = re.sub(r"^[~\-]+\s*f\.", "cf.", text, flags=re.IGNORECASE)
    text = re.sub(r"\b1v\.", "iv.", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+'(?:\s+')+\s*", " ", text)
    return text.strip()


def notes_from_text(
    notes_text: str,
    *,
    note_type: str = "footnote",
    page: int | None = None,
    anchor_offset: int | None = None,
    confidence: float = 0.75,
    source: str = "llm_cleanup",
) -> list[dict[str, Any]]:
    """Convert a plain-text notes blob into normalized note records."""

    if not (notes_text or "").strip():
        return []
    parts = [
        part.strip()
        for part in re.split(r"\n\s*\n|(?=^\s*\d{1,3}[\).]?\s+)", notes_text, flags=re.MULTILINE)
        if part.strip()
    ]
    return [
        note
        for part in parts
        if (
            note := make_note(
                part,
                note_type=note_type,
                page=page,
                anchor_offset=anchor_offset,
                confidence=confidence,
                source=source,
            )
        )
    ]


def normalize_chapter_notes(notes: Any) -> list[dict[str, Any]]:
    if not isinstance(notes, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in notes:
        if isinstance(item, str):
            note = make_note(item, source="legacy_string")
        elif isinstance(item, dict):
            note = make_note(
                str(item.get("text") or ""),
                note_type=str(item.get("type") or "footnote"),
                page=_int_or_none(item.get("page")),
                marker=item.get("marker"),
                anchor_text=item.get("anchor_text"),
                anchor_offset=_int_or_none(item.get("anchor_offset")),
                confidence=_float_or_default(item.get("confidence"), 0.75),
                source=str(item.get("source") or "detector"),
            )
        else:
            note = None
        if note:
            normalized.append(note)
    return normalized


def classify_page_note_blocks(
    blocks: list[dict[str, Any]],
    *,
    median_size: float,
    page_width: float,
    page_height: float,
    extended_notes: bool = False,
) -> list[dict[str, Any]]:
    """Mark layout blocks that should be stored as notes instead of prose."""

    body_left, body_right = _infer_body_column(blocks, median_size, page_width)
    body_width = max(1.0, body_right - body_left)
    classified: list[dict[str, Any]] = []

    for block in blocks:
        text = (block.get("text") or "").strip()
        bbox = block.get("bbox") or (0.0, 0.0, page_width, page_height)
        x0, y0, x1, _ = bbox
        width = max(0.0, x1 - x0)
        size = float(block.get("size") or median_size)
        is_small = size < median_size * 0.82
        note_type: str | None = None
        confidence = 0.78

        if text and looks_like_small_text_content_line(text):
            classified.append(block)
            continue

        if _looks_like_footnote(text, is_small, y0, width, page_height, body_width):
            note_type = "footnote"
            confidence = 0.9 if extract_note_marker(text) else 0.78
        elif extended_notes and _looks_like_margin_note(
            text,
            is_small,
            x0,
            x1,
            width,
            body_left,
            body_right,
            body_width,
        ):
            note_type = "margin"
            confidence = 0.86 if looks_like_reference_note_text(text) else 0.72

        if note_type:
            classified.append({
                **block,
                "role": note_type,
                "note": make_note(
                    text,
                    note_type=note_type,
                    page=(int(block.get("page", 0)) + 1),
                    confidence=confidence,
                    source="layout",
                ),
            })
        else:
            classified.append(block)

    return classified


def _looks_like_footnote(
    text: str,
    is_small: bool,
    y0: float,
    width: float,
    page_height: float,
    body_width: float,
) -> bool:
    if not text or not is_small:
        return False
    is_bottom = y0 >= page_height * 0.68
    has_marker = bool(extract_note_marker(text))
    return is_bottom and (has_marker or width >= body_width * 0.38)


def _looks_like_margin_note(
    text: str,
    is_small: bool,
    x0: float,
    x1: float,
    width: float,
    body_left: float,
    body_right: float,
    body_width: float,
) -> bool:
    if not text:
        return False
    outside_body = x1 <= body_left - 8 or x0 >= body_right + 8
    if not outside_body:
        return False
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) > 220:
        return False
    if width > body_width * 0.5:
        return False
    return is_small or looks_like_reference_note_text(compact)


def _infer_body_column(
    blocks: list[dict[str, Any]],
    median_size: float,
    page_width: float,
) -> tuple[float, float]:
    candidates = []
    for block in blocks:
        text = block.get("text") or ""
        bbox = block.get("bbox")
        if not bbox:
            continue
        x0, _, x1, _ = bbox
        width = x1 - x0
        word_count = len(re.findall(r"[A-Za-z0-9]+", text))
        size = float(block.get("size") or 0)
        if size >= median_size * 0.82 and word_count >= 5 and width >= page_width * 0.28:
            candidates.append((x0, x1))
    if not candidates:
        return page_width * 0.18, page_width * 0.82
    return float(median([item[0] for item in candidates])), float(median([item[1] for item in candidates]))


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
