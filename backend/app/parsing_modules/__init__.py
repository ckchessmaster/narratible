"""Pluggable text-parsing modules.

A parsing module is an optional, deterministic text transformer applied per
chapter at parse time (after cleaning). Modules are registered in ``MODULES``
and selected per-project via the parse endpoint.
"""

from . import bible

# id -> module descriptor. ``transform`` is a callable ``str -> str``.
MODULES: dict[str, dict] = {
    "bible": {
        "id": "bible",
        "name": "Bible Reference Expander",
        "description": (
            "Expands abbreviated scripture book names so they are read "
            "correctly, e.g. 'Ps 1:4' becomes 'Psalms 1:4'."
        ),
        "transform": bible.transform,
    },
}


def list_modules() -> list[dict]:
    """Return module metadata (without the transform callable) for the API."""
    return [
        {"id": m["id"], "name": m["name"], "description": m["description"]}
        for m in MODULES.values()
    ]


def apply_modules(text: str, module_ids: list[str]) -> str:
    """Apply the enabled modules to ``text`` in registry order.

    Unknown ids are ignored so a stale client cannot break parsing.
    """
    if not module_ids:
        return text
    enabled = set(module_ids)
    for module_id, module in MODULES.items():
        if module_id in enabled:
            text = module["transform"](text)
    return text
