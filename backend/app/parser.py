import fitz # PyMuPDF
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

async def extract_text_from_pdf(pdf_path: Path) -> str:
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
