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

def llm_clean_text(text_chunk: str, provider: str = "gemini", progress_callback=None) -> str:
    """
    Uses an LLM to clean up OCR artifacts, footnotes, and margins.
    progress_callback: Optional callable(str, int) to report status string and progress percentage (0-100).
    """
    from .config import load_config
    cfg = load_config()

    def report(msg: str, pct: int):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg, pct)

    chunk_size_chars = getattr(cfg, "llm_chunk_size", 5000)
    
    # Split text into chunks
    paragraphs = text_chunk.split('\n\n')
    chunks = []
    current_chunk = ""
    for p in paragraphs:
        if len(current_chunk) + len(p) > chunk_size_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk = p
        else:
            current_chunk += "\n\n" + p if current_chunk else p
    if current_chunk:
        chunks.append(current_chunk)

    report(f"Split document into {len(chunks)} chunks for LLM processing.", 20)

    def build_prompt(chunk_text: str, is_multi_pass: bool = False, pass_num: int = 1) -> str:
        if not is_multi_pass:
            return (
                "Please clean the following raw text extracted from a PDF. "
                "Fix hyphenation, remove headers/footers/page numbers, and output clean paragraphs. "
                "If there are any footnotes or margin notes, move them to the bottom of the text and format them as Markdown footnotes (e.g., `[^1]: Footnote details...`).\n\n"
                + chunk_text
            )
        else:
            if pass_num == 1:
                return (
                    "Please execute Pass 1 on the following raw text extracted from a PDF. "
                    "Your ONLY job is to fix hyphenation across lines and remove headers, footers, and floating page numbers. "
                    "Do NOT attempt to process footnotes yet. Just output clean structural paragraphs:\n\n"
                    + chunk_text
                )
            elif pass_num == 2:
                return (
                    "Please execute Pass 2 on the following paragraph-structured text. "
                    "Your job is to identify any footnotes or margin notes. Move them to the bottom of the text block "
                    "and format them strictly as Markdown footnotes (e.g., `[^1]: Footnote details...`). "
                    "Leave the main body text structurally intact:\n\n"
                    + chunk_text
                )
            return chunk_text

    cleaned_chunks = []
    use_multi = getattr(cfg, "multi_pass_cleaning", False)

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

        report(f"Loading embedded LLM '{model_name.split('/')[-1]}' into VRAM...", 25)
        
        pipe_kwargs = {
            "task": "text-generation",
            "model": model_name,
            "torch_dtype": torch.float16 if device == "cuda" else torch.float32,
            "token": hf_token
        }

        if getattr(cfg, "use_4bit_quantization", False) and device == "cuda":
            report("Initializing 4-bit Quantization configs...", 26)
            from transformers import BitsAndBytesConfig
            pipe_kwargs["model_kwargs"] = {
                "quantization_config": BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    llm_int8_enable_fp32_cpu_offload=True,
                ),
                "offload_buffers": True
            }
            pipe_kwargs["device_map"] = "auto"
        else:
            pipe_kwargs["device"] = device

        # Load pipeline 
        try:
            report("Moving weights to GPU... (may take a moment)", 28)
            pipe = pipeline(**pipe_kwargs)
        except Exception as e:
            err_msg = str(e)
            if "403" in err_msg or "401" in err_msg or "gated" in err_msg.lower():
                raise RuntimeError(
                    f"Gated Model Access Denied: Ensure your HuggingFace token is correct and you have accepted the EULA at https://huggingface.co/{model_name}"
                ) from e
            raise
        
        for i, chunk in enumerate(chunks):
            # Calculate a sliding progress window from 30% -> 90% across all chunks
            base_prog = 30 + int((i / len(chunks)) * 60)
            
            if not use_multi:
                report(f"Processing chunk {i+1}/{len(chunks)}...", base_prog)
                prompt = build_prompt(chunk)
                messages = [
                    {"role": "system", "content": "You are an expert text editor. Clean the text, remove OCR errors and headers/footers. Preserve footnotes as markdown endnotes."},
                    {"role": "user", "content": prompt},
                ]
                result = pipe(messages, max_new_tokens=4096)
                out = result[0]['generated_text']
                if isinstance(out, list):
                    cleaned_chunks.append(out[-1]['content'])
                else:
                    cleaned_chunks.append(out)
            else:
                # Pass 1
                report(f"Chunk {i+1}/{len(chunks)} — Pass 1 (Structural fixes)...", base_prog)
                prompt1 = build_prompt(chunk, is_multi_pass=True, pass_num=1)
                msg1 = [{"role": "system", "content": "You are an expert structural editor."}, {"role": "user", "content": prompt1}]
                res1 = pipe(msg1, max_new_tokens=4096)[0]['generated_text']
                mid_text = res1[-1]['content'] if isinstance(res1, list) else res1

                # Pass 2
                report(f"Chunk {i+1}/{len(chunks)} — Pass 2 (Footnote detection)...", base_prog + int((0.5 / len(chunks)) * 60))
                prompt2 = build_prompt(mid_text, is_multi_pass=True, pass_num=2)
                msg2 = [{"role": "system", "content": "You are an expert semantic editor."}, {"role": "user", "content": prompt2}]
                res2 = pipe(msg2, max_new_tokens=4096)[0]['generated_text']
                final_text = res2[-1]['content'] if isinstance(res2, list) else res2
                
                cleaned_chunks.append(final_text)

        # Free VRAM immediately
        report("Unloading model and freeing VRAM...", 92)
        del pipe
        torch.cuda.empty_cache()
        gc.collect()

    elif provider == "gemini" and cfg.gemini_api_key:
        from google import genai
        client = genai.Client(api_key=cfg.gemini_api_key)
        for i, chunk in enumerate(chunks):
            base_prog = 30 + int((i / len(chunks)) * 60)
            report(f"Processing chunk {i+1}/{len(chunks)} via Gemini API...", base_prog)
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=build_prompt(chunk),
            )
            cleaned_chunks.append(response.text)
    elif provider == "openai" and cfg.openai_api_key:
        client = OpenAI(api_key=cfg.openai_api_key)
        for i, chunk in enumerate(chunks):
            base_prog = 30 + int((i / len(chunks)) * 60)
            report(f"Processing chunk {i+1}/{len(chunks)} via OpenAI...", base_prog)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an expert text editor. Clean the text, remove OCR errors and headers/footers."},
                    {"role": "user", "content": chunk},
                ]
            )
            cleaned_chunks.append(response.choices[0].message.content)
    else:
        report(f"Provider '{provider}' not configured, falling back to instant heuristic regex...", 50)
        return regex_clean_text(text_chunk)

    report("Cleanup complete! Merging document...", 95)
    return "\n\n".join(cleaned_chunks)
