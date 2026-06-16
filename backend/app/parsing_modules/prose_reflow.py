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
    return _ReflowBlock(re.sub(r"[ \t]{2,}", " ", joined).strip())


def _should_preserve_lineated_block(lines: list[str]) -> bool:
    if any(line[:1].isspace() for line in lines):
        return True
    if any(_is_source_title_line(line) for line in lines):
        return True
    if any(_is_list_like_line(line) for line in lines):
        return True
    if any(_is_citation_or_note_line(line) for line in lines):
        return True
    if any(_is_attribution_line(line) for line in lines):
        return True
    if len(lines) >= 3 and _looks_like_verse_lines(lines):
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
    if any(_is_attribution_line(line) for line in lines):
        return True
    short_lines = [line for line in lines if len(line.strip()) <= 55]
    avg_words = sum(len(line.split()) for line in lines) / len(lines)
    return len(short_lines) >= 3 and avg_words <= 8


def _looks_like_verse_lines(lines: list[str]) -> bool:
    stripped = [line.strip() for line in lines if line.strip()]
    if len(stripped) < 4:
        return False
    if any(_is_attribution_line(line) for line in stripped):
        return True
    avg_len = sum(len(line) for line in stripped) / len(stripped)
    avg_words = sum(len(line.split()) for line in stripped) / len(stripped)
    return avg_len <= 45 and avg_words <= 7


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
    if re.match(r"^(?:\[?\d+\]?|\^\d+)\s+", stripped):
        return True
    return bool(re.search(r"\b(?:cf|ibid|see|pp?\.|vol\.|chap\.)\b", stripped, re.IGNORECASE))


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