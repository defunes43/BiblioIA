"""
catalogue_db.py — Couche d'accès SQLite pour le catalogue SFF.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Schéma
# ─────────────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS books (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    author          TEXT NOT NULL,
    year_published  INTEGER,
    is_ebook        INTEGER DEFAULT 0,
    description     TEXT,
    tags            TEXT,        -- JSON array: ["Space Opera", "IA", ...]
    enriched_at     TEXT,        -- ISO8601, NULL = pas encore enrichi
    source          TEXT         -- 'noosfere'
);
CREATE INDEX IF NOT EXISTS idx_ebook     ON books(is_ebook);
CREATE INDEX IF NOT EXISTS idx_enriched  ON books(enriched_at);
"""

# ─────────────────────────────────────────────────────────────────────────────
# Connexion
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def get_connection(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Context manager : ouvre, yield, commit/rollback, ferme."""
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # Robustesse en cas d'interruption
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_catalogue(db_path: Path) -> None:
    """Crée les tables si elles n'existent pas encore."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        conn.executescript(_DDL)
    logger.info("Catalogue DB initialisée : %s", db_path)


# ─────────────────────────────────────────────────────────────────────────────
# Écriture
# ─────────────────────────────────────────────────────────────────────────────

def upsert_book(conn: sqlite3.Connection, book: dict) -> None:
    """Insère ou met à jour un livre. En cas de doublon (même titre + auteur), garde l'année la plus récente."""
    year = book.get("year_published")
    is_ebook = 1 if (year is not None and year > 2010) else 0
    
    # Récupérer l'année existante si le livre existe déjà
    existing = conn.execute(
        "SELECT year_published FROM books WHERE title = ? AND author = ?",
        (book.get("title", ""), book.get("author", "")),
    ).fetchone()
    
    if existing:
        existing_year = existing[0]
        if existing_year is not None and (year is None or existing_year > year):
            year = existing_year
    
    conn.execute(
        """
        INSERT INTO books (id, title, author, year_published, is_ebook, source)
        VALUES (:id, :title, :author, :year_published, :is_ebook, :source)
        ON CONFLICT(id) DO UPDATE SET
            title          = excluded.title,
            author         = excluded.author,
            year_published = excluded.year_published,
            is_ebook       = excluded.is_ebook,
            source         = excluded.source
        """,
        {
            "id": book["id"],
            "title": book.get("title", ""),
            "author": book.get("author", ""),
            "year_published": year,
            "is_ebook": is_ebook,
            "source": book.get("source", "openlibrary"),
        },
    )


def mark_enriched(
    conn: sqlite3.Connection,
    book_id: str,
    *,
    description: str,
    tags: list[str],
    enriched_at: str,
) -> None:
    """Met à jour les champs d'enrichissement d'un livre."""
    conn.execute(
        """
        UPDATE books
        SET description  = :description,
            tags         = :tags,
            enriched_at  = :enriched_at
        WHERE id = :id
        """,
        {
            "id": book_id,
            "description": description,
            "tags": json.dumps(tags, ensure_ascii=False),
            "enriched_at": enriched_at,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Lecture
# ─────────────────────────────────────────────────────────────────────────────

def get_unenriched_books(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    """Retourne les livres pas encore enrichis (pas de enriched_at)."""
    rows = conn.execute(
        "SELECT id, title, author, year_published FROM books WHERE enriched_at IS NULL LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_enriched_ebooks(conn: sqlite3.Connection) -> list[dict]:
    """Retourne tous les livres enrichis et disponibles en ebook FR."""
    rows = conn.execute(
        """
        SELECT id, title, author, year_published, is_ebook, tags
        FROM books
        WHERE is_ebook = 1 AND enriched_at IS NOT NULL AND tags IS NOT NULL
        """
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d["tags"]) if d["tags"] else []
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
        result.append(d)
    return result


def get_stats(conn: sqlite3.Connection) -> dict:
    """Retourne des statistiques sur le catalogue."""
    total = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    enriched = conn.execute("SELECT COUNT(*) FROM books WHERE enriched_at IS NOT NULL").fetchone()[0]
    ebook = conn.execute("SELECT COUNT(*) FROM books WHERE is_ebook = 1").fetchone()[0]
    return {"total": total, "enriched": enriched, "ebook": ebook}
