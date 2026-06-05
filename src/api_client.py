"""
api_client.py — Client Google Books unifié pour BiblioIA.

Responsabilités :
- Interroger l'API pour récupérer les IDs de volumes.
- Extraire la fiche complète (Volume API) pour obtenir l'arborescence des genres.
- Valider la disponibilité d'un livre en Ebook FR pour l'Agent.
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
    """Résultat de la vérification de disponibilité d'un livre."""
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
            return f"❌ Non disponible en ebook français : '{self.title}'"
        return f"✅ Disponible en ebook français : '{self.title}'\n   🔗 {self.preview_link}"


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions de Recherche (Search API)
# ─────────────────────────────────────────────────────────────────────────────

def search_books_google(
    title: str,
    author: str = "",
    isbn: str = "",
    max_retries: int = 3,
    strict_search: bool = True,
    lang_restrict: str = None
) -> list[dict[str, Any]]:
    """Cherche des livres et retourne la liste des items."""
    
    if isbn:
        query = f'isbn:{isbn}'
    elif strict_search:
        query = f'intitle:"{title}"'
        if author:
            query += f' inauthor:"{author}"'
    else:
        query = f'{title} {author}'.strip()

    params: dict[str, str] = {"q": query, "maxResults": "5"}
    if GOOGLE_BOOKS_API_KEY:
        params["key"] = GOOGLE_BOOKS_API_KEY
    if lang_restrict:
        params["langRestrict"] = lang_restrict

    # Log de l'URL pour debug (SANS la clé API)
    safe_url = f"{GOOGLE_BOOKS_BASE_URL}?q={query}&maxResults=5"
    if lang_restrict:
        safe_url += f"&langRestrict={lang_restrict}"
    logger.info("   [API Search] GET %s", safe_url)

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(GOOGLE_BOOKS_BASE_URL, params=params, timeout=10)
            
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(2**attempt)
                continue
                
            response.raise_for_status()
            items = response.json().get("items", [])
            logger.info("   [API Search] Retour API : %d items trouvés.", len(items))
            return items
            
        except requests.RequestException as exc:
            if attempt == max_retries:
                logger.error("   [API Search] Erreur réseau : %s", exc)
                return []
            time.sleep(2**attempt)
    
    return []


def get_volume_id(title: str, author: str, isbn13: str, isbn10: str) -> str:
    """Stratégie en cascade pure, prend strictement le premier ID trouvé."""
    logger.info("🔍 Recherche ID pour : '%s' (ISBN13: %s)", title, isbn13)
    
    # 1. Tentative ISBN-13
    if isbn13:
        logger.info(" -> Tentative ISBN-13")
        items = search_books_google("", "", isbn=isbn13)
        if items:
            vol_id = items[0].get("id", "")
            vol_title = items[0].get("volumeInfo", {}).get("title", "Titre inconnu")
            logger.info(" ✅ ID trouvé via ISBN-13 : %s (Titre Google: '%s')", vol_id, vol_title)
            return vol_id
        else:
            logger.info(" ❌ Aucun résultat pour ISBN-13.")
            
    # 2. Tentative ISBN-10
    if isbn10:
        logger.info(" -> Tentative ISBN-10")
        items = search_books_google("", "", isbn=isbn10)
        if items:
            vol_id = items[0].get("id", "")
            vol_title = items[0].get("volumeInfo", {}).get("title", "Titre inconnu")
            logger.info(" ✅ ID trouvé via ISBN-10 : %s (Titre Google: '%s')", vol_id, vol_title)
            return vol_id
        else:
            logger.info(" ❌ Aucun résultat pour ISBN-10.")
            
    # 3. Tentative Titre + Auteur
    if title:
        logger.info(" -> Tentative Titre + Auteur (Strict)")
        items = search_books_google(title, author, strict_search=True)
        if items:
            vol_id = items[0].get("id", "")
            vol_title = items[0].get("volumeInfo", {}).get("title", "Titre inconnu")
            logger.info(" ✅ ID trouvé via Texte Strict : %s (Titre Google: '%s')", vol_id, vol_title)
            return vol_id
        else:
            logger.info(" ❌ Aucun résultat pour Texte Strict.")
            
        logger.info(" -> Tentative Titre + Auteur (Large)")
        items = search_books_google(title, author, strict_search=False)
        if items:
            vol_id = items[0].get("id", "")
            vol_title = items[0].get("volumeInfo", {}).get("title", "Titre inconnu")
            logger.info(" ✅ ID trouvé via Texte Large : %s (Titre Google: '%s')", vol_id, vol_title)
            return vol_id
        else:
            logger.info(" ❌ Aucun résultat pour Texte Large.")
            
    logger.warning(" 💥 Échec total. Aucun ID trouvé par aucune méthode.")
    return ""

# ─────────────────────────────────────────────────────────────────────────────
# Vérification Ebook (Agent API)
# ─────────────────────────────────────────────────────────────────────────────

def is_available_french_ebook(title: str, author: str = "") -> BookAvailability:
    """Vérifie si un livre est disponible en ebook ET en français."""
    try:
        items = search_books_google(title, author, strict_search=True)
        if not items:
            items = search_books_google(title, author, strict_search=False)
    except Exception as exc: 
        return BookAvailability(error=f"Erreur de recherche : {exc}")

    if not items:
        return BookAvailability(error=f"Aucun résultat pour '{title}'.")

    for item in items:
        info = item.get("volumeInfo", {})
        sale_info = item.get("saleInfo", {})
        access_info = item.get("accessInfo", {})
        
        is_ebook = sale_info.get("isEbook", False) or access_info.get("epub", {}).get("isAvailable", False)
        
        if info.get("language") == "fr" and is_ebook:
            return BookAvailability(
                available=True,
                title=info.get("title", ""),
                authors=info.get("authors", []),
                language="fr",
                is_ebook=True,
                preview_link=info.get("previewLink", ""),
            )

    first = items[0].get("volumeInfo", {})
    return BookAvailability(available=False, title=first.get("title", ""))