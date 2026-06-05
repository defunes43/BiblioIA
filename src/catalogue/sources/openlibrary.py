"""
openlibrary.py — Client Open Library pour la découverte de livres SFF.

Open Library est une API publique sans authentification.
On interroge par sujet SFF pour obtenir un catalogue de base,
qui sera ensuite filtré (ebook FR) et enrichi (tags LLM).

Docs : https://openlibrary.org/developers/api
"""

from __future__ import annotations

import logging
import time
from typing import Iterator

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://openlibrary.org"
_PAGE_SIZE = 100  # Max autorisé par l'API subjects

# Sujets SFF ciblés — on cible le fond du catalogue, pas juste les bestsellers.
# Les sujets Open Library sont en snake_case.
SFF_SUBJECTS = [
    "science_fiction",
    "fantasy",
]


def _get(url: str, params: dict | None = None, retries: int = 3) -> dict | None:
    """GET avec retry exponentiel."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                wait = 5 * attempt
                logger.warning("Rate limit Open Library — attente %ds", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt == retries:
                logger.error("Erreur Open Library [%s] : %s", url, exc)
                return None
            time.sleep(2**attempt)
    return None


def fetch_subject_works(subject: str) -> Iterator[dict]:
    """
    Génère tous les livres d'un sujet Open Library (pagination automatique).

    Chaque dict retourné a les clés : id, title, author, year_published, source.
    """
    offset = 0
    total_fetched = 0

    while True:
        url = f"{_BASE_URL}/subjects/{subject}.json"
        data = _get(url, params={"limit": _PAGE_SIZE, "offset": offset})

        if not data:
            break

        works = data.get("works", [])
        if not works:
            break

        # Récupère le total à la première page pour le log
        if offset == 0:
            work_count = data.get("work_count", "?")
            logger.info(
                "Sujet '%s' : %s œuvres au total, récupération par pages de %d.",
                subject, work_count, _PAGE_SIZE,
            )

        for work in works:
            # Extraction de l'auteur (peut être une liste)
            authors_raw = work.get("authors", [])
            if authors_raw:
                author = authors_raw[0].get("name", "Auteur inconnu")
            else:
                author = "Auteur inconnu"

            # L'ID Open Library est de la forme "/works/OL27516W" → on prend la partie unique
            ol_key = work.get("key", "")
            book_id = ol_key.replace("/works/", "ol_") if ol_key else ""

            if not book_id or not work.get("title"):
                continue

            yield {
                "id": book_id,
                "title": work.get("title", "").strip(),
                "title_fr": None,  # Sera rempli si traduction FR trouvée via Google Books
                "author": author.strip(),
                "year_published": work.get("first_publish_year"),
                "source": "openlibrary",
            }
            total_fetched += 1

        offset += _PAGE_SIZE
        # Petite pause pour ne pas surcharger l'API (pas de limite officielle documentée)
        time.sleep(0.5)

        # Arrêt si on a dépassé le total déclaré
        if offset >= data.get("work_count", 0):
            break

    logger.info("Sujet '%s' : %d livres récupérés.", subject, total_fetched)


def fetch_all_sff_works(max_per_subject: int = 25000) -> Iterator[dict]:
    """
    Itère sur tous les sujets SFF et retourne chaque livre sans doublon.

    max_per_subject : limite le nombre de livres par sujet (évite les géants
    comme 'science_fiction' qui a 500 000+ entrées).
    """
    seen_ids: set[str] = set()
    total = 0

    for subject in SFF_SUBJECTS:
        count_for_subject = 0
        logger.info("── Récupération du sujet : %s", subject)

        for book in fetch_subject_works(subject):
            if book["id"] in seen_ids:
                continue
            seen_ids.add(book["id"])

            yield book
            count_for_subject += 1
            total += 1

            if count_for_subject >= max_per_subject:
                logger.info(
                    "Sujet '%s' : limite de %d atteinte, passage au suivant.",
                    subject, max_per_subject,
                )
                break

    logger.info("Total livres SFF uniques récupérés depuis Open Library : %d", total)
