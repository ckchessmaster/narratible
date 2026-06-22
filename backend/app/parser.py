import fitz # PyMuPDF
import logging
import re
from pathlib import Path
from typing import Dict, Any
from statistics import median

from .page_artifacts import looks_like_small_text_content_line
from .notes import classify_page_note_blocks, looks_like_reference_note_text, make_note

logger = logging.getLogger(__name__)


def extract_pdf_metadata(pdf_path: Path, front_matter_text: str | None = None, progress_callback=None) -> tuple[dict[str, str], str]:
    """Extract heuristic metadata and front-matter text from a PDF.

    Returns a tuple ``(metadata, front_matter_text)`` where ``metadata`` contains
    best-effort values for title/author/subject/publisher and
    ``front_matter_text`` contains text for optional LLM verification/fill.
    When callers already extracted text from the PDF, they can pass a front
    matter excerpt to avoid a second PyMuPDF page-text pass.
    """

    metadata: dict[str, str] = {}
    front_pages_text: list[str] = [front_matter_text.strip()] if front_matter_text and front_matter_text.strip() else []

    def report(msg: str):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    try:
        report(f"Reading PDF info metadata from {pdf_path}")
        with fitz.open(str(pdf_path)) as doc:
            raw_meta = doc.metadata or {}

            title = (raw_meta.get("title") or "").strip()
            author = (raw_meta.get("author") or "").strip()
            subject = (raw_meta.get("subject") or raw_meta.get("keywords") or "").strip()
            publisher = (raw_meta.get("publisher") or raw_meta.get("creator") or "").strip()

            if title:
                metadata["title"] = title
            if author:
                metadata["author"] = author
            if subject:
                metadata["subject"] = subject
            if publisher:
                metadata["publisher"] = publisher

            if not front_pages_text:
                front_page_limit = min(len(doc), 4)
                for page_index in range(front_page_limit):
                    report(f"Reading metadata front matter page {page_index + 1} of {front_page_limit}")
                    text = (doc[page_index].get_text() or "").strip()
                    if text:
                        front_pages_text.append(text)

            front_matter_text = "\n\n".join(front_pages_text)
            if front_matter_text:
                isbn_match = re.search(r"\b97[89][-\s]?(?:\d[-\s]?){9}\d\b", front_matter_text)
                if isbn_match:
                    metadata["isbn"] = isbn_match.group(0).replace(" ", "")

                series_match = re.search(
                    r"(?:series|book\s+\d+\s+of)\s*[:\-]?\s*([^\n]{3,120})",
                    front_matter_text,
                    re.IGNORECASE,
                )
                if series_match:
                    metadata["series"] = series_match.group(1).strip()

                language_match = re.search(r"\blanguage\s*[:\-]\s*([A-Za-z\-]{2,32})\b", front_matter_text, re.IGNORECASE)
                if language_match:
                    metadata["language"] = language_match.group(1).strip().lower()

                summary_line = next(
                    (
                        ln.strip()
                        for ln in front_matter_text.splitlines()
                        if len(ln.strip()) >= 40 and not ln.strip().lower().startswith(("copyright", "isbn", "all rights reserved"))
                    ),
                    "",
                )
                if summary_line:
                    metadata["description"] = summary_line
    except Exception as exc:
        logger.warning("Failed to extract PDF metadata from %s: %s", pdf_path, exc)

    front_matter_text = "\n\n".join(front_pages_text).strip()
    return metadata, front_matter_text


def extract_pdf_cover(pdf_path: Path, output_path: Path) -> bool:
    """Render page 0 as JPEG and save it to output_path.

    Returns True when cover extraction succeeds, otherwise False.
    """

    try:
        with fitz.open(str(pdf_path)) as doc:
            if len(doc) == 0:
                return False
            page = doc[0]
            scale = 150 / 72
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pix.save(str(output_path), output="jpg")
            return True
    except Exception as exc:
        logger.warning("Failed to extract PDF cover from %s: %s", pdf_path, exc)
        return False

def extract_structured_from_pdf(pdf_path: Path, progress_callback=None, extended_note_detection: bool = False) -> Dict[str, Any]:
    """
    Extracts text and detects chapters using native TOC or layout analysis.

    progress_callback, if provided, is called as ``callback(message, fraction)``
    where ``fraction`` is a float in 0..1 describing how far extraction has
    progressed. It lets long PDFs report movement instead of looking frozen.

    Returns: {
        "raw_text": "...",
        "chapters": [{"title": "...", "raw_text": "...", "confidence": 1.0, "warnings": []}],
        "method": "toc" | "layout" | "fallback"
    }
    """
    try:
        logger.info(f"Extracting structured text from {pdf_path}")
        doc = fitz.open(str(pdf_path))
        
        toc = doc.get_toc()
        
        if toc:
            logger.info("Found native TOC, extracting by bookmarks...")
            return _extract_via_toc(
                doc,
                toc,
                progress_callback=progress_callback,
                extended_note_detection=extended_note_detection,
            )
            
        logger.info("No native TOC found, performing layout analysis...")
        return _extract_via_layout(
            doc,
            progress_callback=progress_callback,
            extended_note_detection=extended_note_detection,
        )
        
    except Exception as e:
        logger.error(f"Failed to parse PDF: {e}")
        raise

def _extract_via_toc(
    doc: fitz.Document,
    toc: list,
    progress_callback=None,
    extended_note_detection: bool = False,
) -> Dict[str, Any]:
    chapters = []
    full_text = []
    layout_pages, median_size = _extract_layout_pages(
        doc,
        progress_callback=None,
        extended_note_detection=extended_note_detection,
    )
    layout_pages = [
        _classify_page_blocks(
            blocks,
            median_size,
            extended_note_detection=extended_note_detection,
        )
        for blocks in layout_pages
    ]
    
    # toc format: [level, title, page_number]
    # We only care about level 1 for top-level chapters, or filter accordingly
    bookmarks = [t for t in toc if t[0] == 1]
    if not bookmarks:
        bookmarks = toc # fallback to all if no level 1
        
    total = len(bookmarks) or 1
    for i, b in enumerate(bookmarks):
        title = b[1]
        start_page = b[2] - 1 # 1-based to 0-based
        end_page = bookmarks[i+1][2] - 1 if i + 1 < len(bookmarks) else len(doc)
        
        # Ensure pages are within bounds
        start_page = max(0, min(start_page, len(doc)-1))
        end_page = max(0, min(end_page, len(doc)))
        
        if start_page >= end_page and i + 1 == len(bookmarks):
            end_page = len(doc)

        if progress_callback:
            progress_callback(f"Reading section {i+1} of {total}…", (i + 1) / total)

        chapter_text = []
        chapter_notes = []
        for page_num in range(start_page, end_page):
            page_text, page_notes = _page_main_text_and_notes(layout_pages[page_num])
            chapter_text.append(page_text)
            chapter_notes.extend(page_notes)
            
        raw_text = "\n\n".join(chapter_text).strip()
        if raw_text:
            chapters.append({
                "title": title.strip(),
                "raw_text": raw_text,
                "notes": chapter_notes,
                "confidence": 1.0,
                "warnings": []
            })
            full_text.append(raw_text)
            
    # Handle frontmatter before first bookmark
    if bookmarks and bookmarks[0][2] - 1 > 0:
        frontmatter_text = []
        frontmatter_notes = []
        for page_num in range(0, bookmarks[0][2] - 1):
            page_text, page_notes = _page_main_text_and_notes(layout_pages[page_num])
            frontmatter_text.append(page_text)
            frontmatter_notes.extend(page_notes)
        front_raw = "\n\n".join(frontmatter_text).strip()
        if front_raw:
            chapters.insert(0, {
                "title": "Frontmatter",
                "raw_text": front_raw,
                "notes": frontmatter_notes,
                "confidence": 1.0,
                "warnings": []
            })
            full_text.insert(0, front_raw)

    return {
        "raw_text": "\n\n".join(full_text),
        "chapters": chapters,
        "method": "toc"
    }

def _despace_title(text: str) -> str:
    """
    Collapse OCR letter-spacing artifacts in headings.

    Examples:
        "G O D" -> "GOD"
        "J O H N  P I P E R" -> "JOHN PIPER"
        "Chapter  1" -> "Chapter 1"

    Normal words (tokens longer than one character) are left untouched; only
    runs of single-character tokens are glued back together. Word boundaries in
    spaced-out text are inferred from double spaces / larger gaps.
    """
    if not text:
        return text

    # Normalise whitespace but remember where larger gaps were so we can keep
    # word boundaries in fully letter-spaced text like "J O H N  P I P E R".
    # Split on 2+ spaces first to preserve intended word separation.
    segments = re.split(r"\s{2,}", text.strip())
    rebuilt_segments = []
    for segment in segments:
        tokens = segment.split()
        if not tokens:
            continue
        out_tokens = []
        run = []
        for tok in tokens:
            if len(tok) == 1 and tok.isalnum():
                run.append(tok)
            else:
                if run:
                    out_tokens.append("".join(run))
                    run = []
                out_tokens.append(tok)
        if run:
            out_tokens.append("".join(run))
        rebuilt_segments.append(" ".join(out_tokens))

    return " ".join(s for s in rebuilt_segments if s).strip()


def _assemble_chapters_from_blocks(page_blocks: list, median_size: float) -> Dict[str, Any]:
    """
    Build chapter boundaries from already-extracted text blocks.

    page_blocks: list (per page) of lists of dicts with keys:
        "text" (str), "size" (float), "page" (int)
    median_size: median span font size used as the heading threshold baseline.

    Returns the same shape as _extract_via_layout: dict with "raw_text",
    "chapters", "method".

    Consecutive heading blocks with no body text between them are treated as a
    single multi-line title (reconstructing titles that PDF layout split across
    blocks) rather than producing separate empty chapters.
    """
    cleaned_full_text = []
    current_chapter_title = "Frontmatter"
    current_chapter_text = []
    current_chapter_notes = []
    chapters = []
    # Track whether body text has accumulated since the last heading so that
    # back-to-back headings merge into one title instead of new chapters.
    title_open = False  # True when the previous block was also a heading
    title_is_placeholder = True  # current title is the untouched "Frontmatter" default

    def finalize_current():
        ch_text = "\n\n".join(current_chapter_text).strip()
        notes = list(current_chapter_notes)
        if ch_text:
            chapters.append({
                "title": _despace_title(current_chapter_title),
                "raw_text": ch_text,
                "notes": notes,
                "confidence": 0.8,
                "warnings": ["Detected via visual layout heuristic. Please verify boundaries."],
            })
            cleaned_full_text.append(ch_text)

    for blocks in page_blocks:
        for b in blocks:
            text = b["text"]
            size = b["size"]
            if b.get("role") in {"footnote", "margin"}:
                note = b.get("note")
                if note:
                    note = {**note, "anchor_offset": _current_text_offset(current_chapter_text)}
                    _append_chapter_note(current_chapter_notes, note)
                continue

            # Skip obvious footnotes or headers/footers (very small text), but
            # keep meaningful small centered attribution/reference lines.
            if size < median_size * 0.8 and not _should_keep_small_text_block(text):
                continue

            is_heading = False
            # Heading heuristics
            if size > median_size * 1.25 and 3 < len(text) < 100:
                is_heading = True
            elif re.match(r'^(Chapter|Part)\s+[IVXLCDM0-9]+', text, re.IGNORECASE) and len(text) < 60:
                is_heading = True

            if is_heading:
                if title_open:
                    # Previous block was also a heading with no body in between:
                    # this is a continuation of a multi-line title.
                    current_chapter_title = f"{current_chapter_title} {text}"
                elif title_is_placeholder and not current_chapter_text:
                    # First real heading while still on the default placeholder
                    # title with no body yet — adopt it as the title outright.
                    current_chapter_title = text
                    title_is_placeholder = False
                else:
                    # A genuine new heading after body text — close the chapter.
                    finalize_current()
                    current_chapter_title = text
                    current_chapter_text = []
                    current_chapter_notes = []
                    title_is_placeholder = False
                title_open = True
            else:
                current_chapter_text.append(text)
                title_open = False

    finalize_current()

    # If we only found Frontmatter, fallback to treating the whole document as one chapter
    if len(chapters) <= 1:
        raw = "\n\n".join(cleaned_full_text).strip()
        notes = chapters[0].get("notes", []) if chapters else []
        chapters = [{
            "title": "Document",
            "raw_text": raw,
            "notes": notes,
            "confidence": 0.5,
            "warnings": ["No chapters detected. Document was not split."]
        }]

    return {
        "raw_text": "\n\n".join(cleaned_full_text),
        "chapters": chapters,
        "method": "layout"
    }


def _should_keep_small_text_block(text: str) -> bool:
    return looks_like_small_text_content_line(text)


def _current_text_offset(paragraphs: list[str]) -> int:
    if not paragraphs:
        return 0
    return len("\n\n".join(paragraphs))


def _append_chapter_note(notes: list[dict], note: dict):
    previous = notes[-1] if notes else None
    if (
        previous
        and previous.get("type") == note.get("type") == "margin"
        and previous.get("page") == note.get("page")
        and previous.get("anchor_offset") == note.get("anchor_offset")
    ):
        previous["text"] = f"{previous.get('text', '').rstrip()} {note.get('text', '').lstrip()}".strip()
        return
    notes.append(note)


def _extract_layout_pages(
    doc: fitz.Document,
    progress_callback=None,
    extended_note_detection: bool = False,
) -> tuple[list[list[dict]], float]:
    font_sizes = []

    raw_pages = []
    total_pages = len(doc) or 1
    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict").get("blocks", [])
        raw_blocks = []
        for b in blocks:
            if "lines" in b:
                raw_lines = []
                for line in b["lines"]:
                    line_spans = []
                    for span in line["spans"]:
                        raw_text = span["text"]
                        if raw_text.strip():
                            size = span["size"]
                            font_sizes.append(size)
                            line_spans.append({
                                "text": raw_text,
                                "size": size,
                                "bbox": tuple(span.get("bbox", line.get("bbox", b.get("bbox", (0.0, 0.0, page.rect.width, page.rect.height))))),
                            })
                    if line_spans:
                        raw_lines.append({
                            "bbox": tuple(line.get("bbox", b.get("bbox", (0.0, 0.0, page.rect.width, page.rect.height)))),
                            "spans": line_spans,
                        })
                if raw_lines:
                    raw_blocks.append({
                        "bbox": tuple(b.get("bbox", (0.0, 0.0, page.rect.width, page.rect.height))),
                        "lines": raw_lines,
                    })
        raw_pages.append({
            "page": page_num,
            "page_width": page.rect.width,
            "page_height": page.rect.height,
            "blocks": raw_blocks,
        })
        if progress_callback:
            # Reserve the last slice of the bar for boundary detection below.
            progress_callback(
                f"Analyzing page {page_num+1} of {total_pages}…",
                ((page_num + 1) / total_pages) * 0.9,
            )

    font_sizes.sort()
    median_size = font_sizes[len(font_sizes)//2] if font_sizes else 12.0
    page_blocks = [
        _text_blocks_from_raw_page(
            raw_page,
            median_size,
            extended_note_detection=extended_note_detection,
        )
        for raw_page in raw_pages
    ]
    return page_blocks, median_size


def _text_blocks_from_raw_page(
    raw_page: dict,
    median_size: float,
    extended_note_detection: bool = False,
) -> list[dict]:
    page_num = int(raw_page.get("page", 0))
    page_width = float(raw_page.get("page_width") or 612.0)
    page_height = float(raw_page.get("page_height") or 792.0)
    body_left, body_right = _infer_body_column_from_raw_page(raw_page, median_size, page_width)
    text_blocks: list[dict] = []

    def flush(lines: list[str], fonts: list[float], bboxes: list[tuple]):
        if not lines:
            return
        if any(looks_like_small_text_content_line(line) for line in lines):
            block_text = "\n".join(lines)
        else:
            block_text = " ".join(lines)
        if not block_text.strip():
            return
        text_blocks.append({
            "text": block_text.strip(),
            "size": sum(fonts) / len(fonts) if fonts else median_size,
            "page": page_num,
            "bbox": _union_bbox(bboxes) if bboxes else (0.0, 0.0, page_width, page_height),
            "page_width": page_width,
            "page_height": page_height,
        })

    for raw_block in raw_page.get("blocks", []):
        current_lines: list[str] = []
        current_fonts: list[float] = []
        current_bboxes: list[tuple] = []

        for raw_line in raw_block.get("lines", []):
            if extended_note_detection:
                body_spans, note_spans = _split_line_note_spans(
                    raw_line.get("spans", []),
                    median_size,
                    body_left,
                    body_right,
                )
            else:
                body_spans = list(raw_line.get("spans", []))
                note_spans = []
            body_text = "".join(span["text"] for span in body_spans).strip()
            if body_text:
                current_lines.append(body_text)
                current_fonts.extend(span["size"] for span in body_spans)
                current_bboxes.extend(span["bbox"] for span in body_spans)

            if note_spans:
                flush(current_lines, current_fonts, current_bboxes)
                current_lines = []
                current_fonts = []
                current_bboxes = []
                for note_span_group in note_spans:
                    note_text = "".join(span["text"] for span in note_span_group).strip()
                    note = make_note(
                        note_text,
                        note_type="margin",
                        page=page_num + 1,
                        confidence=0.88,
                        source="layout_span",
                    )
                    if note:
                        text_blocks.append({
                            "text": note_text,
                            "size": sum(span["size"] for span in note_span_group) / len(note_span_group),
                            "page": page_num,
                            "bbox": _union_bbox([span["bbox"] for span in note_span_group]),
                            "page_width": page_width,
                            "page_height": page_height,
                            "role": "margin",
                            "note": note,
                        })

        flush(current_lines, current_fonts, current_bboxes)

    return text_blocks


def _split_line_note_spans(
    spans: list[dict],
    median_size: float,
    body_left: float,
    body_right: float,
) -> tuple[list[dict], list[list[dict]]]:
    if not spans:
        return [], []

    body_spans = list(spans)
    note_groups: list[list[dict]] = []

    leading_end = 0
    while leading_end < len(body_spans) and _span_is_left_margin(body_spans[leading_end], body_left, median_size):
        leading_end += 1
    if leading_end:
        leading = body_spans[:leading_end]
        if looks_like_reference_note_text("".join(span["text"] for span in leading)):
            note_groups.append(leading)
            body_spans = body_spans[leading_end:]

    trailing_start = None
    for index, span in enumerate(body_spans):
        tail = body_spans[index:]
        if _span_is_right_margin(span, body_right, median_size) and looks_like_reference_note_text("".join(item["text"] for item in tail)):
            trailing_start = index
            break
    if trailing_start is not None:
        trailing = body_spans[trailing_start:]
        note_groups.append(trailing)
        body_spans = body_spans[:trailing_start]

    if not note_groups and _line_is_standalone_margin_note(body_spans, body_left, body_right):
        note_groups.append(body_spans)
        body_spans = []

    return body_spans, note_groups


def _span_is_left_margin(span: dict, body_left: float, median_size: float) -> bool:
    x0, _, x1, _ = span["bbox"]
    return x1 <= body_left - 3 and span["size"] <= median_size * 0.9


def _span_is_right_margin(span: dict, body_right: float, median_size: float) -> bool:
    x0, _, _, _ = span["bbox"]
    return x0 >= body_right - 2 and span["size"] <= median_size * 0.98


def _line_is_standalone_margin_note(spans: list[dict], body_left: float, body_right: float) -> bool:
    text = "".join(span["text"] for span in spans).strip()
    if not looks_like_reference_note_text(text):
        return False
    x0 = min(span["bbox"][0] for span in spans)
    x1 = max(span["bbox"][2] for span in spans)
    return x1 <= body_left - 3 or x0 >= body_right - 2


def _infer_body_column_from_raw_page(raw_page: dict, median_size: float, page_width: float) -> tuple[float, float]:
    lefts: list[float] = []
    rights: list[float] = []
    for raw_block in raw_page.get("blocks", []):
        for raw_line in raw_block.get("lines", []):
            spans = [
                span
                for span in raw_line.get("spans", [])
                if span["size"] >= median_size * 0.95 and re.search(r"[A-Za-z0-9]", span["text"])
            ]
            text = "".join(span["text"] for span in spans)
            if len(re.findall(r"[A-Za-z0-9]+", text)) < 3:
                continue
            lefts.append(min(span["bbox"][0] for span in spans))
            rights.append(max(span["bbox"][2] for span in spans))
    if not lefts or not rights:
        return page_width * 0.18, page_width * 0.82
    return float(median(lefts)), float(median(rights))


def _union_bbox(bboxes: list[tuple]) -> tuple[float, float, float, float]:
    return (
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    )


def _classify_page_blocks(
    blocks: list[dict],
    median_size: float,
    *,
    extended_note_detection: bool = False,
) -> list[dict]:
    if not blocks:
        return []
    page_width = float(blocks[0].get("page_width") or 0) or 612.0
    page_height = float(blocks[0].get("page_height") or 0) or 792.0
    return classify_page_note_blocks(
        blocks,
        median_size=median_size,
        page_width=page_width,
        page_height=page_height,
        extended_notes=extended_note_detection,
    )


def _page_main_text_and_notes(blocks: list[dict]) -> tuple[str, list[dict]]:
    main_blocks: list[str] = []
    notes: list[dict] = []
    for block in blocks:
        if block.get("role") in {"footnote", "margin"}:
            note = block.get("note")
            if note:
                note = {**note, "anchor_offset": len("\n\n".join(main_blocks))}
                notes.append(note)
        else:
            main_blocks.append(block.get("text", ""))
    return "\n\n".join(text for text in main_blocks if text).strip(), notes


def _extract_via_layout(
    doc: fitz.Document,
    progress_callback=None,
    extended_note_detection: bool = False,
) -> Dict[str, Any]:
    page_blocks, median_size = _extract_layout_pages(
        doc,
        progress_callback=progress_callback,
        extended_note_detection=extended_note_detection,
    )

    if progress_callback:
        progress_callback("Detecting chapter boundaries…", 0.95)

    # Pass 2: Assemble chapters from blocks (testable pure helper).
    page_blocks = [
        _classify_page_blocks(
            blocks,
            median_size,
            extended_note_detection=extended_note_detection,
        )
        for blocks in page_blocks
    ]
    return _assemble_chapters_from_blocks(page_blocks, median_size)

def extract_text_from_pdf(pdf_path: Path) -> str:
    """
    Extract text from a given PDF file.
    """
    try:
        logger.info(f"Extracting text from {pdf_path}")
        doc = fitz.open(str(pdf_path))
        full_text = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            full_text.append(text)
        
        return "\n\n".join(full_text)
    except Exception as e:
        logger.error(f"Failed to parse PDF: {e}")
        raise
