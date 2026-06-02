"""
googlebooks.py — Vérification de disponibilité ebook français via Google Books.

Wrapper propre autour de l'api_client.py existant, exposant uniquement
les fonctions nécessaires au catalogue builder.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

# Réutilise le client existant (pas de duplication de logique réseau)
from api_client import search_books_google

logger = logging.getLogger(__name__)


@dataclass
class EbookCheckResult:
    available: bool
    title_fr: str        # Titre trouvé dans Google Books (peut être la traduction FR)
    ebook_link: str
    description: str


def check_french_ebook(title: str, author: str) -> EbookCheckResult:
    """
    Vérifie si un livre est disponible en ebook ET en français via Google Books.

    Stratégie :
    1. Recherche stricte (intitle + inauthor)
    2. Si rien → recherche large (texte libre)
    3. Pour chaque résultat : langue = 'fr' ET isEbook = True → ✅
    """
    for strict in (True, False):
        items = search_books_google(title, author, strict_search=strict)
        if not items:
            continue

        for item in items:
            info = item.get("volumeInfo", {})
            sale_info = item.get("saleInfo", {})
            access_info = item.get("accessInfo", {})

            is_ebook = (
                sale_info.get("isEbook", False)
                or access_info.get("epub", {}).get("isAvailable", False)
            )
            is_french = info.get("language", "") == "fr"

            if is_french and is_ebook:
                title_fr = info.get("title", title)
                link = info.get("previewLink", "")
                description = info.get("description", "")
                logger.info("✅ Ebook FR trouvé : '%s' — %s", title_fr, link)
                return EbookCheckResult(
                    available=True,
                    title_fr=title_fr,
                    ebook_link=link,
                    description=description,
                )

    logger.debug("❌ Pas d'ebook FR pour : '%s' de %s", title, author)
    return EbookCheckResult(available=False, title_fr=title, ebook_link="", description="")
