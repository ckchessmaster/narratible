import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtime_state import RUNTIME_DIR

TOKENS_FILE = RUNTIME_DIR / "mcp_tokens.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_raw_tokens() -> list[dict[str, Any]]:
    if not TOKENS_FILE.exists():
        return []
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_raw_tokens(tokens: list[dict[str, Any]]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = TOKENS_FILE.with_name(f"{TOKENS_FILE.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, TOKENS_FILE)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


def generate_pat(name: str) -> tuple[dict[str, Any], str]:
    cleaned_name = name.strip() or "Default Token"
    raw_token = f"ntb_{secrets.token_hex(24)}"
    token_hash = hash_token(raw_token)
    token_id = secrets.token_hex(8)
    prefix = f"{raw_token[:8]}...{raw_token[-4:]}"

    record = {
        "id": token_id,
        "name": cleaned_name,
        "prefix": prefix,
        "token_hash": token_hash,
        "created_at": _utc_now(),
        "last_used_at": None,
    }

    tokens = _load_raw_tokens()
    tokens.append(record)
    _save_raw_tokens(tokens)

    safe_record = {k: v for k, v in record.items() if k != "token_hash"}
    return safe_record, raw_token


def list_tokens() -> list[dict[str, Any]]:
    tokens = _load_raw_tokens()
    return [{k: v for k, v in t.items() if k != "token_hash"} for t in tokens]


def revoke_token(token_id: str) -> bool:
    tokens = _load_raw_tokens()
    new_tokens = [t for t in tokens if t.get("id") != token_id]
    if len(new_tokens) != len(tokens):
        _save_raw_tokens(new_tokens)
        return True
    return False


def validate_token(raw_token: str) -> bool:
    if not raw_token or not isinstance(raw_token, str):
        return False
    target_hash = hash_token(raw_token)
    tokens = _load_raw_tokens()
    matched = False
    for t in tokens:
        if secrets.compare_digest(t.get("token_hash", ""), target_hash):
            t["last_used_at"] = _utc_now()
            matched = True
            break
    if matched:
        try:
            _save_raw_tokens(tokens)
        except Exception:
            pass
        return True
    return False
