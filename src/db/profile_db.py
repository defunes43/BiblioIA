"""
profile_db.py — Couche d'accès SQLite pour le profil utilisateur.
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
CREATE TABLE IF NOT EXISTS read_books (
    book_id     TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    author      TEXT,
    tags        TEXT,    -- JSON array
    score       REAL     -- functional_relevance_score
);

CREATE TABLE IF NOT EXISTS tag_weights (
    tag         TEXT PRIMARY KEY,
    weight      REAL,    -- somme des scores fonctionnels des livres portant ce tag
    count       INTEGER  -- nombre de livres lus avec ce tag
);

CREATE TABLE IF NOT EXISTS metadata (
    key         TEXT PRIMARY KEY,
    value       TEXT
);
"""

# ─────────────────────────────────────────────────────────────────────────────
# Connexion
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def get_connection(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_profile(db_path: Path) -> None:
    """Crée les tables si elles n'existent pas encore."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        conn.executescript(_DDL)
    logger.info("Profile DB initialisée : %s", db_path)


# ─────────────────────────────────────────────────────────────────────────────
# Écriture
# ─────────────────────────────────────────────────────────────────────────────

def save_profile(conn: sqlite3.Connection, df_processed) -> None:
    Sauvegarde le DataFrame traité dans les tables read_books et tag_weights.
    df_processed doit avoir les colonnes : Book Id, Title, Author, Bookshelves,
    functional_relevance_score (ou bias_corrected_score).
    """
    score_col = (
        "functional_relevance_score"
        if "functional_relevance_score" in df_processed.columns
        else "bias_corrected_score"
    )

    # Vide les tables avant de réécrire (rebuild complet)
    conn.execute("DELETE FROM read_books")
    conn.execute("DELETE FROM tag_weights")

    tag_accumulator: dict[str, dict] = {}

    for _, row in df_processed.iterrows():
        book_id = str(row.get("Book Id", ""))
        title = str(row.get("Title", "")).strip()
        author = str(row.get("Author", "")).strip()
        score = float(row.get(score_col, 0.0))

        raw_tags = str(row.get("Bookshelves", ""))
        tags = [
            t.strip().capitalize()
            for t in raw_tags.split(",")
            if t.strip() and t.strip().lower() not in {"nan", "erreur llm", "non classifié", ""}
        ]

        conn.execute(
            """
            INSERT OR REPLACE INTO read_books (book_id, title, author, tags, score)
            VALUES (?, ?, ?, ?, ?)
            """,
            (book_id, title, author, json.dumps(tags, ensure_ascii=False), score),
        )

        # Accumulation des poids par tag
        for tag in tags:
            if tag not in tag_accumulator:
                tag_accumulator[tag] = {"weight": 0.0, "count": 0}
            tag_accumulator[tag]["weight"] += score
            tag_accumulator[tag]["count"] += 1

    # Sauvegarde des tag_weights
    for tag, data in tag_accumulator.items():
        conn.execute(
            "INSERT OR REPLACE INTO tag_weights (tag, weight, count) VALUES (?, ?, ?)",
            (tag, data["weight"], data["count"]),
        )

    logger.info(
        "Profil sauvegardé : %d livres, %d tags uniques.",
        len(df_processed),
        len(tag_accumulator),
    )


def set_metadata(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value)
    )


def get_metadata(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Lecture
# ─────────────────────────────────────────────────────────────────────────────

def get_tag_weights(conn: sqlite3.Connection) -> dict[str, float]:
    """Retourne {tag: weight} trié par poids décroissant."""
    rows = conn.execute(
        "SELECT tag, weight FROM tag_weights ORDER BY weight DESC"
    ).fetchall()
    return {r["tag"]: r["weight"] for r in rows}


def get_read_titles_authors(conn: sqlite3.Connection) -> set[str]:
    """
    Retourne un set de chaînes normalisées 'titre|auteur' pour le filtre anti-doublon.
    """
    rows = conn.execute("SELECT title, author FROM read_books").fetchall()
    return {
        f"{r['title'].lower().strip()}|{r['author'].lower().strip()}" for r in rows
    }


def get_stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM read_books").fetchone()[0]
    tags = conn.execute("SELECT COUNT(*) FROM tag_weights").fetchone()[0]
    last_updated = get_metadata(conn, "last_updated") or "jamais"
    return {"read_books": total, "unique_tags": tags, "last_updated": last_updated}
