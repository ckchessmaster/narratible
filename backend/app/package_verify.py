import re
from pathlib import Path


def verify_packaged_frontend(frontend_dir: Path) -> str:
    """Return the active bundle name after verifying every TTS engine label."""
    index_path = frontend_dir / "index.html"
    index_html = index_path.read_text(encoding="utf-8")
    script_match = re.search(r'<script[^>]+src="([^"]+\.js)"', index_html)
    if script_match is None:
        raise RuntimeError("Packaged frontend index does not reference a JavaScript bundle.")

    script_path = frontend_dir / script_match.group(1).lstrip("/")
    script_text = script_path.read_text(encoding="utf-8")
    required_labels = ("Edge-TTS", "Kokoro-82M", "F5-TTS Clone", "Chatterbox Clone")
    missing_labels = [label for label in required_labels if label not in script_text]
    if missing_labels:
        raise RuntimeError(
            "Packaged frontend is missing TTS engines: " + ", ".join(missing_labels)
        )
    return script_path.name