import re
from dataclasses import dataclass
from typing import Any

from .config import AppConfig, load_config


PLACEHOLDER_RE = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    label: str
    description: str
    base_prompt: str
    required_variables: tuple[str, ...] = ()


PROMPT_TEMPLATES: dict[str, PromptTemplate] = {
    "metadata_system": PromptTemplate(
        id="metadata_system",
        label="Metadata extraction - system",
        description="Sets the role and JSON contract for front-matter metadata extraction.",
        required_variables=(),
        base_prompt=(
            "You extract book metadata from noisy front matter. "
            "Return only JSON with keys: title, author, language, description, "
            "publisher, subject, isbn, series. Use empty strings when unknown."
        ),
    ),
    "metadata_user": PromptTemplate(
        id="metadata_user",
        label="Metadata extraction - user",
        description="Supplies PDF metadata heuristics and front-matter text to the LLM.",
        required_variables=("heuristics_json", "front_matter_text"),
        base_prompt=(
            "Heuristic metadata from PDF info fields:\n"
            "{{heuristics_json}}\n\n"
            "Front matter text (may include title pages, copyright, and TOC):\n"
            "{{front_matter_text}}"
        ),
    ),
    "chapter_review_system": PromptTemplate(
        id="chapter_review_system",
        label="Chapter review - system",
        description="Defines how candidate chapter boundaries should be reviewed.",
        required_variables=(),
        base_prompt=(
            "You are reviewing chapter boundaries detected in a PDF book by a visual heuristic. "
            "Your job is to classify each candidate, correct malformed titles (OCR artifacts), and "
            "reconstruct full titles that the heuristic truncated. Do not add or split chapters."
        ),
    ),
    "chapter_review_user": PromptTemplate(
        id="chapter_review_user",
        label="Chapter review - user",
        description="Provides candidate chapters, lead-in snippets, and the JSON response format.",
        required_variables=("reference_block", "chapter_list"),
        base_prompt=(
            "Review the candidate chapters below. Each entry may include a [before: \"...\"] lead-in "
            "showing the end of the previous candidate, to help you judge the break.\n\n"
            "For each entry, set section_type to one of:\n"
            "  - \"front_matter\" - cover, title page, copyright, dedication, contents, preface/foreword "
            "BEFORE the first real chapter.\n"
            "  - \"chapter\" - a genuine body chapter.\n"
            "  - \"back_matter\" - notes, bibliography, indexes (scripture/person/subject), appendices "
            "AFTER the last real chapter.\n"
            "  - \"continuation\" - a FALSE chapter break (stray subheading, running footer, or "
            "page-number artifact) that belongs to the PRECEDING entry. The FIRST entry must never be "
            "\"continuation\".\n\n"
            "Also: correct any title that is an OCR artifact (e.g. letter-spaced 'G O D' -> 'GOD') and "
            "restore the full title when it was truncated (e.g. 'Delight?' -> the complete chapter title), "
            "using the reference table of contents and lead-in context where available.\n"
            "Do NOT add chapters or split existing ones.\n\n"
            "{{reference_block}}"
            "Candidates:\n{{chapter_list}}\n\n"
            "Return ONLY valid JSON in this exact format: "
            "{\"chapters\": [{\"title\": \"...\", \"section_type\": \"chapter\", \"note\": null}]}"
        ),
    ),
    "cleanup_system": PromptTemplate(
        id="cleanup_system",
        label="Text cleanup - system",
        description="Sets strict preservation behavior for LLM cleanup.",
        required_variables=("profile_guidance",),
        base_prompt=(
            "You are a strict text editor. NEVER output conversational filler or preamble. "
            "Output ONLY the intended text formatting, no analysis. Fix fragmented OCR characters into proper words. "
            "Never omit, truncate, or summarize text. "
            "Profile guidance: {{profile_guidance}}"
        ),
    ),
    "cleanup_user_streaming": PromptTemplate(
        id="cleanup_user_streaming",
        label="Text cleanup - streaming/XML user",
        description="Used by local LLM cleanup and Gemini streaming so progress is readable.",
        required_variables=("profile_label", "profile_guidance", "chunk_text"),
        base_prompt=(
            "Please clean the following text extracted from a PDF. It has already had basic line breaks fixed. "
            "Cleaning profile: {{profile_label}}. {{profile_guidance}}\n"
            "Your instructions:\n"
            "1. Output the cleaned main text inside <text>...</text> tags.\n"
            "2. Identify any footnotes and margin notes, and output them inside <notes>...</notes> tags.\n"
            "3. Strip entirely any running headers, footers, and floating page numbers.\n"
            "4. Preserve epigraph, poetry, scripture, and source attribution lines such as 'C. S. LEWIS', 'Till We Have Faces', 'PSALM 63:1', and spaced OCR forms like 'P S A L M 6 3 : 1'. Do not treat them as headers/footers.\n"
            "5. Fix OCR errors: Reconstruct mangled or fragmented words (e.g., 'T E R T U L L I A N' -> 'TERTULLIAN'). Correct obvious typos caused by bad scanning.\n"
            "6. Format all major structural headings (e.g., Chapters, Prefaces, Introductions, Prologues, Epilogues) by prefixing them with a Markdown '# ' (e.g., '# Chapter 1', '# Introduction').\n"
            "7. NEVER include any conversational preamble, summary, or analysis. DO NOT output 'Here is the cleaned text'.\n"
            "8. DO NOT omit, summarize, or truncate any text. Do not use placeholders like '...(rest of text)'. You MUST output the full text unaltered except for the requested formatting.\n\n"
            "Here is the text:\n\n"
            "{{chunk_text}}"
        ),
    ),
    "cleanup_user_structured": PromptTemplate(
        id="cleanup_user_structured",
        label="Text cleanup - structured user",
        description="Used by JSON-mode Gemini/OpenAI cleanup.",
        required_variables=("profile_label", "profile_guidance", "chunk_text"),
        base_prompt=(
            "Please clean the following text extracted from a PDF. Ensure basic line breaks are fixed. "
            "Cleaning profile: {{profile_label}}. {{profile_guidance}}\n"
            "Output the cleaned text into `main_text`. Output any footnotes/margin notes into `notes_text`. "
            "Strip running headers/footers/page numbers, but preserve epigraph, poetry, scripture, and source attribution lines such as 'C. S. LEWIS', 'Till We Have Faces', 'PSALM 63:1', and spaced OCR forms like 'P S A L M 6 3 : 1'.\n"
            "Fix OCR errors: Reconstruct mangled or fragmented words (e.g., 'T E R T U L L I A N' -> 'TERTULLIAN'). Catch obvious spelling errors.\n\n"
            "Here is the text:\n\n"
            "{{chunk_text}}"
        ),
    ),
    "modernization_system": PromptTemplate(
        id="modernization_system",
        label="Modernization - system",
        description="Sets preservation rules for modern-language candidates.",
        required_variables=("profile_guidance",),
        base_prompt=(
            "You modernize difficult older text for present-day readers while preserving original meaning. "
            "Never summarize, omit, add interpretation, or change the author's claims. "
            "Preserve every source paragraph, names, numbers, sequence, quotations, speaker intent, theological/legal/technical terms, and paragraph order. "
            "Profile guidance: {{profile_guidance}}"
        ),
    ),
    "modernization_user": PromptTemplate(
        id="modernization_user",
        label="Modernization - user",
        description="Supplies the passage, profile, and optional redo context for modernization.",
        required_variables=("profile_label", "profile_guidance", "redo_block", "chunk_text"),
        base_prompt=(
            "Modernize the following passage into clear present-day English while preserving its meaning. "
            "Modernization profile: {{profile_label}}. {{profile_guidance}}\n"
            "{{redo_block}}"
            "Output only the modernized passage in <text>...</text> tags. "
            "Do not include a preamble, analysis, notes, summaries, or placeholders. "
            "Do not drop or combine away a paragraph; each source paragraph must be represented in order.\n\n"
            "Passage:\n\n"
            "{{chunk_text}}"
        ),
    ),
}


def _placeholder_names(template_text: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(template_text or ""))


def validate_prompt_template(prompt_id: str, template_text: str) -> None:
    prompt = PROMPT_TEMPLATES.get(prompt_id)
    if prompt is None:
        raise ValueError(f"Unknown custom prompt id: {prompt_id}")
    placeholders = _placeholder_names(template_text)
    unknown = sorted(placeholders - set(prompt.required_variables))
    if unknown:
        raise ValueError(f"{prompt.label} contains unknown placeholder(s): {', '.join(unknown)}")
    missing = [name for name in prompt.required_variables if name not in placeholders]
    if missing:
        raise ValueError(f"{prompt.label} is missing required placeholder(s): {', '.join(missing)}")


def validate_prompt_overrides(overrides: dict[str, str] | None) -> None:
    for prompt_id, template_text in (overrides or {}).items():
        validate_prompt_template(prompt_id, template_text)


def list_custom_prompt_templates(config: AppConfig | None = None) -> list[dict[str, Any]]:
    cfg = config or load_config()
    overrides = cfg.custom_prompt_overrides or {}
    return [
        {
            "id": prompt.id,
            "label": prompt.label,
            "description": prompt.description,
            "base_prompt": prompt.base_prompt,
            "prompt": overrides.get(prompt.id, prompt.base_prompt),
            "required_variables": list(prompt.required_variables),
            "customized": prompt.id in overrides,
        }
        for prompt in PROMPT_TEMPLATES.values()
    ]


def render_prompt(prompt_id: str, **values: Any) -> str:
    prompt = PROMPT_TEMPLATES.get(prompt_id)
    if prompt is None:
        raise ValueError(f"Unknown prompt id: {prompt_id}")

    cfg = load_config()
    template_text = prompt.base_prompt
    if cfg.custom_instructions_enabled:
        template_text = (cfg.custom_prompt_overrides or {}).get(prompt_id, prompt.base_prompt)
        validate_prompt_template(prompt_id, template_text)

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise ValueError(f"Missing prompt value for placeholder: {name}")
        value = values[name]
        return "" if value is None else str(value)

    return PLACEHOLDER_RE.sub(replace, template_text)
