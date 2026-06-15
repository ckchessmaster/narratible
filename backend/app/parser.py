import fitz # PyMuPDF
import logging
import re
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

def extract_structured_from_pdf(pdf_path: Path) -> Dict[str, Any]:
    """
    Extracts text and detects chapters using native TOC or layout analysis.
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
            return _extract_via_toc(doc, toc)
            
        logger.info("No native TOC found, performing layout analysis...")
        return _extract_via_layout(doc)
        
    except Exception as e:
        logger.error(f"Failed to parse PDF: {e}")
        raise

def _extract_via_toc(doc: fitz.Document, toc: list) -> Dict[str, Any]:
    chapters = []
    full_text = []
    
    # toc format: [level, title, page_number]
    # We only care about level 1 for top-level chapters, or filter accordingly
    bookmarks = [t for t in toc if t[0] == 1]
    if not bookmarks:
        bookmarks = toc # fallback to all if no level 1
        
    for i, b in enumerate(bookmarks):
        title = b[1]
        start_page = b[2] - 1 # 1-based to 0-based
        end_page = bookmarks[i+1][2] - 1 if i + 1 < len(bookmarks) else len(doc)
        
        # Ensure pages are within bounds
        start_page = max(0, min(start_page, len(doc)-1))
        end_page = max(0, min(end_page, len(doc)))
        
        if start_page >= end_page and i + 1 == len(bookmarks):
            end_page = len(doc)
            
        chapter_text = []
        for page_num in range(start_page, end_page):
            chapter_text.append(doc[page_num].get_text())
            
        raw_text = "\n\n".join(chapter_text).strip()
        if raw_text:
            chapters.append({
                "title": title.strip(),
                "raw_text": raw_text,
                "confidence": 1.0,
                "warnings": []
            })
            full_text.append(raw_text)
            
    # Handle frontmatter before first bookmark
    if bookmarks and bookmarks[0][2] - 1 > 0:
        frontmatter_text = []
        for page_num in range(0, bookmarks[0][2] - 1):
            frontmatter_text.append(doc[page_num].get_text())
        front_raw = "\n\n".join(frontmatter_text).strip()
        if front_raw:
            chapters.insert(0, {
                "title": "Frontmatter",
                "raw_text": front_raw,
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
    chapters = []
    # Track whether body text has accumulated since the last heading so that
    # back-to-back headings merge into one title instead of new chapters.
    title_open = False  # True when the previous block was also a heading
    title_is_placeholder = True  # current title is the untouched "Frontmatter" default

    def finalize_current():
        ch_text = "\n\n".join(current_chapter_text).strip()
        if ch_text:
            chapters.append({
                "title": _despace_title(current_chapter_title),
                "raw_text": ch_text,
                "confidence": 0.8,
                "warnings": ["Detected via visual layout heuristic. Please verify boundaries."],
            })
            cleaned_full_text.append(ch_text)

    for blocks in page_blocks:
        for b in blocks:
            text = b["text"]
            size = b["size"]

            # Skip obvious footnotes or headers/footers (very small text)
            if size < median_size * 0.8:
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
                    title_is_placeholder = False
                title_open = True
            else:
                current_chapter_text.append(text)
                title_open = False

    finalize_current()

    # If we only found Frontmatter, fallback to treating the whole document as one chapter
    if len(chapters) <= 1:
        raw = "\n\n".join(cleaned_full_text).strip()
        chapters = [{
            "title": "Document",
            "raw_text": raw,
            "confidence": 0.5,
            "warnings": ["No chapters detected. Document was not split."]
        }]

    return {
        "raw_text": "\n\n".join(cleaned_full_text),
        "chapters": chapters,
        "method": "layout"
    }


def _extract_via_layout(doc: fitz.Document) -> Dict[str, Any]:
    font_sizes = []

    # Pass 1: Gather all blocks and find median font size, filter out tiny fonts (footnotes)
    page_blocks = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict").get("blocks", [])
        text_blocks = []
        for b in blocks:
            if "lines" in b:
                block_text = ""
                block_fonts = []
                for line in b["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if text:
                            block_text += text + " "
                            block_fonts.append(span["size"])
                            font_sizes.append(span["size"])
                if block_text.strip():
                    avg_size = sum(block_fonts) / len(block_fonts) if block_fonts else 0
                    text_blocks.append({"text": block_text.strip(), "size": avg_size, "page": page_num})
        page_blocks.append(text_blocks)

    font_sizes.sort()
    median_size = font_sizes[len(font_sizes)//2] if font_sizes else 12.0

    # Pass 2: Assemble chapters from blocks (testable pure helper).
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
