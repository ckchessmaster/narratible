import re
import logging
import google.generativeai as genai
from openai import OpenAI
from .config import settings

logger = logging.getLogger(__name__)

def regex_clean_text(text: str) -> str:
    """
    Basic heuristic cleanup of text.
    - Removes excessive newlines
    - Fixes hyphenated line-breaks
    - Attempts to strip page numbers
    """
    # Fix hyphenated line breaks: word-\nword -> wordword
    text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)
    
    # Remove repetitive page numbers or standalone numbers on their own lines
    text = re.sub(r'^\s*\d+\s*$', '', text, flags=re.MULTILINE)
    
    # Condense multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

async def llm_clean_text(text_chunk: str, provider: str = "gemini") -> str:
    """
    Uses an LLM to clean up OCR artifacts, footnotes, and margins.
    """
    prompt = "Please clean the following raw text extracted from a PDF. Fix hyphenation, remove headers/footers/page numbers, and output clean paragraphs:\n\n"
    
    if provider == "gemini" and settings.gemini_api_key:
        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt + text_chunk)
        return response.text
    elif provider == "openai" and settings.openai_api_key:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert text editor. Clean the text, remove OCR errors and headers/footers."},
                {"role": "user", "content": text_chunk}
            ]
        )
        return response.choices[0].message.content
    else:
        logger.warning(f"Provider {provider} not configured, falling back to regex.")
        return regex_clean_text(text_chunk)
