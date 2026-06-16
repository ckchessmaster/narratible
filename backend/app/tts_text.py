"""Audio-only text preparation for TTS engines.

These transforms make generated audio easier to pronounce without changing the
stored chapter text or EPUB output. Edge-TTS already has a strong service-side
text normalizer, so full expansion is aimed at local engines.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from .parsing_modules import apply_tts_modules


LOCAL_TTS_ENGINES = {"kokoro", "f5-tts"}


@dataclass(frozen=True)
class TTSSegment:
    text: str
    pause_after_ms: int = 0


def strip_tts_artifacts(text: str) -> str:
    """Remove markup artifacts that should not be spoken."""
    text = text or ""
    text = re.sub(r"(?m)^\[\^\d+\]:.*$", "", text)
    text = re.sub(r"\[\^\d+\]", "", text)
    return text.strip()


def prepare_text_for_tts(
    text: str,
    engine: str = "edge-tts",
    enabled_modules: list[str] | None = None,
) -> str:
    """Return speech-friendly text for synthesis.

    The original project/chapter text is left untouched. For Edge we only do
    artifact cleanup because the hosted service already performs rich text
    normalization. Local engines receive deterministic expansions for common
    audiobook pronunciation problems.
    """
    text = strip_tts_artifacts(text)
    if not text:
        return ""

    if engine not in LOCAL_TTS_ENGINES:
        return normalize_pacing_text(text)

    text = normalize_tts_unicode(text)
    text, protected = _protect_non_prose(text)
    text = apply_tts_modules(text, enabled_modules, engine)
    text = expand_common_abbreviations(text)
    text = expand_units(text)
    text = normalize_pacing_text(text)
    return _restore_non_prose(text, protected)


def normalize_tts_unicode(text: str) -> str:
    """Normalize compatibility glyphs that local TTS tokenizers may drop."""
    return unicodedata.normalize("NFKC", text)


def normalize_pacing_text(text: str) -> str:
    """Normalize spacing around punctuation while preserving paragraphs."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?<!\d)([.!?])(?=[A-Z0-9])", r"\1 ", text)
    return text.strip()


def expand_common_abbreviations(text: str) -> str:
    """Expand high-confidence abbreviations commonly read literally by TTS."""
    replacements = [
        (r"\be\.g\.(?=\s|,|;|:|$)", "for example"),
        (r"\bi\.e\.(?=\s|,|;|:|$)", "that is"),
        (r"\bvs\.(?=\s|$)", "versus"),
        (r"\bcf\.(?=\s|$)", "compare"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    text = re.sub(
        r"\betc\.(?P<trail>[,;:]?)",
        lambda match: "et cetera" + (match.group("trail") or "."),
        text,
        flags=re.IGNORECASE,
    )
    return text


def expand_units(text: str) -> str:
    """Expand common units that local TTS engines often spell out."""
    unit_patterns = [
        (r"\b(?P<num>\d+(?:\.\d+)?)\s*mph\b", "{num} miles per hour"),
        (r"\b(?P<num>\d+(?:\.\d+)?)\s*km/h\b", "{num} kilometers per hour"),
        (r"\b(?P<num>\d+(?:\.\d+)?)\s*kph\b", "{num} kilometers per hour"),
        (r"\b(?P<num>\d+(?:\.\d+)?)\s*lbs?\b", "{num} pounds"),
        (r"\b(?P<num>\d+(?:\.\d+)?)\s*oz\b", "{num} ounces"),
    ]
    for pattern, replacement in unit_patterns:
        text = re.sub(
            pattern,
            lambda match, repl=replacement: repl.format(num=match.group("num")),
            text,
            flags=re.IGNORECASE,
        )
    text = re.sub(r"(?P<num>\d+(?:\.\d+)?)\s*%", r"\g<num> percent", text)
    return text


def segment_text_for_tts(text: str, engine: str = "edge-tts") -> list[TTSSegment]:
    """Split text into speakable chunks with explicit pause durations."""
    text = normalize_pacing_text(text)
    if not text:
        return []
    if engine not in LOCAL_TTS_ENGINES:
        return [TTSSegment(text=text, pause_after_ms=0)]

    max_chars = 420 if engine == "f5-tts" else 900
    sentence_pause_ms = 260
    paragraph_pause_ms = 620

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    segments: list[TTSSegment] = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        sentences = _split_sentences(paragraph)
        pieces: list[str] = []
        for sentence in sentences:
            pieces.extend(_split_long_sentence(sentence, max_chars))

        for piece_index, piece in enumerate(pieces):
            is_last_piece = piece_index == len(pieces) - 1
            is_last_paragraph = paragraph_index == len(paragraphs) - 1
            if is_last_piece:
                pause = 0 if is_last_paragraph else paragraph_pause_ms
            else:
                pause = sentence_pause_ms
            segments.append(TTSSegment(piece, pause))

    if engine == "f5-tts":
        return _merge_short_reference_segments(segments, max_chars)
    return segments


_NON_PROSE_RE = re.compile(
    r"(?:https?://|www\.)\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
)


def _protect_non_prose(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def replace(match: re.Match) -> str:
        placeholder = f"NARRATIBLETTSPLACEHOLDER{len(protected)}"
        protected[placeholder] = match.group(0)
        return placeholder

    return _NON_PROSE_RE.sub(replace, text), protected


def _restore_non_prose(text: str, protected: dict[str, str]) -> str:
    for placeholder, original in protected.items():
        text = text.replace(placeholder, original)
    return text


def _split_sentences(paragraph: str) -> list[str]:
    protected = _protect_non_sentence_periods(paragraph)
    raw_sentences = re.split(r"(?<=[.!?])\s+(?=(?:['\"])?[A-Z0-9])", protected)
    return [_restore_periods(s).strip() for s in raw_sentences if s.strip()]


def _protect_non_sentence_periods(text: str) -> str:
    protected_abbrevs = [
        "Mr", "Mrs", "Ms", "Dr", "Prof", "Rev", "Fr", "Sr", "Jr", "St",
        "No", "Fig", "cf", "vol", "ed", "pp", "p",
    ]
    for abbrev in protected_abbrevs:
        text = re.sub(rf"\b{re.escape(abbrev)}\.", f"{abbrev}<prd>", text)
    text = re.sub(r"\b([A-Z])\.(?=\s+[A-Z])", r"\1<prd>", text)
    return text


def _restore_periods(text: str) -> str:
    return text.replace("<prd>", ".")


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]

    words = sentence.split()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and current_len + extra > max_chars:
            chunks.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += extra
    if current:
        chunks.append(" ".join(current))
    return chunks


def _merge_short_reference_segments(
    segments: list[TTSSegment],
    max_chars: int,
) -> list[TTSSegment]:
    merged: list[TTSSegment] = []
    for segment in segments:
        if (
            merged
            and _looks_like_spoken_scripture_reference(segment.text)
            and len(merged[-1].text) + len(segment.text) + 2 <= max_chars
        ):
            previous = merged[-1]
            merged[-1] = TTSSegment(
                f"{previous.text}\n\n{segment.text}",
                segment.pause_after_ms,
            )
        else:
            merged.append(segment)
    return merged


def _looks_like_spoken_scripture_reference(text: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?:[1-3]\s+)?[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3} "
            r"chapter \d{1,3}, verses? .+",
            text.strip(),
        )
    )