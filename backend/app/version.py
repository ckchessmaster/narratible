import os
import sys
from pathlib import Path


def _read_version_file() -> str:
    if getattr(sys, "frozen", False):
        version_path = Path(sys.executable).with_name("app-version.txt")
    else:
        version_path = Path(__file__).resolve().parents[2] / "VERSION"

    try:
        return version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0-dev"


APP_VERSION = os.environ.get("NARRATIBLE_APP_VERSION", "").strip() or _read_version_file()