"""
engine.py — Moteur de recommandation déterministe de BiblioIA.

Algorithme : dot product
  score(livre) = Σ tag_weight_user[tag] pour chaque tag du livre présent dans le profil

Aucun LLM, aucune API externe : résultat en < 100ms sur Raspberry Pi.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from db.catalogue_db import get_all_enriched_ebooks, get_connection as cat_conn
from db.profile_db import (
    get_tag_weights,
    get_read_titles_authors,
    get_connection as prof_conn,
)
from recommender.models import BookRecommendation

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    """Retire accents, majuscules, ponctuation — pour la comparaison anti-doublon."""
    no_accents = "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9]", "", no_accents.lower())


def _is_already_read(title: str, author: str, read_set: set[str]) -> bool:
    """Vérifie si un titre/auteur correspond à un livre déjà lu (comparaison souple)."""
    norm_title = _normalize(title)
    norm_author = _normalize(author)

    # Correspondance exacte normalisée
    key = f"{norm_title}|{norm_author}"
    if key in read_set:
        return True

    # Correspondance partielle : le titre normalisé est contenu dans une clé lue
    for read_key in read_set:
        read_title, read_author = read_key.split("|", 1)
        if norm_title and (norm_title in read_title or read_title in norm_title):
            # Vérification supplémentaire sur l'auteur (au moins un mot en commun)
            author_words = set(re.findall(r"[a-z]+", norm_author))
            read_author_words = set(re.findall(r"[a-z]+", read_author))
            if author_words & read_author_words:
                return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# Moteur
# ─────────────────────────────────────────────────────────────────────────────

def get_recommendations(
    profile_db: Path,
    catalogue_db: Path,
    n: int = 15,
    genre_filter: str | None = None,
) -> list[BookRecommendation]:
    """
    Calcule et retourne les N meilleures recommandations.

    Args:
        profile_db: Chemin vers profile.db
        catalogue_db: Chemin vers catalogue.db
        n: Nombre de recommandations à retourner
        genre_filter: Si fourni, ne garde que les livres dont un tag contient cette chaîne
                      (insensible à la casse). Ex: "Space Opera", "Cyberpunk"

    Returns:
        Liste de BookRecommendation triée par score décroissant.
    """
    # ── Chargement des données ──────────────────────────────────────────────
    with prof_conn(profile_db) as conn:
        tag_weights = get_tag_weights(conn)
        read_set = get_read_titles_authors(conn)

    with cat_conn(catalogue_db) as conn:
        catalogue = get_all_enriched_ebooks(conn)

    if not tag_weights:
        logger.warning("Profil vide — aucun tag_weight trouvé. Lance d'abord 'update-profile'.")
        return []

    if not catalogue:
        logger.warning("Catalogue vide — lance d'abord 'build-catalogue'.")
        return []

    logger.info(
        "Scoring : %d livres catalogue × %d tags profil",
        len(catalogue), len(tag_weights),
    )

    # Normalisation des poids : on divise par le poids max pour ramener à [0, 1]
    max_weight = max(tag_weights.values()) if tag_weights else 1.0

    # ── Scoring ────────────────────────────────────────────────────────────
    scored: list[tuple[float, dict, list[str]]] = []

    genre_filter_norm = genre_filter.lower().strip() if genre_filter else None

    for book in catalogue:
        tags: list[str] = book.get("tags", [])
        title = book.get("title", "")
        title_fr = book.get("title_fr") or title
        author = book.get("author", "")

        # Filtre genre (optionnel)
        if genre_filter_norm:
            tag_names_lower = [t.lower() for t in tags]
            if not any(genre_filter_norm in t for t in tag_names_lower):
                continue

        # Filtre anti-doublon (déjà lu)
        if _is_already_read(title, author, read_set) or _is_already_read(title_fr, author, read_set):
            continue

        # Dot product : score = Σ (weight_tag / max_weight) pour les tags en commun
        matching_tags = []
        raw_score = 0.0
        for tag in tags:
            tag_cap = tag.strip().capitalize()
            if tag_cap in tag_weights:
                raw_score += tag_weights[tag_cap] / max_weight
                matching_tags.append(tag_cap)

        if raw_score <= 0:
            continue

        scored.append((raw_score, book, matching_tags))

    # ── Tri et construction du résultat ────────────────────────────────────
    scored.sort(key=lambda x: x[0], reverse=True)

    recommendations = []
    for raw_score, book, matching_tags in scored[:n]:
        recommendations.append(
            BookRecommendation(
                title=book.get("title", ""),
                title_fr=book.get("title_fr"),
                author=book.get("author", ""),
                year_published=book.get("year_published"),
                score=raw_score,
                matching_tags=matching_tags[:5],  # Top 5 tags pour l'affichage
                ebook_link=book.get("ebook_link", ""),
            )
        )

    logger.info("Recommandations calculées : %d résultats (filtre: %s)", len(recommendations), genre_filter or "aucun")
    return recommendations
