import re
import logging
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
    from .config import load_config
    cfg = load_config()

    prompt = (
        "Please clean the following raw text extracted from a PDF. "
        "Fix hyphenation, remove headers/footers/page numbers, and output clean paragraphs. "
        "If there are any footnotes or margin notes, move them to the bottom of the text and format them as Markdown footnotes (e.g., `[^1]: Footnote details...`).\n\n"
        + text_chunk
    )

    if provider == "embedded":
        import torch
        import gc
        import os
        from transformers import pipeline

        hf_token = cfg.huggingface_token.strip() if cfg.huggingface_token else None
        if hf_token:
            os.environ["HF_TOKEN"] = hf_token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_name = cfg.embedded_llm_model or "HuggingFaceTB/SmolLM2-1.7B-Instruct"

        logger.info(f"Loading embedded LLM {model_name} on {device}")
        
        pipe_kwargs = {
            "task": "text-generation",
            "model": model_name,
            "torch_dtype": torch.float16 if device == "cuda" else torch.float32,
            "token": hf_token
        }

        if getattr(cfg, "use_4bit_quantization", False) and device == "cuda":
            from transformers import BitsAndBytesConfig
            pipe_kwargs["model_kwargs"] = {
                "quantization_config": BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                )
            }
            pipe_kwargs["device_map"] = "auto"
            logger.info("Using 4-bit quantization via bitsandbytes")
        else:
            pipe_kwargs["device"] = device

        # Load pipeline 
        pipe = pipeline(**pipe_kwargs)
        
        messages = [
            {"role": "system", "content": "You are an expert text editor. Clean the text, remove OCR errors and headers/footers. Preserve footnotes as markdown endnotes."},
            {"role": "user", "content": prompt},
        ]
        
        result = pipe(messages, max_new_tokens=4096)
        
        # Free VRAM immediately
        del pipe
        torch.cuda.empty_cache()
        gc.collect()
        
        out = result[0]['generated_text']
        # For text-generation, if messages are used, huggingface might return the last message or list of dicts.
        if isinstance(out, list):
            return out[-1]['content']
        else:
            return out

    if provider == "gemini" and cfg.gemini_api_key:
        from google import genai
        client = genai.Client(api_key=cfg.gemini_api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return response.text
    elif provider == "openai" and cfg.openai_api_key:
        client = OpenAI(api_key=cfg.openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert text editor. Clean the text, remove OCR errors and headers/footers."},
                {"role": "user", "content": text_chunk},
            ]
        )
        return response.choices[0].message.content
    else:
        logger.warning(f"Provider '{provider}' not configured, falling back to regex.")
        return regex_clean_text(text_chunk)
