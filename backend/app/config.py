import os
import sys
import json
from pydantic import BaseModel
from pathlib import Path

if getattr(sys, 'frozen', False):
    _app_data_dir = Path(os.environ.get('APPDATA', Path.home())) / "narratible"
    _app_data_dir.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE = _app_data_dir / "config.json"
else:
    CONFIG_FILE = Path.home() / ".narratible_config.json"

class AppConfig(BaseModel):
    llm_provider: str = "gemini"  # "gemini" | "openai" | "local" | "none"
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
    selected_gpu_index: int = 0  # -1 = CPU; 0, 1, 2... = CUDA device index

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

def get_device_string() -> str:
    """Return the torch device string based on the configured GPU selection."""
    cfg = load_config()
    idx = cfg.selected_gpu_index
    if idx < 0:
        return "cpu"
    return f"cuda:{idx}"


# Global settings instance
settings = load_config()
