"""
api_client.py — Client Google Books unifié pour BiblioIA.

Responsabilités :
- Interroger l'API pour récupérer les IDs de volumes.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from config import GOOGLE_BOOKS_API_KEY, GOOGLE_BOOKS_BASE_URL

logger = logging.getLogger(__name__)

def search_books_google(
    title: str,
    author: str = "",
    isbn: str = "",
    max_retries: int = 3,
    strict_search: bool = True,
    lang_restrict: str = None,
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

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(GOOGLE_BOOKS_BASE_URL, params=params, timeout=10)
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response.json().get("items", [])
        except requests.RequestException:
            if attempt == max_retries:
                return []
            time.sleep(2**attempt)
    return []
