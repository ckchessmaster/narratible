"""Pluggable text-parsing modules.

A parsing module is an optional, deterministic text transformer applied per
chapter at parse time (after cleaning). Modules are registered in ``MODULES``
and selected per-project via the parse endpoint.
"""

from . import bible, prose_reflow
from ..notes import EXTENDED_NOTE_DETECTION_MODULE_ID

MODERNIZATION_MODULE_ID = "modernize_text"

# id -> module descriptor. ``transform`` is a callable ``str -> str``.
# ``tts_transform`` is optional and receives ``(text, engine)``.
MODULES: dict[str, dict] = {
    "prose_reflow": {
        "id": "prose_reflow",
        "name": "Prose Reflow",
        "description": (
            "Joins PDF-wrapped prose lines while preserving likely verse, "
            "lists, citations, and epigraph attributions."
        ),
        "transform": prose_reflow.transform,
    },
    "bible": {
        "id": "bible",
        "name": "Bible Reference Expander",
        "description": (
            "Expands abbreviated scripture book names so they are read "
            "correctly, e.g. 'Ps 1:4' becomes 'Psalms 1:4'."
        ),
        "transform": bible.transform,
        "tts_transform": bible.tts_transform,
    },
    EXTENDED_NOTE_DETECTION_MODULE_ID: {
        "id": EXTENDED_NOTE_DETECTION_MODULE_ID,
        "name": "Extended Note Detection",
        "description": (
            "Uses PDF layout geometry to strip margin notes and collect them with "
            "footnotes for optional EPUB export. Audio never includes collected notes."
        ),
        "kind": "layout_detection",
        "warning": "Best for scholarly or messy scans; review extracted text when page margins contain real prose.",
    },
    MODERNIZATION_MODULE_ID: {
        "id": MODERNIZATION_MODULE_ID,
        "name": "Text Modernization",
        "description": (
            "Uses an LLM to create reviewable modern-language candidates for older, "
            "hard-to-read prose while preserving meaning."
        ),
        "kind": "llm_modernization",
        "requires_llm": True,
        "warning": "Slower and less predictable than deterministic enhancements. Review candidates before TTS or export.",
        "profiles_endpoint": "/api/modernization-profiles",
    },
}


def list_modules() -> list[dict]:
    """Return module metadata (without the transform callable) for the API."""
    return [
        {key: value for key, value in m.items() if key not in {"transform", "tts_transform"}}
        for m in MODULES.values()
    ]


def normalize_module_ids(module_ids: list[str] | None) -> list[str]:
    """Return known module ids in registry order, dropping stale/unknown ids."""
    if not module_ids:
        return []
    enabled = set(module_ids)
    return [module_id for module_id in MODULES if module_id in enabled]


def apply_modules(text: str, module_ids: list[str]) -> str:
    """Apply the enabled modules to ``text`` in registry order.

    Unknown ids are ignored so a stale client cannot break parsing.
    """
    if not module_ids:
        return text
    for module_id in normalize_module_ids(module_ids):
        module = MODULES[module_id]
        if module.get("transform"):
            text = module["transform"](text)
    return text


def apply_tts_modules(text: str, module_ids: list[str] | None, engine: str) -> str:
    """Apply enabled modules' audio-only transforms in registry order."""
    for module_id in normalize_module_ids(module_ids):
        tts_transform = MODULES[module_id].get("tts_transform")
        if tts_transform:
            text = tts_transform(text, engine)
    return text
