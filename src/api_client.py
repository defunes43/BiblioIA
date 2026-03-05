"""
api_client.py — Client Google Books avec validation disponibilité ebook français.

Responsabilités :
- Interroger l'API Google Books avec filtres langue et format.
- Valider qu'un titre est disponible en ebook ET en français.
- Gérer les erreurs réseau (timeout, rate-limit) avec retry exponentiel.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from config import GOOGLE_BOOKS_API_KEY, GOOGLE_BOOKS_BASE_URL

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Types de données
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class BookAvailability:
    """Résultat de la vérification de disponibilité d'un livre.

    Attributes:
        available: True si le livre est disponible en ebook en français.
        title: Titre retourné par Google Books.
        authors: Liste des auteurs retournés par Google Books.
        language: Code langue du volume trouvé (ex: "fr").
        is_ebook: Indique si un format ebook est disponible.
        preview_link: URL vers Google Books.
        error: Message d'erreur si la recherche a échoué.
    """

    available: bool = False
    title: str = ""
    authors: list[str] = field(default_factory=list)
    language: str = ""
    is_ebook: bool = False
    preview_link: str = ""
    error: str = ""

    def __str__(self) -> str:
        if self.error:
            return f"[ERREUR] {self.error}"
        if not self.available:
            return (
                f"❌ Non disponible en ebook français : '{self.title}'"
                f" (langue={self.language!r}, ebook={self.is_ebook})"
            )
        return (
            f"✅ Disponible en ebook français : '{self.title}'"
            f" — {', '.join(self.authors)}\n   🔗 {self.preview_link}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internes
# ─────────────────────────────────────────────────────────────────────────────


def _build_params(title: str, author: str) -> dict[str, str]:
    """Construit les paramètres de requête Google Books."""
    query = f'intitle:"{title}"'
    if author:
        query += f' inauthor:"{author}"'

    params: dict[str, str] = {
        "q": query,
        "langRestrict": "fr",
        "printType": "books",
        "maxResults": "10",
    }
    if GOOGLE_BOOKS_API_KEY:
        params["key"] = GOOGLE_BOOKS_API_KEY
    return params


def _extract_volume_info(item: dict[str, Any]) -> dict[str, Any]:
    """Extrait les informations pertinentes d'un item Google Books."""
    volume_info: dict[str, Any] = item.get("volumeInfo", {})
    sale_info: dict[str, Any] = item.get("saleInfo", {})
    access_info: dict[str, Any] = item.get("accessInfo", {})

    is_ebook: bool = sale_info.get("isEbook", False) or access_info.get(
        "epub", {}
    ).get("isAvailable", False)

    return {
        "title": volume_info.get("title", ""),
        "authors": volume_info.get("authors", []),
        "language": volume_info.get("language", ""),
        "is_ebook": is_ebook,
        "preview_link": volume_info.get("previewLink", ""),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions publiques
# ─────────────────────────────────────────────────────────────────────────────


def search_books_google(
    title: str,
    author: str = "",
    max_retries: int = 3,
    timeout: int = 10,
) -> list[dict[str, Any]]:
    """Interroge l'API Google Books et retourne les items bruts.

    Args:
        title: Titre du livre recherché.
        author: Auteur du livre (optionnel, améliore la précision).
        max_retries: Nombre maximum de tentatives en cas d'erreur.
        timeout: Délai d'attente HTTP en secondes.

    Returns:
        Liste de volumes (dicts) retournés par l'API.

    Raises:
        requests.HTTPError: Si l'API retourne une erreur non récupérable.
    """
    params = _build_params(title, author)

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(
                GOOGLE_BOOKS_BASE_URL, params=params, timeout=timeout
            )

            # Gestion rate-limit (429) avec backoff exponentiel
            if response.status_code == 429:
                wait_time = 2**attempt
                logger.warning(
                    "Rate-limit Google Books (429). Attente %ds (tentative %d/%d).",
                    wait_time,
                    attempt,
                    max_retries,
                )
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            data = response.json()
            items: list[dict[str, Any]] = data.get("items", [])
            logger.debug(
                "Google Books : %d résultat(s) pour '%s' / '%s'.",
                len(items),
                title,
                author,
            )
            return items

        except requests.Timeout:
            logger.warning(
                "Timeout Google Books (tentative %d/%d) pour '%s'.",
                attempt,
                max_retries,
                title,
            )
            if attempt == max_retries:
                logger.error("Toutes les tentatives ont échoué pour '%s'.", title)
                return []
            time.sleep(2**attempt)

        except requests.HTTPError as exc:
            logger.error("Erreur HTTP Google Books pour '%s' : %s", title, exc)
            return []

        except requests.RequestException as exc:
            logger.error("Erreur réseau inattendue pour '%s' : %s", title, exc)
            return []

    return []


def is_available_french_ebook(title: str, author: str = "") -> BookAvailability:
    """Vérifie si un livre est disponible en ebook ET en français via Google Books.

    Les critères de validation sont tous les deux obligatoires :
    - ``volumeInfo.language == "fr"``
    - ``saleInfo.isEbook == True`` OU ``accessInfo.epub.isAvailable == True``

    Args:
        title: Titre du livre à vérifier.
        author: Auteur du livre (recommandé pour éviter les ambiguïtés).

    Returns:
        :class:`BookAvailability` décrivant le résultat.
    """
    try:
        items = search_books_google(title, author)
    except Exception as exc:  # noqa: BLE001
        return BookAvailability(error=f"Erreur lors de la recherche : {exc}")

    if not items:
        return BookAvailability(
            error=f"Aucun résultat Google Books pour '{title}' / '{author}'."
        )

    for item in items:
        info = _extract_volume_info(item)
        if info["language"] == "fr" and info["is_ebook"]:
            return BookAvailability(
                available=True,
                title=info["title"],
                authors=info["authors"],
                language=info["language"],
                is_ebook=True,
                preview_link=info["preview_link"],
            )

    # Aucun résultat ne satisfait les deux critères : retourne le premier pour info
    first = _extract_volume_info(items[0])
    return BookAvailability(
        available=False,
        title=first["title"],
        authors=first["authors"],
        language=first["language"],
        is_ebook=first["is_ebook"],
        preview_link=first["preview_link"],
    )
