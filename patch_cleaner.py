import re

with open("backend/app/cleaner.py", "r", encoding="utf-8") as f:
    text = f.read()

def new_clean_text():
    return '''def llm_clean_text(text_chunk: str, provider: str = "gemini", progress_callback=None, cancel_check=None, output_callback=None) -> str:
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

    chunk_size_chars = getattr(cfg, "llm_chunk_size", 5000)
    
    # Split text into chunks
    paragraphs = text_chunk.split('\\n\\n')
    chunks = []
    current_chunk = ""
    for p in paragraphs:
        if len(current_chunk) + len(p) > chunk_size_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk = p
        else:
            current_chunk += "\\n\\n" + p if current_chunk else p
    if current_chunk:
        chunks.append(current_chunk)

    report(f"Split document into {len(chunks)} chunks for LLM processing.", 20)

    def build_prompt(chunk_text: str) -> str:
        return (
            "Please clean the following text extracted from a PDF. It has already had basic line breaks fixed. "
            "Your instructions:\\n"
            "1. Output the cleaned main text inside <text>...</text> tags.\\n"
            "2. Identify any footnotes and margin notes, and output them inside <notes>...</notes> tags.\\n"
            "3. Strip entirely any running headers, footers, and floating page numbers.\\n"
            "4. NEVER include any conversational preamble, summary, or analysis.\\n\\n"
            "Here is the text:\\n\\n"
            + chunk_text
        )

    SYSTEM_PROMPT = "You are a strict text editor. Output ONLY the extracted <text> and <notes> tags. NO CONVERSATIONAL PREAMBLE."

    cleaned_chunks = []
    all_notes = []

    def parse_output(response_text: str):
        text_match = re.search(r'<text>(.*?)</text>', response_text, re.DOTALL)
        notes_match = re.search(r'<notes>(.*?)</notes>', response_text, re.DOTALL)
        
        main_text = text_match.group(1).strip() if text_match else response_text.strip()
        notes_text = notes_match.group(1).strip() if notes_match else ""
        
        if "The text has been" in main_text:
            main_text = re.sub(r'The text has been.*?(?:\\n\\n|\\Z)', '', main_text, flags=re.IGNORECASE|re.DOTALL).strip()
            
        return main_text, notes_text

    def process_chunk_result(main_text, notes_text):
        if main_text:
            cleaned_chunks.append(main_text)
        if notes_text:
            all_notes.append(notes_text)
        if output_callback:
            output_callback(main_text + ("\\n\\n[Notes: " + notes_text + "]" if notes_text else ""))

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

        pipe = None
        try:
            report("Moving weights to GPU... (may take a moment)", 28)
            pipe = pipeline(**pipe_kwargs)
            
            for i, chunk in enumerate(chunks):
                if cancel_check and cancel_check():
                    report("Processing cancelled.", 0)
                    raise InterruptedError("User cancelled LLM clean text operation.")

                base_prog = 30 + int((i / len(chunks)) * 60)
                report(f"Processing chunk {i+1}/{len(chunks)}...", base_prog)
                
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(chunk)},
                ]
                result = pipe(messages, max_new_tokens=4096, temperature=0.0, repetition_penalty=1.15, do_sample=False)
                out = result[0]['generated_text']
                raw_out = out[-1]['content'].strip() if isinstance(out, list) else out.strip()
                
                main_text, notes_text = parse_output(raw_out)
                process_chunk_result(main_text, notes_text)
                
        except Exception as e:
            err_msg = str(e)
            if "403" in err_msg or "401" in err_msg or "gated" in err_msg.lower():
                raise RuntimeError(f"Gated Model Access Denied: Ensure your HF token is correct") from e
            raise
        finally:
            report("Unloading model and freeing VRAM...", 92)
            if pipe is not None:
                del pipe
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()

    elif provider == "gemini" and cfg.gemini_api_key:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=cfg.gemini_api_key)
        for i, chunk in enumerate(chunks):
            if cancel_check and cancel_check():
                raise InterruptedError("User cancelled.")

            base_prog = 30 + int((i / len(chunks)) * 60)
            report(f"Processing chunk {i+1}/{len(chunks)} via Gemini...", base_prog)
            
            config = types.GenerateContentConfig(
                temperature=0.0,
                system_instruction=SYSTEM_PROMPT,
            )

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=build_prompt(chunk),
                config=config,
            )
            main_text, notes_text = parse_output(response.text.strip())
            process_chunk_result(main_text, notes_text)
            
    elif provider == "openai" and cfg.openai_api_key:
        client = OpenAI(api_key=cfg.openai_api_key)
        for i, chunk in enumerate(chunks):
            if cancel_check and cancel_check():
                raise InterruptedError("User cancelled.")

            base_prog = 30 + int((i / len(chunks)) * 60)
            report(f"Processing chunk {i+1}/{len(chunks)} via OpenAI...", base_prog)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.0,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(chunk)},
                ]
            )
            main_text, notes_text = parse_output(response.choices[0].message.content.strip())
            process_chunk_result(main_text, notes_text)
    else:
        report(f"Provider '{provider}' not configured, falling back to regex...", 50)
        return regex_clean_text(text_chunk)

    report("Cleanup complete! Merging document...", 95)
    final_doc = "\\n\\n".join(cleaned_chunks)
    if all_notes:
        final_doc += "\\n\\n--- NOTES ---\\n\\n" + "\\n\\n".join(all_notes)
        
    return final_doc
'''

idx = text.find("def llm_clean_text")
if idx != -1:
    with open("backend/app/cleaner.py", "w", encoding="utf-8") as f2:
        f2.write(text[:idx] + new_clean_text())
    print("Patched cleaner.py")
else:
    print("Failed to find start of method")
