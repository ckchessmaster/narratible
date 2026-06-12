import re
import json
import time
import logging
from openai import OpenAI
from pydantic import BaseModel
from .config import settings

class CleanedTextResponse(BaseModel):
    main_text: str
    notes_text: str

logger = logging.getLogger(__name__)

_cached_pipe = None
_cached_pipe_kwargs = None

def unload_llm():
    """Explicitly unload LLM to free up VRAM."""
    global _cached_pipe, _cached_pipe_kwargs
    if _cached_pipe is not None:
        if hasattr(_cached_pipe, 'model'):
            del _cached_pipe.model
        if hasattr(_cached_pipe, 'tokenizer'):
            del _cached_pipe.tokenizer
        del _cached_pipe
        _cached_pipe = None
        _cached_pipe_kwargs = None
        
        try:
            import torch
            import gc
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()
        except ImportError:
            pass

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

def llm_clean_text(text_chunk: str, provider: str = "gemini", progress_callback=None, cancel_check=None, output_callback=None) -> str:
    """
    Uses an LLM to clean up OCR artifacts, footnotes, and margins.
    progress_callback: Optional callable(str, int) to report status string and progress percentage (0-100).
    cancel_check: Optional callable() -> bool to abort processing early.
    output_callback: Optional callable(str) -> to report chunks of text as they finish.
    """
    from .config import load_config
    import re
    cfg = load_config()

    def report(msg: str, pct: int):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg, pct)

    # 1. Regex pre-pass
    report("Running fast Regex pre-pass...", 5)
    text_chunk = regex_clean_text(text_chunk)

    chunk_size_chars = getattr(cfg, "cloud_llm_chunk_size", 12000) if provider in ("gemini", "openai") else getattr(cfg, "llm_chunk_size", 5000)
    
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

    def build_prompt(chunk_text: str) -> str:
        return (
            "Please clean the following text extracted from a PDF. It has already had basic line breaks fixed. "
            "Your instructions:\n"
            "1. Output the cleaned main text inside <text>...</text> tags.\n"
            "2. Identify any footnotes and margin notes, and output them inside <notes>...</notes> tags.\n"
            "3. Strip entirely any running headers, footers, and floating page numbers.\n"
            "4. Fix OCR errors: Reconstruct mangled or fragmented words (e.g., 'T E R T U L L I A N' -> 'TERTULLIAN'). Correct obvious typos caused by bad scanning.\n"
            "5. Format all major structural headings (e.g., Chapters, Prefaces, Introductions, Prologues, Epilogues) by prefixing them with a Markdown '# ' (e.g., '# Chapter 1', '# Introduction').\n"
            "6. NEVER include any conversational preamble, summary, or analysis. DO NOT output 'Here is the cleaned text'.\n"
            "7. DO NOT omit, summarize, or truncate any text. Do not use placeholders like '...(rest of text)'. You MUST output the full text unaltered except for the requested formatting.\n\n"
            "Here is the text:\n\n"
            + chunk_text
        )

    SYSTEM_PROMPT = "You are a strict text editor. NEVER output conversational filler or preamble. Output ONLY the intended text formatting, no analysis. Fix fragmented OCR characters into proper words. Never omit, truncate, or summarize text."

    cleaned_chunks = []
    all_notes = []

    def parse_output(response_text: str):
        text_match = re.search(r'<text>(.*?)</text>', response_text, re.DOTALL)
        notes_match = re.search(r'<notes>(.*?)</notes>', response_text, re.DOTALL)
        
        main_text = text_match.group(1).strip() if text_match else response_text.strip()
        notes_text = notes_match.group(1).strip() if notes_match else ""
        
        if not text_match:
            # Aggressive stripping of AI preambles if fallback triggered
            main_text = re.sub(r'^(Here is the cleaned text.*?:|Based on the provided text.*?:\s*|Certainly.*?:|Absolutely.*?:)', '', main_text, flags=re.IGNORECASE|re.DOTALL).strip()
        
        if "The text has been" in main_text:
            main_text = re.sub(r'The text has been.*?(?:\n\n|\Z)', '', main_text, flags=re.IGNORECASE|re.DOTALL).strip()
            
        return main_text, notes_text

    def process_chunk_result(main_text, notes_text):
        if main_text:
            cleaned_chunks.append(main_text)
        if notes_text:
            all_notes.append(notes_text)
        # Avoid duplicating output for streaming providers by only appending separators
        if provider != "embedded" and output_callback:
            output_callback(main_text + ("\n\n[Notes: " + notes_text + "]" if notes_text else "") + "\n\n")
        elif provider == "embedded" and output_callback:
            output_callback("\n\n---\n\n")

    if provider == "embedded":
        try:
            import torch
            import gc
            import os
            from transformers import pipeline
            from .tts import unload_tts
        except ImportError as e:
            raise ImportError(
                f"Embedded LLM dependencies failed to load ({e}). "
                "Ensure transformers and torch are installed."
            )

        # Ensure TTS models are out of VRAM before we allocate LLM
        unload_tts()

        hf_token = cfg.huggingface_token.strip() if cfg.huggingface_token else None
        if hf_token:
            os.environ["HF_TOKEN"] = hf_token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

        device = "cuda"
        if not __import__('torch').cuda.is_available():
            raise RuntimeError(
                "The embedded LLM requires a CUDA-capable GPU. "
                "No GPU was detected on this system."
            )
        model_name = cfg.embedded_llm_model or "HuggingFaceTB/SmolLM2-1.7B-Instruct"

        report(f"Loading embedded LLM '{model_name.split('/')[-1]}' into VRAM...", 25)
        
        pipe_kwargs = {
            "task": "text-generation",
            "model": model_name,
            "torch_dtype": torch.float16,
            "token": hf_token
        }

        if getattr(cfg, "use_4bit_quantization", False):
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
            pipe_kwargs["device"] = "cuda"

        global _cached_pipe, _cached_pipe_kwargs
        
        try:
            from transformers.generation.streamers import BaseStreamer
            
            class CallbackStreamer(BaseStreamer):
                def __init__(self, tokenizer, callback):
                    self.tokenizer = tokenizer
                    self.callback = callback
                    self.is_first = True
                    
                def put(self, value):
                    if self.is_first:
                        self.is_first = False
                        return # Skip the prompt part
                    # decode without skip_special_tokens to preserve <think>
                    text = self.tokenizer.decode(value, skip_special_tokens=False)
                    # We might get some garbage tokens, but let's just forward it
                    if self.callback and text:
                        self.callback(text)
                
                def end(self):
                    pass

            if _cached_pipe is None or str(_cached_pipe_kwargs) != str(pipe_kwargs):
                unload_llm()
                report("Moving weights to GPU... (may take a moment)", 28)
                _cached_pipe = pipeline(**pipe_kwargs)
                _cached_pipe_kwargs = pipe_kwargs
            else:
                report("Using cached LLM weights...", 28)

            pipe = _cached_pipe
            
            for i, chunk in enumerate(chunks):
                # Pre-emptively clear any residual fragmentation before starting the next heavy generation
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass

                if cancel_check and cancel_check():
                    report("Processing cancelled.", 0)
                    raise InterruptedError("User cancelled LLM clean text operation.")

                base_prog = 30 + int((i / len(chunks)) * 60)
                report(f"Processing chunk {i+1}/{len(chunks)}...", base_prog)
                
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(chunk)},
                ]
                
                streamer = CallbackStreamer(pipe.tokenizer, output_callback)

                result = pipe(
                    messages, 
                    max_new_tokens=4096, 
                    temperature=getattr(cfg, "llm_temperature", 0.1), 
                    repetition_penalty=1.2, 
                    do_sample=True,
                    streamer=streamer
                )
                out = result[0]['generated_text']
                raw_out = out[-1]['content'].strip() if isinstance(out, list) else out.strip()
                
                main_text, notes_text = parse_output(raw_out)
                process_chunk_result(main_text, notes_text)
                
                # Free activation memory between chunks
                del streamer
                del messages
                del result
                if 'out' in locals():
                    del out
                if 'raw_out' in locals():
                    del raw_out
                
                try:
                    import torch
                    import gc
                    gc.collect()
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass

        except Exception as e:
            err_msg = str(e)
            if "403" in err_msg or "401" in err_msg or "gated" in err_msg.lower():
                raise RuntimeError(f"Gated Model Access Denied: Ensure your HF token is correct") from e
            raise

    elif provider == "gemini" and cfg.gemini_api_key:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=cfg.gemini_api_key)
        
        def build_cloud_prompt(chunk_text: str) -> str:
            return (
                "Please clean the following text extracted from a PDF. Ensure basic line breaks are fixed. "
                "Output the cleaned text into `main_text`. Output any footnotes/margin notes into `notes_text`. "
                "Strip running headers/footers/page numbers.\nFix OCR errors: Reconstruct mangled or fragmented words (e.g., 'T E R T U L L I A N' -> 'TERTULLIAN'). Catch obvious spelling errors.\n\n"
                "Here is the text:\n\n" + chunk_text
            )
            
        for i, chunk in enumerate(chunks):
            if cancel_check and cancel_check():
                raise InterruptedError("User cancelled.")

            base_prog = 30 + int((i / len(chunks)) * 60)
            report(f"Processing chunk {i+1}/{len(chunks)} via Gemini...", base_prog)
            
            config = types.GenerateContentConfig(
                temperature=getattr(cfg, "llm_temperature", 0.1),
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=CleanedTextResponse,
            )

            max_retries = 5
            for attempt in range(max_retries):
                try:
                    response = client.models.generate_content(
                        model=getattr(cfg, "gemini_model", "gemini-2.5-flash"),
                        contents=build_cloud_prompt(chunk),
                        config=config,
                    )
                    break
                except Exception as api_err:
                    err_str = str(api_err)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        if "free_tier" in err_str or "limit: 0" in err_str:
                            raise RuntimeError(
                                "Gemini free-tier quota exhausted (limit is 0). "
                                "Enable billing on your Google AI account or switch to a paid tier: "
                                "https://ai.google.dev/gemini-api/docs/rate-limits"
                            ) from api_err
                        if attempt < max_retries - 1:
                            wait = 2 ** attempt * 10
                            report(f"Gemini rate limited, retrying in {wait}s... (attempt {attempt+1}/{max_retries})", base_prog)
                            time.sleep(wait)
                            continue
                    raise
            try:
                res_obj = CleanedTextResponse.model_validate_json(response.text.strip())
                process_chunk_result(res_obj.main_text, res_obj.notes_text)
            except Exception:
                main_text, notes_text = parse_output(response.text.strip())
                process_chunk_result(main_text, notes_text)
            
    elif provider == "openai" and cfg.openai_api_key:
        client = OpenAI(api_key=cfg.openai_api_key)
        
        def build_cloud_prompt(chunk_text: str) -> str:
            return (
                "Please clean the following text extracted from a PDF. Ensure basic line breaks are fixed. "
                "Output the cleaned text into `main_text`. Output any footnotes/margin notes into `notes_text`. "
                "Strip running headers/footers/page numbers.\nFix OCR errors: Reconstruct mangled or fragmented words (e.g., 'T E R T U L L I A N' -> 'TERTULLIAN'). Catch obvious spelling errors.\n\n"
                "Here is the text:\n\n" + chunk_text
            )

        for i, chunk in enumerate(chunks):
            if cancel_check and cancel_check():
                raise InterruptedError("User cancelled.")

            base_prog = 30 + int((i / len(chunks)) * 60)
            report(f"Processing chunk {i+1}/{len(chunks)} via OpenAI...", base_prog)
            response = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                temperature=getattr(cfg, "llm_temperature", 0.1),
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_cloud_prompt(chunk)},
                ],
                response_format=CleanedTextResponse,
            )
            res_obj = response.choices[0].message.parsed
            process_chunk_result(res_obj.main_text, res_obj.notes_text)
    else:
        report(f"Provider '{provider}' not configured, falling back to regex...", 50)
        return regex_clean_text(text_chunk)

    report("Cleanup complete! Merging document...", 95)
    final_doc = "\n\n".join(cleaned_chunks)
    if all_notes:
        final_doc += "\n\n--- NOTES ---\n\n" + "\n\n".join(all_notes)
        
    return final_doc
