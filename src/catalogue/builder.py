"""
builder.py — Orchestrateur du catalogue SFF.

Pipeline :
1. Récupère les livres SFF depuis Open Library (par sujet)
2. Les insère dans catalogue.db (upsert, idempotent)
3. Pour les livres non encore enrichis :
   a. Vérifie disponibilité ebook FR via Google Books
   b. Si disponible → récupère la description + génère les tags LLM
   c. Marque le livre comme enrichi (enriched_at = now)
4. Affiche les stats finales

Le builder est REPRABLE : si interrompu, il reprend où il s'est arrêté
(books avec enriched_at IS NULL).

Optimisation clé :
- Seuls les livres confirmés ebook FR passent par le LLM → ~80% d'appels évités.
- MAX_WORKERS contrôle la parallélisation (défaut 2 pour Raspberry Pi).
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from db.catalogue_db import (
    get_all_enriched_ebooks,
    get_stats,
    get_unenriched_books,
    init_catalogue,
    get_connection,
    mark_enriched,
    upsert_book,
)
from catalogue.sources.openlibrary import fetch_all_sff_works
from catalogue.sources.googlebooks import check_french_ebook
from enrichment import generate_tags_with_llm

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

_BATCH_SIZE = 50      # Livres traités par batch avant sauvegarde intermédiaire
_SLEEP_BETWEEN_LLM = 1.0   # Secondes entre deux appels LLM (rate limiting doux)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 : Ingestion Open Library → SQLite
# ─────────────────────────────────────────────────────────────────────────────

def ingest_from_openlibrary(
    db_path: Path,
    max_per_subject: int = 25000,
) -> int:
    """
    Récupère les livres SFF depuis Open Library et les insère dans le catalogue.
    Retourne le nombre de nouveaux livres insérés.
    """
    inserted = 0
    batch: list[dict] = []

    def _flush_batch(books: list[dict]) -> int:
        count = 0
        with get_connection(db_path) as conn:
            stats_before = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
            for book in books:
                upsert_book(conn, book)
            stats_after = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
            count = stats_after - stats_before
        return count

    for book in fetch_all_sff_works(max_per_subject=max_per_subject):
        batch.append(book)
        if len(batch) >= _BATCH_SIZE:
            inserted += _flush_batch(batch)
            batch.clear()

    if batch:
        inserted += _flush_batch(batch)

    logger.info("Ingestion terminée : %d nouveaux livres ajoutés.", inserted)
    return inserted


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 : Enrichissement (ebook check + tagging LLM)
# ─────────────────────────────────────────────────────────────────────────────

def _enrich_one_book(book: dict) -> dict:
    """
    Traite un livre :
    1. Vérifie ebook FR (Google Books)
    2. Si disponible → génère les tags LLM
    Retourne un dict avec les résultats d'enrichissement.
    """
    book_id = book["id"]
    title = book["title"]
    author = book["author"]

    result = check_french_ebook(title, author)

    tags: list[str] = []
    description = ""

    if result.available:
        description = result.description or ""
        # Rate limiting doux avant l'appel LLM
        time.sleep(_SLEEP_BETWEEN_LLM)
        tags = generate_tags_with_llm(result.title_fr, author, description)

    return {
        "id": book_id,
        "is_ebook_fr": result.available,
        "title_fr": result.title_fr if result.available else None,
        "ebook_link": result.ebook_link,
        "description": description,
        "tags": tags,
        "enriched_at": datetime.now(timezone.utc).isoformat(),
    }


def enrich_catalogue(db_path: Path, max_workers: int = 2) -> int:
    """
    Enrichit les livres non encore traités (enriched_at IS NULL).
    Retourne le nombre de livres enrichis.
    """
    enriched_count = 0

    while True:
        with get_connection(db_path) as conn:
            batch = get_unenriched_books(conn, limit=_BATCH_SIZE)

        if not batch:
            logger.info("Aucun livre restant à enrichir.")
            break

        logger.info("Enrichissement de %d livres (workers=%d)…", len(batch), max_workers)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_enrich_one_book, book): book for book in batch}

            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    with get_connection(db_path) as conn:
                        mark_enriched(
                            conn,
                            result["id"],
                            is_ebook_fr=result["is_ebook_fr"],
                            ebook_link=result["ebook_link"],
                            description=result["description"],
                            tags=result["tags"],
                            enriched_at=result["enriched_at"],
                        )
                        # Met à jour le title_fr si trouvé
                        if result["is_ebook_fr"] and result.get("title_fr"):
                            conn.execute(
                                "UPDATE books SET title_fr = ? WHERE id = ?",
                                (result["title_fr"], result["id"]),
                            )
                    enriched_count += 1

                except Exception as exc:
                    src_book = futures[future]
                    logger.error(
                        "Erreur enrichissement '%s' : %s", src_book.get("title"), exc
                    )

        logger.info("Batch terminé. Total enrichis : %d", enriched_count)

    return enriched_count


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entrée public
# ─────────────────────────────────────────────────────────────────────────────

def build_catalogue(
    db_path: Path,
    max_per_subject: int = 500,
    max_workers: int = 2,
) -> None:
    """
    Pipeline complet de construction/mise à jour du catalogue.

    Args:
        db_path: Chemin vers le fichier catalogue.db.
        max_per_subject: Nombre max de livres par sujet Open Library.
        max_workers: Nombre de workers pour l'enrichissement parallèle.
    """
    logger.info("═" * 60)
    logger.info("🚀 Démarrage du catalogue builder")
    logger.info("   DB        : %s", db_path)
    logger.info("   Max/sujet : %d", max_per_subject)
    logger.info("   Workers   : %d", max_workers)
    logger.info("═" * 60)

    # Initialisation des tables
    init_catalogue(db_path)

    # Phase 1 : Ingestion
    logger.info("── Phase 1 : Ingestion Open Library")
    new_books = ingest_from_openlibrary(db_path, max_per_subject=max_per_subject)

    with get_connection(db_path) as conn:
        stats = get_stats(conn)
    logger.info(
        "   Catalogue total : %d livres (%d nouveaux)", stats["total"], new_books
    )

    # Phase 2 : Enrichissement
    logger.info("── Phase 2 : Enrichissement (ebook FR + tags LLM)")
    enriched = enrich_catalogue(db_path, max_workers=max_workers)

    # Bilan final
    with get_connection(db_path) as conn:
        stats = get_stats(conn)

    logger.info("═" * 60)
    logger.info("✅ Catalogue builder terminé")
    logger.info("   Total livres      : %d", stats["total"])
    logger.info("   Enrichis          : %d", stats["enriched"])
    logger.info("   Ebook FR dispo    : %d", stats["ebook_fr"])
    logger.info("═" * 60)
