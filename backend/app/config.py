import os
import json
from pydantic import BaseModel
from pathlib import Path

CONFIG_FILE = Path.home() / ".echo_scribe_config.json"

class AppConfig(BaseModel):
    gemini_api_key: str = ""
    openai_api_key: str = ""
    huggingface_token: str = ""
    embedded_llm_model: str = "HuggingFaceTB/SmolLM2-1.7B-Instruct"
    use_4bit_quantization: bool = False
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
