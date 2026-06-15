"""Detect and remove repeated page furniture from extracted PDF text."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


_STANDALONE_PAGE_RE = re.compile(
    r"^\s*(?:p(?:age)?\.?\s*)?(?:\d{1,4}|[ivxlcdm]{1,8})\s*$",
    re.IGNORECASE,
)
_LEADING_PAGE_RE = re.compile(
    r"^\s*(?:p(?:age)?\.?\s*)?(?:\d{1,4}|[ivxlcdm]{1,8})\s+(?P<body>.+?)\s*$",
    re.IGNORECASE,
)
_TRAILING_PAGE_RE = re.compile(
    r"^\s*(?P<body>.+?)\s+(?:p(?:age)?\.?\s*)?(?:\d{1,4}|[ivxlcdm]{1,8})\s*$",
    re.IGNORECASE,
)
_REFERENCE_RE = re.compile(
    r"\b(?:cf|ibid|see|matt|mark|luke|john|rom|cor|ps|prov|gen|exod|deut)\.?\b"
    r"|\bpp?\.\b|\bvol\.\b|\bchap\.\b|[,;:]",
    re.IGNORECASE,
)
_ALL_CAPS_RE = re.compile(r"^[A-Z0-9 '&.-]{5,90}$")
_CONTINUATION_RE = re.compile(
    r"^(?:[\"']?)(?:[a-z]|that\b|who\b|whom\b|whose\b|which\b|where\b|when\b|"
    r"and\b|or\b|but\b|for\b|because\b|if\b|while\b|as\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _ArtifactCandidate:
    key: str
    has_page_marker: bool
    repeated_title_line: bool = False


def remove_running_headers(text: str, known_titles: list[str] | None = None) -> str:
    """Remove repeated running headers, footers, and floating page numbers.

    The detector is intentionally conservative: number+title lines are removed
    when their stripped title repeats or matches known project/chapter titles.
    Standalone page-number lines are always removed.
    """
    if not text:
        return ""

    known_keys = {
        _normalize_key(title)
        for title in (known_titles or [])
        if title and _normalize_key(title)
    }
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    candidates: dict[int, _ArtifactCandidate] = {}
    counts: dict[str, int] = {}

    for idx, line in enumerate(lines):
        candidate = _candidate_for_line(line)
        if candidate is None:
            continue
        candidates[idx] = candidate
        if candidate.key:
            counts[candidate.key] = counts.get(candidate.key, 0) + 1

    removals: set[int] = set()
    for idx, candidate in candidates.items():
        if not candidate.key:
            removals.add(idx)
            continue
        if counts.get(candidate.key, 0) >= 2:
            removals.add(idx)
            continue
        if candidate.has_page_marker and candidate.key in known_keys:
            removals.add(idx)

    return _rebuild_without_artifacts(lines, removals)


def _candidate_for_line(line: str) -> _ArtifactCandidate | None:
    stripped = line.strip()
    if not stripped:
        return None

    if _STANDALONE_PAGE_RE.match(stripped):
        return _ArtifactCandidate(key="", has_page_marker=True)

    for pattern in (_LEADING_PAGE_RE, _TRAILING_PAGE_RE):
        match = pattern.match(stripped)
        if not match:
            continue
        body = match.group("body").strip()
        if _looks_like_header_text(body):
            return _ArtifactCandidate(
                key=_normalize_key(body),
                has_page_marker=True,
            )

    if _looks_like_repeated_title_line(stripped):
        return _ArtifactCandidate(
            key=_normalize_key(stripped),
            has_page_marker=False,
            repeated_title_line=True,
        )

    return None


def _looks_like_header_text(text: str) -> bool:
    if not 3 <= len(text) <= 90:
        return False
    if _REFERENCE_RE.search(text):
        return False
    if text.endswith((".", "!", "?", ":", ";")):
        return False
    words = text.split()
    if not 2 <= len(words) <= 12:
        return False
    alpha_chars = sum(1 for ch in text if ch.isalpha())
    if alpha_chars < 3:
        return False
    return True


def _looks_like_repeated_title_line(text: str) -> bool:
    if not _ALL_CAPS_RE.match(text):
        return False
    if _REFERENCE_RE.search(text):
        return False
    return len(text.split()) >= 2


def _normalize_key(text: str) -> str:
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _rebuild_without_artifacts(lines: list[str], removals: set[int]) -> str:
    if not removals:
        return "\n".join(lines).strip()

    rebuilt: list[str] = []
    idx = 0
    while idx < len(lines):
        if idx not in removals:
            rebuilt.append(lines[idx])
            idx += 1
            continue

        next_idx = _next_kept_nonempty(lines, removals, idx + 1)
        prev_text = _last_nonempty(rebuilt)
        next_text = lines[next_idx].strip() if next_idx is not None else ""
        if prev_text and next_text and _should_join_across_artifact(prev_text, next_text):
            while rebuilt and not rebuilt[-1].strip():
                rebuilt.pop()
            rebuilt[-1] = rebuilt[-1].rstrip() + " " + next_text.lstrip()
            idx = next_idx + 1
            continue

        idx += 1

    return re.sub(r"\n{3,}", "\n\n", "\n".join(rebuilt)).strip()


def _next_kept_nonempty(lines: list[str], removals: set[int], start: int) -> int | None:
    for idx in range(start, len(lines)):
        if idx in removals:
            continue
        if lines[idx].strip():
            return idx
    return None


def _last_nonempty(lines: list[str]) -> str:
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    return ""


def _should_join_across_artifact(previous: str, following: str) -> bool:
    if previous.rstrip().endswith((".", "!", "?", ":", ";")):
        return False
    return bool(_CONTINUATION_RE.match(following.lstrip()))