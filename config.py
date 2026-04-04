from dotenv import load_dotenv

load_dotenv()

import os
from pathlib import Path


def get_env(key: str, default: str) -> str:
    return os.environ.get(key, default)


BASE_DIR = Path.home() / "projects" / "roleplay-langgraph"

# Flask session signing. Set SECRET_KEY in the environment for production.
SECRET_KEY = get_env(
    "SECRET_KEY",
    "a77e91f4c2d08b3e6f5012345678abcd9012ef3456789012abcdef3456789012",
)

DATABASE_PATH = Path(get_env("DATABASE_PATH", str(BASE_DIR / "rpg.db")))

GAMES_DIR = Path(get_env("GAMES_DIR", str(BASE_DIR / "games")))
SESSIONS_DIR = Path(get_env("SESSIONS_DIR", str(BASE_DIR / "sessions")))
LOGS_DIR = Path(get_env("LOGS_DIR", str(BASE_DIR / "logs")))
FEEDBACK_DIR = Path(get_env("FEEDBACK_DIR", str(LOGS_DIR / "feedback")))

OLLAMA_HOST = get_env("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = get_env("DEFAULT_MODEL", "nchapman/mn-12b-mag-mell-r1:latest")
LLM_PROVIDER = get_env("LLM_PROVIDER", "ollama")

# Azure (used when LLM_PROVIDER=azure)
AZURE_ENDPOINT = get_env("AZURE_ENDPOINT", "")
AZURE_API_KEY = get_env("AZURE_API_KEY", "")
AZURE_DEPLOYMENT = get_env("AZURE_DEPLOYMENT", "gpt-4o-mini")
AZURE_API_VERSION = get_env("AZURE_API_VERSION", "2024-12-01-preview")

FLASK_HOST = get_env("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(get_env("FLASK_PORT", "5051"))
FLASK_DEBUG = get_env("FLASK_DEBUG", "false").lower() == "true"

HISTORY_LIMIT = int(get_env("HISTORY_LIMIT", "6"))
SAVE_SLOTS = int(get_env("SAVE_SLOTS", "5"))

INVENTORY_WEIGHT_LIMIT = int(get_env("INVENTORY_WEIGHT_LIMIT", "10"))

LOG_LEVEL = get_env("LOG_LEVEL", "INFO")


def ensure_dirs():
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)


ensure_dirs()
