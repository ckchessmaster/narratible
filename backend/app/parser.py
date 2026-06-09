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

def _extract_via_layout(doc: fitz.Document) -> Dict[str, Any]:
    full_text_blocks = []
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
    
    # Filter footnotes/superscripts (e.g. < 0.8 * median) and scripture refs inline
    # Actually, we just need to find headings (size > 1.2 * median)
    
    headings = []
    cleaned_full_text = []
    
    current_chapter_title = "Frontmatter"
    current_chapter_text = []
    chapters = []
    
    for page_num, blocks in enumerate(page_blocks):
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
                # Save previous chapter
                ch_text = "\n\n".join(current_chapter_text).strip()
                if ch_text:
                    chapters.append({
                        "title": current_chapter_title,
                        "raw_text": ch_text,
                        "confidence": 0.8,
                        "warnings": ["Detected via visual layout heuristic. Please verify boundaries."]
                    })
                    cleaned_full_text.append(ch_text)
                
                current_chapter_title = text
                current_chapter_text = []
            else:
                current_chapter_text.append(text)
                
    # final chapter
    ch_text = "\n\n".join(current_chapter_text).strip()
    if ch_text:
        chapters.append({
            "title": current_chapter_title,
            "raw_text": ch_text,
            "confidence": 0.8,
            "warnings": ["Detected via visual layout heuristic. Please verify boundaries."]
        })
        cleaned_full_text.append(ch_text)
        
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
