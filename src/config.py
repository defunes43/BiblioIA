"""
config.py — Centralised configuration loader for BiblioIA.

Reads all settings from environment variables (populated via .env).
Import this module first in every other module to guarantee variables are loaded.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from src/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


# ── LLM ───────────────────────────────────────────────────────────────────────

GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
ENRICHMENT_LLM_MODEL: str = os.getenv("ENRICHMENT_LLM_MODEL", "gemini-2.0-flash")
ENRICHMENT_LLM_TEMPERATURE: float = float(os.getenv("ENRICHMENT_LLM_TEMPERATURE", "0.0"))

AGENT_LLM_MODEL: str = os.getenv("AGENT_LLM_MODEL", "gemini-1.5-pro")
AGENT_LLM_TEMPERATURE: float = float(os.getenv("AGENT_LLM_TEMPERATURE", "0.7"))

# ── Google Books API ──────────────────────────────────────────────────────────

# Optional: leave empty to use the unauthenticated quota (1 000 req/day)
GOOGLE_BOOKS_API_KEY: str = os.getenv("GOOGLE_BOOKS_API_KEY", "")
GOOGLE_BOOKS_BASE_URL: str = "https://www.googleapis.com/books/v1/volumes"

# ── Données ───────────────────────────────────────────────────────────────────

CSV_PATH: Path = Path(os.getenv("CSV_PATH", "data/goodreads_library_export.csv"))
if not CSV_PATH.is_absolute():
    CSV_PATH = _PROJECT_ROOT / CSV_PATH

# ── Paramètres de biais ───────────────────────────────────────────────────────

# Coefficient de décroissance exponentielle pour le biais de nouveauté.
# Plus λ est élevé, plus les livres anciens sont pénalisés.
RECENCY_DECAY_LAMBDA: float = float(os.getenv("RECENCY_DECAY_LAMBDA", "0.2"))

# Nombre d'années forcé pour les livres marqués avec le tag spécifique (ex: "older_books")
OLDER_BOOKS_YEARS_AGO: int = int(os.getenv("OLDER_BOOKS_YEARS_AGO", "10"))
OLDER_BOOKS_TAG: str = os.getenv("OLDER_BOOKS_TAG", "older_books")

# ── Validation ────────────────────────────────────────────────────────────────

def validate() -> None:
    """Raise EnvironmentError if critical variables are missing."""
    missing: list[str] = []
    if not GOOGLE_API_KEY:
        missing.append("GOOGLE_API_KEY")
    if missing:
        raise EnvironmentError(
            f"Variables d'environnement manquantes : {', '.join(missing)}\n"
            "Copie .env.example vers .env et remplis les valeurs requises."
        )
