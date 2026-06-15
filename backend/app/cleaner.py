import re
import json
import time
import logging
from typing import Literal
from openai import OpenAI
from pydantic import BaseModel
from .config import settings, get_device_string

class CleanedTextResponse(BaseModel):
    main_text: str
    notes_text: str

SectionType = Literal["front_matter", "chapter", "back_matter", "continuation"]

class ReviewedChapterEntry(BaseModel):
    title: str
    section_type: SectionType
    note: str | None = None

class ChapterReviewResponse(BaseModel):
    chapters: list[ReviewedChapterEntry]

logger = logging.getLogger(__name__)


def _find_contents_text(chapters: list[dict], max_chars: int = 1500) -> str | None:
    """
    Locate a table-of-contents candidate among the chapters and return a
    snippet of its body text (up to max_chars) to use as a reference for
    repairing truncated chapter titles. Returns None if none is found.
    """
    toc_title_re = re.compile(r"^\s*(table of )?contents\s*$", re.IGNORECASE)
    # A TOC body typically has several segments ending in page numbers.
    page_ref_re = re.compile(r"\D\s\d{1,4}(\s|$)")

    for ch in chapters:
        title = (ch.get("title") or "").strip()
        body = ch.get("raw_text", "") or ""
        if toc_title_re.match(title):
            snippet = body[:max_chars].replace("\n", " ").strip()
            if snippet:
                return snippet
        # Body-based heuristic: many page-number references in a short span.
        if len(page_ref_re.findall(body[:max_chars])) >= 4:
            return body[:max_chars].replace("\n", " ").strip()
    return None


def _apply_chapter_review(chapters: list[dict], reviewed_list: list) -> list[dict] | None:
    """
    Apply an LLM chapter review to the heuristic chapter list.

    chapters: list of chapter dicts (title, raw_text, …).
    reviewed_list: list of ReviewedChapterEntry (same length as chapters).

    Returns a new chapter list, or None if the review can't be applied (caller
    should then fall back to the original chapters).

    Rules:
      - "continuation" entries are folded into the previous surviving entry.
      - consecutive "front_matter" entries collapse into one "Frontmatter".
      - consecutive "back_matter" entries collapse into one "Backmatter".
      - "chapter" entries keep their (corrected) title individually.
    """
    if len(reviewed_list) != len(chapters):
        return None

    work = [dict(ch) for ch in chapters]
    reviews = list(reviewed_list)

    # 1. Fold continuation breaks into the previous surviving entry (reverse order).
    for i in range(len(reviews) - 1, 0, -1):
        if reviews[i].section_type == "continuation":
            work[i - 1]["raw_text"] = (
                work[i - 1].get("raw_text", "") + "\n\n" + work[i].get("raw_text", "")
            )
            work.pop(i)
            reviews.pop(i)

    # 2. Group consecutive front/back matter and apply corrected titles.
    result: list[dict] = []
    prev_group: str | None = None  # "front_matter" | "back_matter" | None
    for ch, rv in zip(work, reviews):
        stype = rv.section_type
        if stype in ("front_matter", "back_matter"):
            label = "Frontmatter" if stype == "front_matter" else "Backmatter"
            if prev_group == stype:
                # merge into the last grouped section
                result[-1]["raw_text"] = (
                    result[-1].get("raw_text", "") + "\n\n" + ch.get("raw_text", "")
                )
            else:
                ch["title"] = label
                ch["confidence"] = 0.95
                ch["warnings"] = ["Chapter boundaries reviewed by LLM"]
                result.append(ch)
            prev_group = stype
        else:
            ch["title"] = rv.title
            ch["confidence"] = 0.95
            ch["warnings"] = ["Chapter boundaries reviewed by LLM"]
            result.append(ch)
            prev_group = None

    return result

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

def llm_review_chapters(
    chapters: list[dict],
    provider: str,
    cancel_check=None,
    progress_callback=None,
    prompt_save_path=None,  # Optional Path — saves prompt JSON for debug inspection
) -> list[dict]:
    """
    Validate and refine heuristic chapter boundaries using an LLM.
    Merges false-positive breaks and corrects malformed titles.
    Returns the original chapters list unchanged on any error (graceful fallback).
    """
    from .config import load_config
    cfg = load_config()

    def report(msg: str, pct: int = 20):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg, pct)

    if not chapters:
        return chapters

    if cancel_check and cancel_check():
        return chapters

    # Build compact prompt — first ~400 chars of each chapter's raw_text, hard-capped total.
    # A short lead-in window (tail of the previous chapter) is prepended so the LLM can see
    # both sides of every candidate break when judging false breaks / repairing titles.
    SNIPPET_LEN = 400
    LEADIN_LEN = 120
    MAX_PROMPT_BYTES = 28_000

    def build_chapter_lines(snippet_len: int, leadin_len: int) -> str:
        lines = []
        for i, ch in enumerate(chapters):
            snippet = ch.get("raw_text", "")[:snippet_len].replace("\n", " ").strip()
            leadin = ""
            if i > 0 and leadin_len > 0:
                prev_body = chapters[i - 1].get("raw_text", "")
                leadin = prev_body[-leadin_len:].replace("\n", " ").strip()
            prefix = f'[before: "…{leadin}"] ' if leadin else ""
            lines.append(f'{i + 1}. {prefix}"{ch["title"]}" — "{snippet}"')
        return "\n".join(lines)

    chapter_list = build_chapter_lines(SNIPPET_LEN, LEADIN_LEN)
    if len(chapter_list.encode()) > MAX_PROMPT_BYTES:
        ratio = MAX_PROMPT_BYTES / len(chapter_list.encode())
        reduced_snippet = max(50, int(SNIPPET_LEN * ratio))
        reduced_leadin = max(0, int(LEADIN_LEN * ratio))
        chapter_list = build_chapter_lines(reduced_snippet, reduced_leadin)

    contents_reference = _find_contents_text(chapters)

    SYSTEM_PROMPT = (
        "You are reviewing chapter boundaries detected in a PDF book by a visual heuristic. "
        "Your job is to classify each candidate, correct malformed titles (OCR artifacts), and "
        "reconstruct full titles that the heuristic truncated. Do not add or split chapters."
    )
    reference_block = ""
    if contents_reference:
        reference_block = (
            "REFERENCE TABLE OF CONTENTS (use it to restore correct, complete chapter titles "
            "when a candidate title is truncated or malformed):\n"
            f'"{contents_reference}"\n\n'
        )
    USER_PROMPT = (
        "Review the candidate chapters below. Each entry may include a [before: \"…\"] lead-in "
        "showing the end of the previous candidate, to help you judge the break.\n\n"
        "For each entry, set section_type to one of:\n"
        "  • \"front_matter\" — cover, title page, copyright, dedication, contents, preface/foreword "
        "BEFORE the first real chapter.\n"
        "  • \"chapter\" — a genuine body chapter.\n"
        "  • \"back_matter\" — notes, bibliography, indexes (scripture/person/subject), appendices "
        "AFTER the last real chapter.\n"
        "  • \"continuation\" — a FALSE chapter break (stray subheading, running footer, or "
        "page-number artifact) that belongs to the PRECEDING entry. The FIRST entry must never be "
        "\"continuation\".\n\n"
        "Also: correct any title that is an OCR artifact (e.g. letter-spaced 'G O D' → 'GOD') and "
        "restore the full title when it was truncated (e.g. 'Delight?' → the complete chapter title), "
        "using the reference table of contents and lead-in context where available.\n"
        "Do NOT add chapters or split existing ones.\n\n"
        f"{reference_block}"
        f"Candidates:\n{chapter_list}\n\n"
        'Return ONLY valid JSON in this exact format: '
        '{"chapters": [{"title": "...", "section_type": "chapter", "note": null}]}'
    )

    report(f"Reviewing {len(chapters)} chapter candidate(s) with {provider}…", 18)

    # Save prompt for debug inspection if a path was provided
    if prompt_save_path is not None:
        try:
            import json as _json
            from pathlib import Path as _Path
            _Path(prompt_save_path).write_text(
                _json.dumps(
                    {
                        "provider": provider,
                        "chapter_count": len(chapters),
                        "system_prompt": SYSTEM_PROMPT,
                        "user_prompt": USER_PROMPT,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as _e:
            logger.warning("Could not save debug prompt: %s", _e)

    try:
        if provider == "gemini" and cfg.gemini_api_key:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=cfg.gemini_api_key)
            config = types.GenerateContentConfig(
                temperature=0.1,
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=ChapterReviewResponse,
            )
            response = client.models.generate_content(
                model=getattr(cfg, "gemini_model", "gemini-2.5-flash"),
                contents=USER_PROMPT,
                config=config,
            )
            reviewed = ChapterReviewResponse.model_validate_json(response.text.strip())

        elif provider == "openai" and cfg.openai_api_key:
            client = OpenAI(api_key=cfg.openai_api_key)
            response = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                temperature=0.1,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": USER_PROMPT},
                ],
                response_format=ChapterReviewResponse,
            )
            reviewed = response.choices[0].message.parsed

        elif provider == "embedded":
            import os
            import torch
            from transformers import pipeline
            from .tts import unload_tts

            model_name = cfg.embedded_llm_model
            if not model_name:
                raise ValueError("No embedded LLM model configured. Select a model in Settings → Local AI.")

            hf_token = cfg.huggingface_token.strip() if cfg.huggingface_token else None
            if hf_token:
                os.environ["HF_TOKEN"] = hf_token
                os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

            device = get_device_string()
            if device == "cpu" or not torch.cuda.is_available():
                raise RuntimeError("The embedded LLM requires a CUDA-capable GPU.")

            pipe_kwargs = {
                "task": "text-generation",
                "model": model_name,
                "torch_dtype": torch.float16,
                "token": hf_token,
            }
            if getattr(cfg, "use_4bit_quantization", False):
                from transformers import BitsAndBytesConfig
                pipe_kwargs["model_kwargs"] = {
                    "quantization_config": BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16,
                    )
                }
                pipe_kwargs["device_map"] = "auto"
            else:
                pipe_kwargs["device"] = device

            global _cached_pipe, _cached_pipe_kwargs
            if _cached_pipe is None or str(_cached_pipe_kwargs) != str(pipe_kwargs):
                unload_tts()
                unload_llm()
                report(f"Loading model '{model_name.split('/')[-1]}' for chapter review…", 20)
                _cached_pipe = pipeline(**pipe_kwargs)
                _cached_pipe_kwargs = pipe_kwargs
            else:
                report("Using cached model weights for chapter review…", 20)

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT},
            ]
            result = _cached_pipe(messages, max_new_tokens=1024, temperature=0.1, do_sample=True)
            raw_out = result[0]["generated_text"][-1]["content"].strip()

            json_match = re.search(r'\{.*\}', raw_out, re.DOTALL)
            if not json_match:
                raise ValueError("Embedded model returned no parseable JSON for chapter review.")
            reviewed = ChapterReviewResponse.model_validate_json(json_match.group())

        else:
            logger.warning("llm_review_chapters: provider '%s' not usable, skipping review.", provider)
            return chapters

        # Validate response length matches
        if len(reviewed.chapters) != len(chapters):
            logger.warning(
                "Chapter review returned %d entries for %d chapters — skipping review.",
                len(reviewed.chapters), len(chapters),
            )
            return chapters

        reviewed_chapters = _apply_chapter_review(chapters, list(reviewed.chapters))
        if reviewed_chapters is None:
            return chapters

        report(f"Chapter review complete — {len(reviewed_chapters)} chapter(s) after merging.", 27)
        return reviewed_chapters

    except Exception as exc:
        logger.warning("llm_review_chapters failed (%s) — using original chapter boundaries.", exc)
        return chapters


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

        device = get_device_string()
        if device == "cpu" or not __import__('torch').cuda.is_available():
            raise RuntimeError(
                "The embedded LLM requires a CUDA-capable GPU. "
                "No GPU was detected on this system."
            )
        model_name = cfg.embedded_llm_model
        if not model_name:
            raise ValueError("No embedded LLM model configured. Select a model in Settings → Local AI.")

        # Detect first-run download
        try:
            import os as _os
            from pathlib import Path as _Path
            hf_cache = _Path(_os.environ.get("HF_HOME", _Path.home() / ".cache" / "huggingface"))
            safe_name = model_name.replace("/", "--")
            model_cache = hf_cache / "hub" / f"models--{safe_name}"
            is_first_run = not model_cache.exists()
        except Exception:
            is_first_run = False

        load_msg = (
            f"Downloading model '{model_name.split('/')[-1]}' from HuggingFace (first run)…"
            if is_first_run
            else f"Loading model '{model_name.split('/')[-1]}' into GPU VRAM…"
        )
        report(load_msg, 25)
        
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
            pipe_kwargs["device"] = device

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
