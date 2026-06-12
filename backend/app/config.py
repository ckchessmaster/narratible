import os
import sys
import json
from pydantic import BaseModel
from pathlib import Path

if getattr(sys, 'frozen', False):
    _app_data_dir = Path(os.environ.get('APPDATA', Path.home())) / "EchoScribe"
    _app_data_dir.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE = _app_data_dir / "config.json"
else:
    CONFIG_FILE = Path.home() / ".echo_scribe_config.json"

class AppConfig(BaseModel):
    gemini_api_key: str = ""
    gemini_model: str = "gemma-4-31b-it"
    openai_api_key: str = ""
    huggingface_token: str = ""
    embedded_llm_model: str = "google/gemma-4-E2B-it"
    use_4bit_quantization: bool = False
    llm_chunk_size: int = 5000
    cloud_llm_chunk_size: int = 50000
    llm_temperature: float = 0.1
    audiobookshelf_url: str = ""
    audiobookshelf_token: str = ""
    default_tts_engine: str = "edge-tts"

def load_config() -> AppConfig:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return AppConfig(**data)
            except Exception:
                pass
    return AppConfig()

def save_config(config: AppConfig):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, indent=4)

# Global settings instance
settings = load_config()
