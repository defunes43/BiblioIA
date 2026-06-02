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
    title_fr        TEXT,
    author          TEXT NOT NULL,
    year_published  INTEGER,
    is_ebook_fr     INTEGER DEFAULT 0,
    ebook_link      TEXT,
    description     TEXT,
    tags            TEXT,        -- JSON array: ["Space Opera", "IA", ...]
    enriched_at     TEXT,        -- ISO8601, NULL = pas encore enrichi
    source          TEXT         -- 'openlibrary' | 'googlebooks'
);
CREATE INDEX IF NOT EXISTS idx_ebook     ON books(is_ebook_fr);
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
    """Insère ou met à jour un livre (ignore les champs enrichment si déjà enrichi)."""
    conn.execute(
        """
        INSERT INTO books (id, title, title_fr, author, year_published, source)
        VALUES (:id, :title, :title_fr, :author, :year_published, :source)
        ON CONFLICT(id) DO UPDATE SET
            title          = excluded.title,
            author         = excluded.author,
            year_published = excluded.year_published,
            source         = excluded.source
        WHERE books.enriched_at IS NULL
        """,
        {
            "id": book["id"],
            "title": book.get("title", ""),
            "title_fr": book.get("title_fr"),
            "author": book.get("author", ""),
            "year_published": book.get("year_published"),
            "source": book.get("source", "openlibrary"),
        },
    )


def mark_enriched(
    conn: sqlite3.Connection,
    book_id: str,
    *,
    is_ebook_fr: bool,
    ebook_link: str,
    description: str,
    tags: list[str],
    enriched_at: str,
) -> None:
    """Met à jour les champs d'enrichissement d'un livre."""
    conn.execute(
        """
        UPDATE books
        SET is_ebook_fr  = :is_ebook_fr,
            ebook_link   = :ebook_link,
            description  = :description,
            tags         = :tags,
            enriched_at  = :enriched_at
        WHERE id = :id
        """,
        {
            "id": book_id,
            "is_ebook_fr": 1 if is_ebook_fr else 0,
            "ebook_link": ebook_link,
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
        SELECT id, title, title_fr, author, year_published, ebook_link, tags
        FROM books
        WHERE is_ebook_fr = 1 AND enriched_at IS NOT NULL AND tags IS NOT NULL
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
    ebook_fr = conn.execute("SELECT COUNT(*) FROM books WHERE is_ebook_fr = 1").fetchone()[0]
    return {"total": total, "enriched": enriched, "ebook_fr": ebook_fr}
