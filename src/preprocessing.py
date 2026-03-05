"""
preprocessing.py — Pipeline de nettoyage et de correction des biais pour BiblioIA.

Règles métier implémentées :
1. Chargement et nettoyage robuste du CSV Goodreads.
2. Règle "arsac" : force la date de lecture à il y a ≥ 10 ans.
3. Correction du biais de série / auteur (pondération inverse du volume).
4. Correction du biais de nouveauté (décroissance exponentielle temporelle).
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Final

import pandas as pd

from config import ARSAC_YEARS_AGO, CSV_PATH, RECENCY_DECAY_LAMBDA

logger = logging.getLogger(__name__)

# Colonnes conservées après le chargement initial
_USEFUL_COLUMNS: Final[list[str]] = [
    "Book Id",
    "Title",
    "Author",
    "Additional Authors",
    "ISBN",
    "ISBN13",
    "My Rating",
    "Average Rating",
    "Publisher",
    "Binding",
    "Number of Pages",
    "Year Published",
    "Original Publication Year",
    "Date Read",
    "Date Added",
    "Bookshelves",
    "Exclusive Shelf",
    "My Review",
    "Read Count",
]

# Valeur sentinelle pour la correction "arsac"
_ARSAC_KEYWORD: Final[str] = "arsac"


# ─────────────────────────────────────────────────────────────────────────────
# Chargement
# ─────────────────────────────────────────────────────────────────────────────


def load_csv(csv_path: Path | str | None = None) -> pd.DataFrame:
    """Charge le CSV Goodreads et retourne un DataFrame brut.

    Args:
        csv_path: Chemin vers le fichier CSV. Utilise ``CSV_PATH`` si None.

    Returns:
        DataFrame brut avec uniquement les colonnes utiles.

    Raises:
        FileNotFoundError: Si le fichier CSV est introuvable.
        ValueError: Si des colonnes obligatoires sont absentes.
    """
    path = Path(csv_path) if csv_path else CSV_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Fichier CSV introuvable : {path}\n"
            "Place ton export Goodreads dans le dossier data/ ou ajuste CSV_PATH dans .env."
        )

    logger.info("Chargement du CSV : %s", path)
    df = pd.read_csv(path, dtype=str, encoding="utf-8")

    # Vérifie les colonnes obligatoires
    missing_cols = [c for c in _USEFUL_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Colonnes manquantes dans le CSV : {missing_cols}")

    return df[_USEFUL_COLUMNS].copy()


# ─────────────────────────────────────────────────────────────────────────────
# Nettoyage de base
# ─────────────────────────────────────────────────────────────────────────────


def _parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Parse les colonnes de date en datetime, les erreurs → NaT."""
    for col in ("Date Read", "Date Added"):
        df[col] = pd.to_datetime(df[col], format="%Y/%m/%d", errors="coerce")
    return df


def _parse_numerics(df: pd.DataFrame) -> pd.DataFrame:
    """Convertit les colonnes numériques, remplace les zéros de notation par NaN."""
    for col in ("My Rating", "Average Rating", "Number of Pages", "Read Count"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Note de 0 = "non noté" dans Goodreads, pas une vraie note
    df["My Rating"] = df["My Rating"].replace(0, float("nan"))
    return df


def _filter_read_books(df: pd.DataFrame) -> pd.DataFrame:
    """Ne conserve que les livres marqués comme lus (Exclusive Shelf == 'read')."""
    before = len(df)
    df = df[df["Exclusive Shelf"].str.strip().str.lower() == "read"].copy()
    logger.info("Filtrage 'read' : %d → %d livres", before, len(df))
    return df


def _clean_text_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip les espaces superflus sur les colonnes texte."""
    text_cols = ["Title", "Author", "Bookshelves", "Publisher", "Binding"]
    for col in text_cols:
        df[col] = df[col].astype(str).str.strip()
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Règle métier 1 – "arsac" (temporalité forcée)
# ─────────────────────────────────────────────────────────────────────────────


def apply_arsac_rule(df: pd.DataFrame) -> pd.DataFrame:
    """Force la date de lecture des livres "arsac" à il y a au moins N ans.

    Si la colonne ``Bookshelves`` contient le mot-clé ``"arsac"``, la valeur
    ``Date Read`` est remplacée par ``today - ARSAC_YEARS_AGO years``
    (ou conservée si elle est déjà plus ancienne).

    Args:
        df: DataFrame nettoyé avec la colonne ``Date Read`` parsée en datetime.

    Returns:
        DataFrame avec la règle arsac appliquée.
    """
    arsac_cutoff: pd.Timestamp = pd.Timestamp(
        date.today() - timedelta(days=365 * ARSAC_YEARS_AGO)
    )

    arsac_mask = df["Bookshelves"].str.contains(_ARSAC_KEYWORD, case=False, na=False)
    count_arsac = arsac_mask.sum()

    if count_arsac == 0:
        logger.info("Règle arsac : aucun livre concerné.")
        return df

    logger.info("Règle arsac : %d livre(s) concerné(s).", count_arsac)

    # Pour les lignes arsac, on prend le MIN entre la date existante et la coupure
    # (si Date Read est NaT ou plus récente que la coupure → on force la coupure)
    def _force_arsac_date(row: pd.Series) -> pd.Timestamp:
        existing = row["Date Read"]
        if pd.isna(existing) or existing > arsac_cutoff:
            return arsac_cutoff
        return existing  # déjà assez ancienne, on conserve

    df.loc[arsac_mask, "Date Read"] = df.loc[arsac_mask].apply(
        _force_arsac_date, axis=1
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Règle métier 2 – Biais de série / auteur
# ─────────────────────────────────────────────────────────────────────────────


def apply_author_bias_correction(df: pd.DataFrame) -> pd.DataFrame:
    """Pondère chaque livre par l'inverse du nombre de livres lus du même auteur.

    Un auteur avec 20 livres lus reçoit un poids de 1/20 par livre,
    évitant qu'il n'écrase les auteurs moins prolifiques dans le profil.

    Args:
        df: DataFrame nettoyé.

    Returns:
        DataFrame avec la colonne ``author_weight`` ajoutée (0 < weight ≤ 1).
    """
    author_counts = df.groupby("Author")["Book Id"].transform("count")
    df["author_weight"] = 1.0 / author_counts
    logger.info(
        "Biais auteur corrigé. Poid moyen : %.3f", df["author_weight"].mean()
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Règle métier 3 – Biais de nouveauté
# ─────────────────────────────────────────────────────────────────────────────


def apply_recency_bias_correction(df: pd.DataFrame) -> pd.DataFrame:
    """Applique une décroissance exponentielle selon l'ancienneté de lecture.

    ``recency_weight = exp(-λ × years_since_read)``

    Les livres sans date de lecture reçoivent un poids neutre de 0.5.

    Args:
        df: DataFrame avec ``Date Read`` parsée.

    Returns:
        DataFrame avec les colonnes ``days_since_read`` et ``recency_weight``.
    """
    today = pd.Timestamp(date.today())
    df["days_since_read"] = (today - df["Date Read"]).dt.days

    def _recency(days: float) -> float:
        if math.isnan(days):
            return 0.5  # poids neutre pour les dates absentes
        years = days / 365.25
        return math.exp(-RECENCY_DECAY_LAMBDA * years)

    df["recency_weight"] = df["days_since_read"].apply(_recency)
    logger.info(
        "Biais nouveauté corrigé. Poids moyen : %.3f", df["recency_weight"].mean()
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Score global pondéré
# ─────────────────────────────────────────────────────────────────────────────


def compute_bias_corrected_score(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule le score final combinant note, biais auteur et biais nouveauté.

    ``bias_corrected_score = My Rating × author_weight × recency_weight``

    Le score est ensuite normalisé entre 0 et 1 (min-max).
    Les livres sans note reçoivent ``Average Rating`` comme substitut.

    Args:
        df: DataFrame avec ``author_weight``, ``recency_weight`` et ``My Rating``.

    Returns:
        DataFrame avec la colonne ``bias_corrected_score`` (0–1).
    """
    # Substitut : si pas de note personnelle, utilise la note moyenne Goodreads
    rating = df["My Rating"].fillna(df["Average Rating"])

    raw_score = rating * df["author_weight"] * df["recency_weight"]

    score_min = raw_score.min()
    score_max = raw_score.max()
    if score_max > score_min:
        df["bias_corrected_score"] = (raw_score - score_min) / (score_max - score_min)
    else:
        df["bias_corrected_score"] = 0.5  # tous identiques

    logger.info(
        "Score pondéré calculé. Moyenne : %.3f | Max : %.3f",
        df["bias_corrected_score"].mean(),
        df["bias_corrected_score"].max(),
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entrée public
# ─────────────────────────────────────────────────────────────────────────────


def load_and_prepare(csv_path: Path | str | None = None) -> pd.DataFrame:
    """Pipeline complet : charge, nettoie et corrige les biais du CSV Goodreads.

    Args:
        csv_path: Chemin optionnel vers le fichier CSV (remplace CSV_PATH).

    Returns:
        DataFrame prêt à l'emploi avec toutes les colonnes de pondération.
    """
    df = load_csv(csv_path)
    df = _parse_dates(df)
    df = _parse_numerics(df)
    df = _filter_read_books(df)
    df = _clean_text_columns(df)
    df = apply_arsac_rule(df)
    df = apply_author_bias_correction(df)
    df = apply_recency_bias_correction(df)
    df = compute_bias_corrected_score(df)
    df = df.reset_index(drop=True)
    logger.info("Pipeline terminé. %d livres dans le DataFrame final.", len(df))
    return df
