"""
config.py — Centralised configuration loader for BiblioIA.

Reads all settings from environment variables (populated via .env).
Import this module first in every other module to guarantee variables are loaded.
"""
# NOTE : Les variables AGENT_LLM_* ont été supprimées (v2 — plus d'agent LangChain).

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from src/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


# ── LLM ───────────────────────────────────────────────────────────────────────

GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini").lower()
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
ENRICHMENT_LLM_MODEL: str = os.getenv("ENRICHMENT_LLM_MODEL", "gemini-2.0-flash")
ENRICHMENT_LLM_TEMPERATURE: float = float(os.getenv("ENRICHMENT_LLM_TEMPERATURE", "0.0"))

# ── Google Books API ──────────────────────────────────────────────────────────

# Optional: leave empty to use the unauthenticated quota (1 000 req/day)
GOOGLE_BOOKS_API_KEY: str = os.getenv("GOOGLE_BOOKS_API_KEY", "")
GOOGLE_BOOKS_BASE_URL: str = "https://www.googleapis.com/books/v1/volumes"

# ── Données ───────────────────────────────────────────────────────────────────

CSV_PATH: Path = Path(os.getenv("CSV_PATH", "data/goodreads_library_export.csv"))
if not CSV_PATH.is_absolute():
    CSV_PATH = _PROJECT_ROOT / CSV_PATH

# Bases de données SQLite
_db_catalogue = Path(os.getenv("CATALOGUE_DB_PATH", "data/catalogue.db"))
CATALOGUE_DB_PATH: Path = _db_catalogue if _db_catalogue.is_absolute() else _PROJECT_ROOT / _db_catalogue

_db_profile = Path(os.getenv("PROFILE_DB_PATH", "data/profile.db"))
PROFILE_DB_PATH: Path = _db_profile if _db_profile.is_absolute() else _PROJECT_ROOT / _db_profile

# Nombre max de livres par sujet Open Library (catalogue builder)
MAX_BOOKS_PER_SUBJECT: int = int(os.getenv("MAX_BOOKS_PER_SUBJECT", "500"))

# ── Paramètres de biais ───────────────────────────────────────────────────────

# Coefficient de décroissance exponentielle pour le biais de nouveauté.
# Plus λ est élevé, plus les livres anciens sont pénalisés.
RECENCY_DECAY_LAMBDA: float = float(os.getenv("RECENCY_DECAY_LAMBDA", "0.2"))

# Nombre d'années forcé pour les livres marqués avec le tag spécifique (ex: "older_books")
OLDER_BOOKS_YEARS_AGO: int = int(os.getenv("OLDER_BOOKS_YEARS_AGO", "10"))
OLDER_BOOKS_TAG: str = os.getenv("OLDER_BOOKS_TAG", "older_books")

# ── Performance fonctionnelle / ranking ──────────────────────────────────────

# Facteur de bonus appliqué aux tags les plus représentatifs.
# 0.0 = pas de bonus, 1.0 = bonus maximal.
TOP_TAG_BOOST_FACTOR: float = float(os.getenv("TOP_TAG_BOOST_FACTOR", "0.35"))

# Nombre de tags les plus importants utilisés pour le bonus de pertinence.
TOP_TAG_COUNT: int = int(os.getenv("TOP_TAG_COUNT", "8"))

# ── Enrichissement ────────────────────────────────────────────────────────────

# Réenrichir les lignes "Non classifié"/"Erreur LLM" à chaque exécution.
FORCE_REFRESH_UNCLASSIFIED: bool = os.getenv("FORCE_REFRESH_UNCLASSIFIED", "true").lower() == "true"

# Nombre de workers pour l'enrichissement concurrent.
# Défaut : 2 workers (adapté au Raspberry Pi — IO-bound, pas CPU-bound)
ENRICHMENT_MAX_WORKERS: int = int(os.getenv("ENRICHMENT_MAX_WORKERS", "2"))

# Sauvegarde d'étape après N livres traités.
ENRICHMENT_SAVE_EVERY: int = int(os.getenv("ENRICHMENT_SAVE_EVERY", "50"))

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

# ── Noosfere Scraper ───────────────────────────────────────────────────────────

# Délai entre les requêtes HTTP (en secondes) - généreux pour respecter le site
NOOSFERE_BASE_DELAY: float = float(os.getenv("NOOSFERE_BASE_DELAY", "2.0"))
NOOSFERE_MAX_RETRIES: int = int(os.getenv("NOOSFERE_MAX_RETRIES", "3"))

# Base de données de la file d'attente de scraping
_SCRAPING_QUEUE = Path(os.getenv("SCRAPING_QUEUE_DB_PATH", "data/scraping_queue.db"))
SCRAPING_QUEUE_DB_PATH: Path = _SCRAPING_QUEUE if _SCRAPING_QUEUE.is_absolute() else _PROJECT_ROOT / _SCRAPING_QUEUE
