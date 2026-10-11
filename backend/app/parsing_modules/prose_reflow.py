"""Reflow PDF-wrapped prose while preserving lineated text."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class _ReflowBlock:
    text: str
    preserve: bool = False
    lineated: bool = False


def transform(text: str) -> str:
    """Join wrapped prose lines while preserving likely verse and lists."""
    return reflow_wrapped_prose(text)


def reflow_wrapped_prose(text: str) -> str:
    """Join PDF-wrapped prose lines while preserving lineated text.

    This normalizes visual line breaks from prose extraction, but keeps likely
    verse, lists, citations, and indented quotations intact.
    """
    if not text:
        return ""

    raw_blocks = [
        block.strip("\n")
        for block in re.split(r"\n{2,}", text.replace("\r\n", "\n").replace("\r", "\n"))
        if block.strip()
    ]
    blocks = [_prepare_reflow_block(block) for block in raw_blocks]
    _mark_lineated_sequences(blocks)

    output: list[_ReflowBlock] = []
    for block in blocks:
        if (
            output
            and output[-1].preserve
            and block.preserve
            and output[-1].lineated
            and block.lineated
        ):
            output[-1].text = f"{output[-1].text.rstrip()}\n{block.text.lstrip()}"
        elif (
            output
            and not output[-1].preserve
            and not block.preserve
            and _should_join_reflow_blocks(output[-1].text, block.text)
        ):
            sep = "" if _should_join_reflow_blocks_without_space(output[-1].text, block.text) else " "
            output[-1].text = f"{output[-1].text.rstrip()}{sep}{block.text.lstrip()}"
        else:
            output.append(block)

    return "\n\n".join(block.text for block in output).strip()


def _prepare_reflow_block(block: str) -> _ReflowBlock:
    lines = [line.rstrip() for line in block.split("\n")]
    nonempty = [line for line in lines if line.strip()]
    if not nonempty:
        return _ReflowBlock("")

    lineated = _looks_like_verse_lines(nonempty)
    preserve = lineated or _should_preserve_lineated_block(nonempty)
    if preserve:
        return _ReflowBlock("\n".join(lines).strip(), preserve=True, lineated=lineated)

    if len(nonempty) == 1:
        return _ReflowBlock(nonempty[0].strip())

    joined = " ".join(line.strip() for line in nonempty)
    # Repair hyphenated line wraps (e.g. distinc- tion -> distinction)
    joined = re.sub(r"\b([a-zA-Z]{2,})-\s+([a-zA-Z]{2,})\b", r"\1\2", joined)
    return _ReflowBlock(re.sub(r"[ \t]{2,}", " ", joined).strip())


def _should_preserve_lineated_block(lines: list[str]) -> bool:
    stripped = [line.strip() for line in lines if line.strip()]
    if not stripped:
        return False
    # Structured lists (>= 60% of lines start with bullet/number)
    list_count = sum(1 for line in stripped if _is_list_like_line(line))
    if len(stripped) >= 2 and (list_count / len(stripped) >= 0.6):
        return True
    # Standalone short attributions or source titles (e.g. "PSALM 63:1", "C. S. LEWIS")
    if len(stripped) <= 2 and all(_is_attribution_line(line) or _is_source_title_line(line) for line in stripped):
        return True
    # Structured citation lists where majority of lines start with citation markers
    cit_count = sum(1 for line in stripped if _is_citation_or_note_line(line))
    if len(stripped) >= 2 and (cit_count / len(stripped) >= 0.6):
        return True
    if _looks_like_verse_lines(stripped):
        return True
    return False


def _mark_lineated_sequences(blocks: list[_ReflowBlock]) -> None:
    idx = 0
    while idx < len(blocks):
        if blocks[idx].preserve or "\n" in blocks[idx].text:
            idx += 1
            continue
        if (
            idx + 1 < len(blocks)
            and not blocks[idx + 1].preserve
            and _should_join_reflow_blocks_without_space(blocks[idx].text, blocks[idx + 1].text)
        ):
            idx += 1
            continue
        if (
            idx > 0
            and not blocks[idx - 1].preserve
            and _should_join_reflow_blocks(blocks[idx - 1].text, blocks[idx].text)
        ):
            idx += 1
            continue

        start = idx
        run: list[int] = []
        while idx < len(blocks) and not blocks[idx].preserve and "\n" not in blocks[idx].text:
            if (
                idx + 1 < len(blocks)
                and not blocks[idx + 1].preserve
                and _should_join_reflow_blocks_without_space(blocks[idx].text, blocks[idx + 1].text)
            ):
                break
            line = blocks[idx].text.strip()
            if not _is_lineated_candidate(line):
                break
            run.append(idx)
            idx += 1

        if _looks_like_lineated_sequence([blocks[i].text for i in run]):
            for run_idx in run:
                blocks[run_idx].preserve = True
                blocks[run_idx].lineated = True
        elif idx == start:
            idx += 1


def _looks_like_lineated_sequence(lines: list[str]) -> bool:
    if len(lines) < 3:
        return False
    short_lines = [line for line in lines if len(line.strip()) <= 45]
    avg_words = sum(len(line.split()) for line in lines) / len(lines)
    return len(short_lines) >= 2 and avg_words <= 7


def _looks_like_verse_lines(lines: list[str]) -> bool:
    stripped = [line.strip() for line in lines if line.strip()]
    if len(stripped) < 4:
        return False
    cap_count = sum(1 for line in stripped if line[:1].isupper())
    avg_len = sum(len(line) for line in stripped) / len(stripped)
    avg_words = sum(len(line.split()) for line in stripped) / len(stripped)
    cap_ratio = cap_count / len(stripped)

    # 1. Very short lines with high initial-line capitalization (typical verse / poetry)
    if avg_len <= 45 and avg_words <= 7 and cap_ratio >= 0.75:
        return True
    # 2. Extremely short lineated stanzas (narrow liturgical verse, psalms)
    if avg_len <= 35 and avg_words <= 6:
        return True
    return False


def _is_lineated_candidate(line: str) -> bool:
    if not line:
        return False
    if _is_source_title_line(line):
        return False
    if _is_list_like_line(line) or _is_citation_or_note_line(line):
        return False
    return len(line) <= 80


def _is_list_like_line(line: str) -> bool:
    return bool(re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|[A-Za-z][.)]\s+)", line))


def _is_citation_or_note_line(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(
        r"^(?:\[?\d+\]?|\^\d+|(?:cf|ibid|see|pp?\.|vol\.|chap\.)\b)",
        stripped,
        re.IGNORECASE,
    ))


def _is_attribution_line(line: str) -> bool:
    stripped = line.strip().rstrip("0123456789")
    letters = [ch for ch in stripped if ch.isalpha()]
    if not letters:
        return False
    uppercase = sum(1 for ch in letters if ch.upper() == ch and ch.lower() != ch)
    spaced_caps = bool(re.fullmatch(r"[A-Z0-9 .:;'-]{3,}", stripped))
    return spaced_caps and uppercase / len(letters) >= 0.75


def _is_source_title_line(line: str) -> bool:
    stripped = line.strip()
    if not re.search(r"\d+$", stripped):
        return False
    without_note = stripped.rstrip("0123456789").strip()
    words = without_note.split()
    if not 2 <= len(words) <= 8:
        return False
    titled = sum(1 for word in words if word[:1].isupper())
    return titled >= max(2, len(words) - 1)


def _should_join_reflow_blocks(previous: str, current: str) -> bool:
    previous = previous.rstrip()
    current = current.lstrip()
    if not previous or not current:
        return False
    if previous.endswith((".", "!", "?", ":", ";")):
        return False
    if _is_list_like_line(current) or _is_citation_or_note_line(current):
        return False
    if re.match(r"^\d?\s*[A-Z][A-Za-z]+\s+\d{1,3}:\d{1,3}", current):
        return True
    if current[:1].islower():
        return True
    return bool(re.match(
        r"^(?:that|who|whom|whose|which|where|when|and|or|but|for|because|"
        r"if|while|as|to|of|in|is|are|was|were|the|a|an)\b",
        current,
        re.IGNORECASE,
    ))


def _should_join_reflow_blocks_without_space(previous: str, current: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]", previous.strip()) and current[:1].islower())


def _is_terminal_sentence_punctuation(text: str) -> bool:
    t = text.rstrip()
    t = re.sub(r'[\'"”’\)\]]+$', '', t).rstrip()
    return t.endswith((".", "!", "?"))


def should_stitch_paragraph_blocks(block_a: dict, block_b: dict) -> bool:
    if block_a.get("type", "body") != "body" or block_b.get("type", "body") != "body":
        return False
    if block_a.get("format", "prose") == "verse" or block_b.get("format", "prose") == "verse":
        return False
    if block_a.get("audio_muted") or block_b.get("audio_muted"):
        return False

    text_a = (block_a.get("text") or "").strip()
    text_b = (block_b.get("text") or "").strip()
    if not text_a or not text_b:
        return False

    # Block B cannot be a list, footnote/citation, or verse
    if _is_list_like_line(text_b) or _is_citation_or_note_line(text_b):
        return False
    if _looks_like_verse_lines(text_b.split("\n")):
        return False

    # Trailing hyphen on A always means continuation
    if text_a.endswith("-") or text_a.endswith("\u00ad"):
        return True

    # If A already ends with sentence-terminating punctuation, it's not a broken sentence
    if _is_terminal_sentence_punctuation(text_a):
        return False

    # Leading conditions on B:
    if text_b[:1].islower():
        return True

    # Connective/continuation words
    if re.match(
        r"^(?:that|who|whom|whose|which|where|when|and|or|but|for|because|"
        r"if|while|as|to|of|in|is|are|was|were|the|a|an)\b",
        text_b,
        re.IGNORECASE,
    ):
        return True

    # Bible reference or verse continuation in theological texts
    if re.match(r"^\d?\s*[A-Z][A-Za-z]+\s+\d{1,3}:\d{1,3}", text_b):
        return True

    # Across page boundary (sp_b > sp_a):
    sp_a = block_a.get("source_page")
    sp_b = block_b.get("source_page")
    if sp_a is not None and sp_b is not None and sp_b > sp_a:
        if not _is_source_title_line(text_b):
            return True

    # Same page (or missing source_page) dangling endings:
    last_word = text_a.split()[-1].lower() if text_a.split() else ""
    last_word_clean = re.sub(r"[^a-zA-Z]", "", last_word)
    dangling_words = {
        "the", "a", "an", "of", "in", "to", "and", "or", "but", "with", "for",
        "by", "on", "at", "from", "as", "that", "their", "his", "her", "its",
        "our", "your", "which", "into", "onto", "under", "over", "vil"
    }
    if text_a.endswith((",", ";", ":")) or last_word_clean in dangling_words:
        return True

    return False


def stitch_split_paragraph_blocks(blocks: list[dict]) -> tuple[list[dict], int]:
    """Stitch split prose paragraphs across pages while preserving intervening notes."""
    if not blocks:
        return [], 0

    merged: list[dict] = []
    stitched_count = 0
    i = 0

    while i < len(blocks):
        current = dict(blocks[i])
        if current.get("type", "body") != "body" or current.get("format", "prose") == "verse":
            merged.append(current)
            i += 1
            continue

        intervening: list[dict] = []
        j = i + 1
        found_next_body = None

        while j < len(blocks):
            cand = blocks[j]
            cand_type = cand.get("type", "body")
            if cand_type in {"footnote", "marginalia", "figure_caption"}:
                intervening.append(cand)
                j += 1
                continue
            if cand_type == "body" and cand.get("format", "prose") != "verse":
                found_next_body = (j, cand)
                break
            break

        if found_next_body and should_stitch_paragraph_blocks(current, found_next_body[1]):
            next_idx, next_block = found_next_body
            text_a = (current.get("text") or "").strip()
            text_b = (next_block.get("text") or "").strip()

            if text_a.endswith("-") or text_a.endswith("\u00ad"):
                clean_a = re.sub(r"[-\u00ad]\s*$", "", text_a)
                match_a = re.search(r"([a-zA-Z]+)$", clean_a)
                match_b = re.match(r"^([a-zA-Z]+)", text_b)
                if match_a and match_b:
                    joined_text = clean_a + text_b
                else:
                    joined_text = f"{clean_a} {text_b}"
            else:
                joined_text = f"{text_a} {text_b}"

            current["text"] = reflow_wrapped_prose(joined_text).strip()
            stitched_count += 1

            # Keep intervening footnotes/marginalia right after the stitched block
            merged.append(current)
            for inv in intervening:
                merged.append(inv)
            i = next_idx + 1
            continue

        merged.append(current)
        for inv in intervening:
            merged.append(inv)
        i = j if intervening and not found_next_body else i + 1

    return merged, stitched_count