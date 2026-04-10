"""
preprocessing.py — Pipeline de nettoyage et de correction des biais pour BiblioIA.

Règles métier implémentées :
1. Chargement et nettoyage robuste du CSV Goodreads.
2. Règle "older_books" : force l'année de lecture à il y a ≥ 10 ans.
3. Correction du biais de nouveauté : lissage par année (adapté aux ajouts par lots).
"""

from __future__ import annotations

import logging
import math
from datetime import date
from pathlib import Path
from typing import Final

import pandas as pd

from config import CSV_PATH, OLDER_BOOKS_TAG, OLDER_BOOKS_YEARS_AGO, RECENCY_DECAY_LAMBDA
from enrichment import enrich_dataframe_with_genres

logger = logging.getLogger(__name__)

_USEFUL_COLUMNS: Final[list[str]] = [
    "Book Id",
    "Title",
    "Author",
    "Additional Authors",
    "ISBN",
    "ISBN13",
    "Publisher",
    "Binding",
    "Number of Pages",
    "Year Published",
    "Date Read",
    "Date Added",
    "Bookshelves",
    "Exclusive Shelf",
    "Read Count",
    "Micro-genre",
]

# ─────────────────────────────────────────────────────────────────────────────
# Chargement et Nettoyage de base
# ─────────────────────────────────────────────────────────────────────────────

def load_csv(csv_path: Path | str | None = None) -> pd.DataFrame:
    """Charge le CSV Goodreads et retourne un DataFrame brut."""
    path = Path(csv_path) if csv_path else CSV_PATH
    if not path.exists():
        raise FileNotFoundError(f"Fichier CSV introuvable : {path}")

    logger.info("Chargement du CSV : %s", path)
    df = pd.read_csv(path, dtype=str, encoding="utf-8")

    # S'assurer que la colonne Micro-genre existe (même si vide) avant le filtrage
    if "Micro-genre" not in df.columns:
        df["Micro-genre"] = ""

    missing_cols = [c for c in _USEFUL_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Colonnes manquantes dans le CSV : {missing_cols}")

    return df[_USEFUL_COLUMNS].copy()


def _parse_dates_to_years(df: pd.DataFrame) -> pd.DataFrame:
    """Extrait l'année de lecture pour s'affranchir du bruit des jours/mois."""
    for col in ("Date Read", "Date Added"):
        df[col] = pd.to_datetime(df[col], format="%Y/%m/%d", errors="coerce")
    
    # On crée une colonne unifiée "action_year". 
    # Priorité à l'année de lecture, sinon année d'ajout, sinon l'année en cours.
    current_year = date.today().year
    df["action_year"] = df["Date Read"].dt.year.fillna(df["Date Added"].dt.year).fillna(current_year)
    return df


def _filter_read_books(df: pd.DataFrame) -> pd.DataFrame:
    """Ne conserve que les livres marqués comme lus."""
    before = len(df)
    df = df[df["Exclusive Shelf"].str.strip().str.lower() == "read"].copy()
    logger.info("Filtrage 'read' : %d → %d livres", before, len(df))
    return df


def _clean_text_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip les espaces superflus sur les colonnes texte principales."""
    text_cols = ["Title", "Author", "Bookshelves", "Micro-genre"]
    for col in text_cols:
        df[col] = df[col].astype(str).str.strip()
    return df

# ─────────────────────────────────────────────────────────────────────────────
# Application des Règles Métier
# ─────────────────────────────────────────────────────────────────────────────

def apply_older_books_rule(df: pd.DataFrame) -> pd.DataFrame:
    """Force l'année d'action des livres marqués à il y a au moins N ans."""
    current_year = date.today().year
    older_max_year = current_year - OLDER_BOOKS_YEARS_AGO

    mask = df["Bookshelves"].str.contains(OLDER_BOOKS_TAG, case=False, na=False)
    count = mask.sum()

    if count > 0:
        logger.info("Règle older_books : %d livre(s) plafonné(s) à l'année %d.", count, older_max_year)
        df.loc[mask, "action_year"] = df.loc[mask, "action_year"].clip(upper=older_max_year)

    return df


def apply_author_bias_correction(df: pd.DataFrame) -> pd.DataFrame:
    """Neutralise le biais de série/auteur.
    
    Si Robin Hobb a 15 livres dans le CSV, chaque livre pèse 1/15.
    Ainsi, l'intégralité de son oeuvre pèse l'équivalent d'un seul auteur.
    """
    author_counts = df["Author"].value_counts()

    def _calculate_author_weight(author: str) -> float:
        if not author or author.lower() == "nan":
            return 1.0
        return 1.0 / author_counts.get(author, 1)

    df["author_weight"] = df["Author"].apply(_calculate_author_weight)
    
    logger.info("Biais d'auteur corrigé. Poids moyen calculé : %.3f", df["author_weight"].mean())
    return df


def apply_recency_bias_correction(df: pd.DataFrame) -> pd.DataFrame:
    """Applique une décroissance basée sur les années (lisse les batchs)."""
    current_year = date.today().year
    df["years_since_read"] = current_year - df["action_year"]

    def _recency(years_ago: float) -> float:
        if math.isnan(years_ago) or years_ago < 0:
            years_ago = 0
        return math.exp(-RECENCY_DECAY_LAMBDA * years_ago)

    df["recency_weight"] = df["years_since_read"].apply(_recency)
    logger.info("Biais nouveauté corrigé par année. Poids moyen : %.3f", df["recency_weight"].mean())
    return df


def compute_bias_corrected_score(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule le score final combinant le biais d'auteur et de nouveauté."""
    raw_score = df["author_weight"] * df["recency_weight"]

    # Normalisation min-max
    score_min, score_max = raw_score.min(), raw_score.max()
    if score_max > score_min:
        df["bias_corrected_score"] = (raw_score - score_min) / (score_max - score_min)
    else:
        df["bias_corrected_score"] = 0.5 

    logger.info("Score pondéré calculé. Moyenne : %.3f", df["bias_corrected_score"].mean())
    return df

# ─────────────────────────────────────────────────────────────────────────────
# Point d'entrée public
# ─────────────────────────────────────────────────────────────────────────────

def load_and_prepare(csv_path: Path | str | None = None) -> pd.DataFrame:
    """Pipeline complet : charge, nettoie et corrige les biais."""
    df = load_csv(csv_path)
    df = _filter_read_books(df)
    df = _clean_text_columns(df)
    
    # Enrichissement avec OpenLibrary (ajoute/remplit 'Micro-genre')
    df = enrich_dataframe_with_genres(df)
    
    # Transformations temporelles et biais
    df = _parse_dates_to_years(df)
    df = apply_older_books_rule(df)
    df = apply_author_bias_correction(df)
    df = apply_recency_bias_correction(df)
    df = compute_bias_corrected_score(df)
    
    df = df.reset_index(drop=True)
    df = df.fillna("")
    logger.info("Pipeline terminé. %d livres prêts pour l'Agent.", len(df))
    return df