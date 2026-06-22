import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Callable, Literal

from openai import OpenAI
from pydantic import BaseModel

from ..cleaner import (
    DEFAULT_CLOUD_LLM_CHUNK_SIZE,
    DEFAULT_LOCAL_LLM_CHUNK_SIZE,
    MAX_CLOUD_LLM_CHUNK_SIZE,
    MAX_LOCAL_LLM_CHUNK_SIZE,
    _build_cancel_stopping_criteria,
    _call_gemini_with_retries,
    _embedded_generation_sampling_kwargs,
    _has_llm_placeholder,
    _normalize_words,
    _parse_llm_clean_output,
    _split_text_for_llm,
    unload_llm,
)
from ..config import get_device_string, load_config
from ..custom_instructions import render_prompt

logger = logging.getLogger(__name__)

MODERNIZATION_MODULE_ID = "modernize_text"
_PARAGRAPH_ANCHOR_STOPWORDS = {
    "about",
    "after",
    "again",
    "being",
    "could",
    "every",
    "first",
    "great",
    "their",
    "there",
    "these",
    "thing",
    "those",
    "through",
    "under",
    "where",
    "which",
    "while",
    "would",
}


class ModernizedTextResponse(BaseModel):
    modernized_text: str


ModernizationProfileId = Literal["light_update", "standard_modern", "plain_language"]


class ModernizationProfile(BaseModel):
    id: ModernizationProfileId
    label: str
    description: str
    warning: str
    temperature: float
    cloud_chunk_size: int
    local_chunk_size: int
    min_word_ratio: float
    max_word_ratio: float
    prompt_guidance: str


class ChunkModernizationEvaluation(BaseModel):
    chunk_id: int
    provider: str
    profile: ModernizationProfileId
    status: Literal["candidate", "fallback"]
    source_text: str
    candidate_text: str
    accepted_text: str
    integrity_issues: list[str]
    metrics: dict[str, Any]
    similarity_to_previous: float | None = None
    risk_level: Literal["low", "medium", "high"]
    risk_reasons: list[str]
    recommended_action: str
    variants: list[dict[str, Any]]


class TextModernizationEvaluation(BaseModel):
    provider: str
    profile: ModernizationProfileId
    source_language: str = "same"
    target_style: str = "modern readable prose"
    chunk_count: int
    candidate_count: int
    fallback_count: int
    chunks: list[ChunkModernizationEvaluation]


MODERNIZATION_PROFILES: dict[str, ModernizationProfile] = {
    "light_update": ModernizationProfile(
        id="light_update",
        label="Light Update",
        description="Keeps the original style and sentence structure, changing only wording that is likely to confuse modern readers.",
        warning="Changes the least. Best first pass for meaning-sensitive texts, with the lowest drift risk.",
        temperature=0.0,
        cloud_chunk_size=12000,
        local_chunk_size=6000,
        min_word_ratio=0.62,
        max_word_ratio=1.75,
        prompt_guidance=(
            "Modernize only words and constructions that block comprehension. Preserve sentence order, "
            "paragraph order, imagery, claims, names, numbers, dialogue intent, and specialized terms."
        ),
    ),
    "standard_modern": ModernizationProfile(
        id="standard_modern",
        label="Standard Modern",
        description="Updates older wording and sentence flow into natural modern prose while preserving meaning, order, names, and key terms.",
        warning="Recommended default. More readable than Light Update, with moderate drift risk that requires review.",
        temperature=0.1,
        cloud_chunk_size=14000,
        local_chunk_size=7000,
        min_word_ratio=0.55,
        max_word_ratio=1.95,
        prompt_guidance=(
            "Use clear modern wording and syntax, but do not summarize, add interpretation, reorder ideas, "
            "or change the author's claims. Keep names, numbers, quotations, and key terms intact."
        ),
    ),
    "plain_language": ModernizationProfile(
        id="plain_language",
        label="Plain Language",
        description="Rewrites difficult archaic phrasing into simpler modern language for maximum readability.",
        warning="Most likely to change style; compare carefully before applying.",
        temperature=0.2,
        cloud_chunk_size=14000,
        local_chunk_size=7000,
        min_word_ratio=0.48,
        max_word_ratio=2.2,
        prompt_guidance=(
            "Rewrite difficult archaic constructions into plain modern language. Preserve all events, arguments, "
            "speaker intent, names, numbers, and sequence. Do not shorten into a summary."
        ),
    ),
}


def get_modernization_profile(profile_id: str | None = None) -> ModernizationProfile:
    aliases = {
        "faithful": "light_update",
        "balanced": "standard_modern",
        "plain": "plain_language",
    }
    requested = (profile_id or "standard_modern").lower()
    profile_key = aliases.get(requested, requested)
    return MODERNIZATION_PROFILES.get(profile_key, MODERNIZATION_PROFILES["standard_modern"])


def list_modernization_profiles() -> list[dict]:
    return [profile.model_dump() for profile in MODERNIZATION_PROFILES.values()]


def _protected_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"\b(?:\d+[\w:.-]*|[A-Z][A-Za-z'’-]{2,})\b", text):
        normalized = token.strip(".,;:!?()[]{}\"'")
        if normalized and normalized.lower() not in {"The", "And", "But", "For", "This", "That", "Chapter"}:
            tokens.append(normalized)
    seen: set[str] = set()
    unique: list[str] = []
    for token in tokens:
        key = token.lower()
        if key not in seen:
            seen.add(key)
            unique.append(token)
    return unique[:40]


def _modernization_metrics(source_text: str, candidate_text: str) -> dict[str, Any]:
    source_words = _normalize_words(source_text)
    candidate_words = _normalize_words(candidate_text)
    source_paragraphs = [p for p in source_text.split("\n\n") if p.strip()]
    candidate_paragraphs = [p for p in candidate_text.split("\n\n") if p.strip()]
    protected = _protected_tokens(source_text)
    candidate_lower = candidate_text.lower()
    missing_protected = [token for token in protected if token.lower() not in candidate_lower]
    return {
        "source_word_count": len(source_words),
        "output_word_count": len(candidate_words),
        "word_count_ratio": len(candidate_words) / max(1, len(source_words)) if source_words else 1.0,
        "source_paragraph_count": len(source_paragraphs),
        "output_paragraph_count": len(candidate_paragraphs),
        "protected_token_count": len(protected),
        "missing_protected_tokens": missing_protected,
        "missing_source_paragraphs": _missing_source_paragraph_count(source_paragraphs, candidate_text),
    }


def _paragraph_anchor_terms(paragraph: str) -> list[str]:
    terms: list[str] = []
    for word in _normalize_words(paragraph):
        if len(word) < 5 or word in _PARAGRAPH_ANCHOR_STOPWORDS:
            continue
        if word not in terms:
            terms.append(word)
    return terms[:12]


def _missing_source_paragraph_count(source_paragraphs: list[str], candidate_text: str) -> int:
    candidate_words = set(_normalize_words(candidate_text))
    missing = 0
    for paragraph in source_paragraphs:
        if len(_normalize_words(paragraph)) < 12:
            continue
        anchors = _paragraph_anchor_terms(paragraph)
        if len(anchors) < 4:
            continue
        matched = sum(1 for word in anchors if word in candidate_words)
        if matched / len(anchors) < 0.25:
            missing += 1
    return missing


def _modernization_integrity_issues(source_text: str, candidate_text: str, profile_id: str | None = None) -> list[str]:
    profile = get_modernization_profile(profile_id)
    metrics = _modernization_metrics(source_text, candidate_text)
    issues: list[str] = []

    if source_text.strip() and not candidate_text.strip():
        return ["empty output"]

    if _has_llm_placeholder(candidate_text):
        issues.append("placeholder or summary language")

    if re.search(r"\b(?:summary|summarized|modernized version|in modern terms)\b", candidate_text, re.IGNORECASE):
        issues.append("meta or summary language")

    if metrics["source_word_count"] >= 80:
        ratio = metrics["word_count_ratio"]
        if ratio < profile.min_word_ratio:
            issues.append(f"word count shrank to {ratio:.0%}")
        elif ratio > profile.max_word_ratio:
            issues.append(f"word count expanded to {ratio:.0%}")

    missing = metrics.get("missing_protected_tokens") or []
    if missing:
        preview = ", ".join(missing[:5])
        issues.append(f"missing protected tokens: {preview}")

    source_paragraphs = metrics.get("source_paragraph_count", 0)
    output_paragraphs = metrics.get("output_paragraph_count", 0)
    missing_paragraphs = metrics.get("missing_source_paragraphs", 0)
    if missing_paragraphs:
        issues.append(f"possible paragraph omission: {missing_paragraphs} source paragraph(s) not reflected")
    elif source_paragraphs >= 4 and output_paragraphs <= max(1, source_paragraphs // 3):
        issues.append("possible paragraph omission")

    return issues


def _assess_modernization_risk(metrics: dict[str, Any], integrity_issues: list[str], status: str) -> dict[str, Any]:
    reasons = list(integrity_issues)
    ratio = metrics.get("word_count_ratio", 1.0)
    if status == "fallback":
        reasons.append("no usable modernization candidate")
    if abs(ratio - 1.0) > 0.35:
        reasons.append("large word-count delta")
    elif abs(ratio - 1.0) > 0.18:
        reasons.append("moderate word-count delta")

    high_markers = (
        "empty output",
        "placeholder or summary language",
        "meta or summary language",
        "possible paragraph omission",
        "no usable modernization candidate",
        "large word-count delta",
    )
    if any(
        reason.startswith("word count ")
        or reason.startswith("missing protected tokens")
        or reason.startswith("possible paragraph omission")
        or reason in high_markers
        for reason in reasons
    ):
        risk_level = "high"
    elif reasons:
        risk_level = "medium"
    else:
        risk_level = "low"
    return {
        "risk_level": risk_level,
        "risk_reasons": reasons,
        "recommended_action": "review" if risk_level != "low" else "accept",
    }


def _normalized_similarity(a: str, b: str) -> float:
    a_words = " ".join(_normalize_words(a))
    b_words = " ".join(_normalize_words(b))
    if not a_words or not b_words:
        return 0.0
    return SequenceMatcher(None, a_words, b_words).ratio()


def _similarity_to_previous(candidate_text: str, previous_candidates: list[str] | None) -> float | None:
    candidates = [text for text in (previous_candidates or []) if text and text.strip()]
    if not candidates or not candidate_text.strip():
        return None
    return max(_normalized_similarity(candidate_text, previous) for previous in candidates)


def _redo_mode_instruction(redo_mode: str | None) -> str:
    instructions = {
        "try_again": "Produce a materially different modernization candidate while preserving the same source details.",
        "more_faithful": "Preserve more original wording, sentence structure, imagery, and term choices while improving only what blocks comprehension.",
        "more_readable": "Make the prose clearer and smoother for present-day readers while preserving all source details and sequence.",
        "less_condensed": "Restore omitted detail, avoid compression, and ensure the candidate is not a summary.",
        "preserve_key_terms": "Keep protected names, terms, titles, numbers, and specialized vocabulary exactly where possible.",
        "fix_missing_paragraphs": "Ensure every source paragraph is represented in order and no paragraph is omitted or merged away.",
        "custom": "Follow the custom redo instruction while preserving meaning, sequence, and all source details.",
    }
    return instructions.get(redo_mode or "try_again", instructions["try_again"])


def _redo_temperature(profile: ModernizationProfile, redo_context: dict[str, Any] | None) -> float:
    if not redo_context:
        return profile.temperature
    redo_mode = redo_context.get("redo_mode") or "try_again"
    if redo_mode in {"try_again", "more_readable"}:
        return min(profile.temperature + 0.10, 0.35)
    if redo_mode in {"more_faithful", "preserve_key_terms", "fix_missing_paragraphs"}:
        return min(profile.temperature, 0.10)
    return min(profile.temperature + 0.05, 0.30)


def _parse_modernization_output(response_text: str) -> str:
    try:
        response_json = json.loads(response_text)
        if isinstance(response_json, dict):
            modernized = response_json.get("modernized_text") or response_json.get("main_text")
            if isinstance(modernized, str):
                return modernized.strip()
    except json.JSONDecodeError:
        pass

    text_match = re.search(r"<text>(.*?)</text>", response_text, re.DOTALL)
    if text_match:
        return text_match.group(1).strip()
    main_text, _ = _parse_llm_clean_output(response_text)
    return main_text.strip()


def _evaluate_modernization_chunk(
    chunk_id: int,
    source_text: str,
    candidate_text: str,
    provider: str,
    profile_id: str,
    previous_candidates: list[str] | None = None,
) -> ChunkModernizationEvaluation:
    profile = get_modernization_profile(profile_id)
    issues = _modernization_integrity_issues(source_text, candidate_text, profile.id)
    similarity = _similarity_to_previous(candidate_text, previous_candidates)
    if similarity is not None and similarity >= 0.94:
        issues.append("very similar to previous candidate")
    metrics = _modernization_metrics(source_text, candidate_text)
    status = "fallback" if issues and not candidate_text.strip() else "candidate"
    risk = _assess_modernization_risk(metrics, issues, status)
    variant_text = candidate_text.strip()
    variants: list[dict[str, Any]] = []
    if variant_text:
        variants.append({
            "variant_id": f"{chunk_id}-1",
            "provider": provider,
            "profile": profile.id,
            "status": status,
            "candidate_text": variant_text,
            "accepted_text": variant_text,
            "integrity_issues": issues,
            "metrics": metrics,
            "similarity_to_previous": similarity,
            **risk,
        })
    return ChunkModernizationEvaluation(
        chunk_id=chunk_id,
        provider=provider,
        profile=profile.id,
        status=status,
        source_text=source_text.strip(),
        candidate_text=variant_text,
        accepted_text=source_text.strip(),
        integrity_issues=issues,
        metrics=metrics,
        similarity_to_previous=similarity,
        variants=variants,
        **risk,
    )


def _build_system_prompt(profile: ModernizationProfile) -> str:
    return render_prompt(
        "modernization_system",
        profile_guidance=profile.prompt_guidance,
    )


def _build_user_prompt(chunk_text: str, profile: ModernizationProfile, redo_context: dict[str, Any] | None = None) -> str:
    redo_block = ""
    if redo_context:
        previous_candidates = [text for text in (redo_context.get("previous_candidates") or []) if text and text.strip()]
        integrity_issues = redo_context.get("integrity_issues") or []
        instruction = (redo_context.get("instruction") or "").strip()
        previous_preview = "\n\n".join(previous_candidates[-3:])
        redo_block = (
            "\nRedo context:\n"
            f"- Redo mode: {redo_context.get('redo_mode') or 'try_again'}\n"
            f"- Mode instruction: {_redo_mode_instruction(redo_context.get('redo_mode'))}\n"
        )
        if instruction:
            redo_block += f"- Custom instruction: {instruction}\n"
        if integrity_issues:
            redo_block += f"- Prior integrity warnings: {'; '.join(str(issue) for issue in integrity_issues)}\n"
        if previous_preview:
            redo_block += (
                "\nPrevious candidate(s) to improve on. Do not copy these; produce a materially different candidate:\n"
                f"{previous_preview}\n"
            )

    return render_prompt(
        "modernization_user",
        profile_label=profile.label,
        profile_guidance=profile.prompt_guidance,
        redo_block=redo_block,
        chunk_text=chunk_text,
    )


def _configured_chunk_size(provider: str, profile: ModernizationProfile) -> int:
    cfg = load_config()
    if provider in ("gemini", "openai"):
        configured = getattr(cfg, "cloud_llm_chunk_size", DEFAULT_CLOUD_LLM_CHUNK_SIZE)
        return min(configured, profile.cloud_chunk_size, MAX_CLOUD_LLM_CHUNK_SIZE)
    configured = getattr(cfg, "llm_chunk_size", DEFAULT_LOCAL_LLM_CHUNK_SIZE)
    return min(configured, profile.local_chunk_size, MAX_LOCAL_LLM_CHUNK_SIZE)


def llm_modernize_text(
    text: str,
    provider: str = "gemini",
    progress_callback: Callable[[str, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    output_callback: Callable[[str], None] | None = None,
    retry_decision_callback: Callable[[dict], str] | None = None,
    modernization_profile: str = "standard_modern",
    redo_context: dict[str, Any] | None = None,
) -> tuple[str, dict]:
    cfg = load_config()
    profile = get_modernization_profile(modernization_profile)
    generation_temperature = _redo_temperature(profile, redo_context)
    chunk_size_chars = _configured_chunk_size(provider, profile)
    chunks = _split_text_for_llm(text, chunk_size_chars)
    system_prompt = _build_system_prompt(profile)

    def report(msg: str, pct: int):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg, pct)

    report(f"Split chapter into {len(chunks)} modernization chunks.", 10)
    evaluated_chunks: list[ChunkModernizationEvaluation] = []

    def process_chunk_result(chunk_id: int, source_chunk: str, candidate_text: str):
        evaluation = _evaluate_modernization_chunk(
            chunk_id,
            source_chunk,
            candidate_text,
            provider,
            profile.id,
            redo_context.get("previous_candidates") if redo_context else None,
        )
        evaluated_chunks.append(evaluation)
        if output_callback and candidate_text:
            output_callback(candidate_text + "\n\n")
        if evaluation.integrity_issues:
            report("Modernized candidate needs review.", 85)

    if provider == "embedded":
        try:
            import gc
            import os
            import torch
            from transformers import pipeline
            from .. import cleaner as cleaner_module
            from ..tts import unload_tts
        except ImportError as e:
            raise ImportError(
                f"Embedded LLM dependencies failed to load ({e}). Ensure transformers and torch are installed."
            ) from e

        unload_tts()
        hf_token = cfg.huggingface_token.strip() if cfg.huggingface_token else None
        if hf_token:
            os.environ["HF_TOKEN"] = hf_token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

        device = get_device_string()
        if device == "cpu" or not torch.cuda.is_available():
            raise RuntimeError("The embedded LLM requires a CUDA-capable GPU. No GPU was detected on this system.")
        model_name = cfg.embedded_llm_model
        if not model_name:
            raise ValueError("No embedded LLM model configured. Select a model in Settings -> Local AI.")

        pipe_kwargs: dict[str, Any] = {
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
                    llm_int8_enable_fp32_cpu_offload=True,
                ),
                "offload_buffers": True,
            }
            pipe_kwargs["device_map"] = "auto"
        else:
            pipe_kwargs["device"] = device

        if cleaner_module._cached_pipe is None or str(cleaner_module._cached_pipe_kwargs) != str(pipe_kwargs):
            unload_llm()
            report("Loading local LLM for modernization...", 15)
            cleaner_module._cached_pipe = pipeline(**pipe_kwargs)
            cleaner_module._cached_pipe_kwargs = pipe_kwargs
        pipe = cleaner_module._cached_pipe

        for i, chunk in enumerate(chunks):
            if cancel_check and cancel_check():
                raise InterruptedError("User cancelled.")
            base_prog = 20 + int((i / len(chunks)) * 70)
            report(f"Modernizing chunk {i + 1}/{len(chunks)} with local LLM...", base_prog)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _build_user_prompt(chunk, profile, redo_context)},
            ]
            result = pipe(
                messages,
                max_new_tokens=4096,
                repetition_penalty=1.15,
                stopping_criteria=_build_cancel_stopping_criteria(cancel_check),
                **_embedded_generation_sampling_kwargs(generation_temperature),
            )
            if cancel_check and cancel_check():
                raise InterruptedError("User cancelled.")
            out = result[0]["generated_text"]
            raw_out = out[-1]["content"].strip() if isinstance(out, list) else str(out).strip()
            process_chunk_result(i, chunk, _parse_modernization_output(raw_out))
            del messages
            del result
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    elif provider == "gemini" and cfg.gemini_api_key:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=cfg.gemini_api_key)
        config = types.GenerateContentConfig(
            temperature=generation_temperature,
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=ModernizedTextResponse,
        )
        for i, chunk in enumerate(chunks):
            if cancel_check and cancel_check():
                raise InterruptedError("User cancelled.")
            base_prog = 20 + int((i / len(chunks)) * 70)
            report(f"Modernizing chunk {i + 1}/{len(chunks)} via Gemini...", base_prog)
            while True:
                try:
                    response = _call_gemini_with_retries(
                        lambda: client.models.generate_content(
                            model=getattr(cfg, "gemini_model", "gemma-4-31b-it"),
                            contents=_build_user_prompt(chunk, profile, redo_context),
                            config=config,
                        ),
                        report,
                        base_prog,
                        cancel_check=cancel_check,
                    )
                    response_text = (response.text or "").strip()
                    try:
                        res_obj = ModernizedTextResponse.model_validate_json(response_text)
                        candidate = res_obj.modernized_text
                    except Exception:
                        candidate = _parse_modernization_output(response_text)
                    process_chunk_result(i, chunk, candidate)
                    break
                except RuntimeError as gemini_err:
                    err_text = str(gemini_err)
                    if "free-tier quota exhausted" in err_text:
                        raise
                    if "Gemini request failed after" in err_text and retry_decision_callback:
                        decision = retry_decision_callback({"chunk_index": i, "chunk_count": len(chunks), "error": err_text})
                        if decision == "retry":
                            report("Retrying Gemini for this modernization chunk by user request...", base_prog)
                            continue
                        process_chunk_result(i, chunk, "")
                        break
                    raise

    elif provider == "openai" and cfg.openai_api_key:
        client = OpenAI(api_key=cfg.openai_api_key)
        for i, chunk in enumerate(chunks):
            if cancel_check and cancel_check():
                raise InterruptedError("User cancelled.")
            base_prog = 20 + int((i / len(chunks)) * 70)
            report(f"Modernizing chunk {i + 1}/{len(chunks)} via OpenAI...", base_prog)
            response = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                temperature=generation_temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": _build_user_prompt(chunk, profile, redo_context)},
                ],
                response_format=ModernizedTextResponse,
            )
            res_obj = response.choices[0].message.parsed
            if res_obj is None:
                raise ValueError("OpenAI returned an empty modernization response.")
            process_chunk_result(i, chunk, res_obj.modernized_text)
    else:
        raise RuntimeError(f"Provider '{provider}' is not configured for text modernization.")

    fallback_count = sum(1 for chunk in evaluated_chunks if chunk.status == "fallback")
    final_doc = "\n\n".join(
        (chunk.variants[0]["accepted_text"] if chunk.variants else chunk.source_text)
        for chunk in evaluated_chunks
    )
    evaluation = TextModernizationEvaluation(
        provider=provider,
        profile=profile.id,
        chunk_count=len(evaluated_chunks),
        candidate_count=len(evaluated_chunks) - fallback_count,
        fallback_count=fallback_count,
        chunks=evaluated_chunks,
    )
    report("Modernization candidates ready.", 95)
    return final_doc, evaluation.model_dump()