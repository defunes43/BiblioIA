"""
noosfere.py — Scraper pour le site Noosfere.org (catalogue SFF français).

Ce module respecte le site avec des délais généreux entre les requêtes et fournit
une pipeline complète pour alimenter le catalogue BiblioIA.
"""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_BASE_URL = "https://www.noosfere.org"
_YEAR_URL = f"{_BASE_URL}/livres/parutions.asp?interv=annee&nouvo=0&annee={{}}&tri=editeur&typeouvrage=1"
_MONTH_URL = f"{_BASE_URL}/livres/parutions.asp?interv=mois&annee={{}}&mois={{}}&nouvo=0&tri=editeur&typeouvrage=1"
_USER_AGENT = "BiblioIA/1.0 (contact@bibliia.fr; respectueux, délai 2s entre requêtes)"


# ─────────────────────────────────────────────────────────────────────────────
# Types de données
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScrapeResult:
    """Résultat du scraping d'un livre individuel."""
    numlivre: str
    title: str
    author: str
    summary: str
    success: bool
    error: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Scraping d'une page annuelle/mensuelle
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_with_delay(url: str, session: requests.Session, delay: float, max_retries: int = 3) -> str | None:
    """Récupère une page avec délai généreux et gestion des retries."""
    headers = {"User-Agent": _USER_AGENT}
    for attempt in range(max_retries):
        try:
            time.sleep(delay)
            response = session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            logger.warning("Tentative %d/%d échouée pour %s: %s", attempt + 1, max_retries, url, exc)
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1) * delay)
    return None


def _find_books_with_summary(html: str) -> list[str]:
    """
    Extrait les numlivres de livres qui ont un résumé.
    
    Le résumé est indiqué par la présence de <span class="cadre1" title="Présence d'un résumé">R</span>
    sur la même ligne que le lien du livre.
    """
    soup = BeautifulSoup(html, "html.parser")
    numlivres = []
    
    for link in soup.find_all("a", href=re.compile(r"niourf\.asp\?numlivre=")):
        href = link.get("href", "")
        match = re.search(r"numlivre=(\d+)", href)
        if not match:
            continue
        
        numlivre = match.group(1)
        parent_td = link.find_parent("td")
        if parent_td:
            tr_html = str(parent_td)
            if "Présence d'un résumé" in tr_html or "Presence d'un resume" in tr_html:
                numlivres.append(numlivre)
    
    return numlivres


def _scrape_year_page(year: int, session: requests.Session, delay: float) -> list[str]:
    """Scrape la page de parutions d'une année et retourne les numlivres avec résumé."""
    url = _YEAR_URL.format(year)
    logger.info("Scraping année %d: %s", year, url)
    
    html = _fetch_with_delay(url, session, delay)
    if not html:
        logger.error("Impossible de récupérer la page pour l'année %d", year)
        return []
    
    return _find_books_with_summary(html)


def _scrape_month_page(year: int, month: int, session: requests.Session, delay: float) -> list[str]:
    """Scrape la page de parutions d'un mois et retourne les numlivres avec résumé."""
    url = _MONTH_URL.format(year, month)
    logger.info("Scraping mois %d/%d: %s", month, year, url)
    
    html = _fetch_with_delay(url, session, delay)
    if not html:
        logger.error("Impossible de récupérer la page pour %d/%d", month, year)
        return []
    
    return _find_books_with_summary(html)


# ─────────────────────────────────────────────────────────────────────────────
# Scraping d'une fiche livre
# ─────────────────────────────────────────────────────────────────────────────

def _parse_book_details(html: str, numlivre: str) -> ScrapeResult:
    """
    Extrait les données d'une fiche livre.
    
    - Titre : <span class="TitreNiourf">
    - Auteur : <span class="AuteurNiourf"> <a>...</a>
    - Résumé : <div id="quatrieme">
    """
    soup = BeautifulSoup(html, "html.parser")
    
    title_span = soup.find("span", class_="TitreNiourf")
    title = title_span.get_text(strip=True) if title_span else ""
    
    author_span = soup.find("span", class_="AuteurNiourf")
    author = ""
    if author_span:
        author_link = author_span.find("a")
        author = author_link.get_text(strip=True) if author_link else author_span.get_text(strip=True)
    
    summary_div = soup.find("div", id="quatrieme")
    summary = ""
    if summary_div:
        summary = summary_div.get_text(strip=True)
    
    return ScrapeResult(
        numlivre=numlivre,
        title=title,
        author=author,
        summary=summary,
        success=bool(title),
    )


def scrape_book_details(numlivre: str, session: requests.Session, delay: float) -> ScrapeResult:
    """Scrape la fiche détaillée d'un livre."""
    url = f"{_BASE_URL}/livres/niourf.asp?numlivre={numlivre}"
    logger.info("Scraping livre numlivre=%s", numlivre)
    
    html = _fetch_with_delay(url, session, delay)
    if not html:
        return ScrapeResult(numlivre=numlivre, title="", author="", summary="", success=False, error="fetch_failed")
    
    return _parse_book_details(html, numlivre)


# ─────────────────────────────────────────────────────────────────────────────
# Base de données de la file d'attente
# ─────────────────────────────────────────────────────────────────────────────

_SCRAPING_DDL = """
CREATE TABLE IF NOT EXISTS scraping_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    numlivre      TEXT UNIQUE NOT NULL,
    url           TEXT NOT NULL,
    added_at      TEXT NOT NULL,
    scraped_at    TEXT,
    title         TEXT,
    author        TEXT,
    summary       TEXT,
    enriched_at   TEXT,
    year          INTEGER,
    month         INTEGER
);
CREATE INDEX IF NOT EXISTS idx_queue_pending ON scraping_queue(scraped_at IS NULL);
CREATE INDEX IF NOT EXISTS idx_queue_numlivre ON scraping_queue(numlivre);
"""


@contextmanager
def get_scraping_connection(db_path: Path) -> Generator:
    """Context manager pour la connexion à la base de scraping."""
    import sqlite3
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_scraping_queue(db_path: Path) -> None:
    """Initialise la table de file d'attente."""
    with get_scraping_connection(db_path) as conn:
        conn.executescript(_SCRAPING_DDL)
    logger.info("Scraping queue DB initialisée : %s", db_path)


def add_to_scraping_queue(conn, numlivre: str, url: str, year: int | None = None, month: int | None = None) -> bool:
    """Ajoute un livre à la file d'attente si pas déjà présent."""
    try:
        conn.execute(
            "INSERT OR IGNORE INTO scraping_queue (numlivre, url, added_at, year, month) VALUES (?, ?, ?, ?, ?)",
            (numlivre, url, datetime.now(timezone.utc).isoformat(), year, month),
        )
        return True
    except Exception as exc:
        logger.error("Erreur ajout file d'attente %s: %s", numlivre, exc)
        return False


def get_pending_books(conn, limit: int = 100) -> list[dict]:
    """Retourne les livres en attente de scraping."""
    rows = conn.execute(
        "SELECT id, numlivre, url, year FROM scraping_queue WHERE scraped_at IS NULL LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def clear_scraping_queue(db_path: Path) -> int:
    """Vide la file d'attente et retourne le nombre d'éléments supprimés."""
    with get_scraping_connection(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM scraping_queue").fetchone()[0]
        conn.execute("DELETE FROM scraping_queue")
    logger.info("File d'attente vidée : %d éléments supprimés", count)
    return count


def mark_scraped(conn, book_id: int, title: str, author: str, summary: str) -> None:
    """Marque un livre comme scrapé avec ses données."""
    conn.execute(
        """
        UPDATE scraping_queue
        SET scraped_at = ?, title = ?, author = ?, summary = ?
        WHERE id = ?
        """,
        (datetime.now(timezone.utc).isoformat(), title, author, summary, book_id),
    )


def mark_enriched(conn, numlivre: str) -> None:
    """Marque un livre comme enrichi (transféré vers catalogue)."""
    conn.execute(
        "UPDATE scraping_queue SET enriched_at = ? WHERE numlivre = ?",
        (datetime.now(timezone.utc).isoformat(), numlivre),
    )


def get_queue_stats(db_path: Path) -> dict:
    """Retourne les statistiques de la file d'attente."""
    with get_scraping_connection(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM scraping_queue").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM scraping_queue WHERE scraped_at IS NULL").fetchone()[0]
        scraped = conn.execute("SELECT COUNT(*) FROM scraping_queue WHERE scraped_at IS NOT NULL AND enriched_at IS NULL").fetchone()[0]
        enriched = conn.execute("SELECT COUNT(*) FROM scraping_queue WHERE enriched_at IS NOT NULL").fetchone()[0]
    return {"total": total, "pending": pending, "scraped": scraped, "enriched": enriched}


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions publiques principales
# ─────────────────────────────────────────────────────────────────────────────

def scrape_year_to_queue(
    year: int,
    session: requests.Session,
    delay: float,
    db_path: Path,
) -> int:
    """Scrape la page de parutions d'une année et ajoute les livres avec résumé à la file d'attente."""
    numlivres = _scrape_year_page(year, session, delay)
    added = 0
    
    with get_scraping_connection(db_path) as conn:
        for numlivre in numlivres:
            url = f"{_BASE_URL}/livres/niourf.asp?numlivre={numlivre}"
            result = add_to_scraping_queue(conn, numlivre, url, year=year)
            if result:
                added += 1
    
    logger.info("Année %d: %d livres ajoutés à la file d'attente", year, added)
    return added


def scrape_month_to_queue(
    year: int,
    month: int,
    session: requests.Session,
    delay: float,
    db_path: Path,
) -> int:
    """Scrape la page de parutions d'un mois et ajoute les livres avec résumé à la file d'attente."""
    numlivres = _scrape_month_page(year, month, session, delay)
    added = 0
    
    with get_scraping_connection(db_path) as conn:
        for numlivre in numlivres:
            url = f"{_BASE_URL}/livres/niourf.asp?numlivre={numlivre}"
            result = add_to_scraping_queue(conn, numlivre, url, year=year, month=month)
            if result:
                added += 1
    
    logger.info("Mois %d/%d: %d livres ajoutés à la file d'attente", month, year, added)
    return added


def initialize_scraping_queue(
    db_path: Path,
    start_year: int = 1950,
    end_year: int = 2025,
    delay: float = 2.0,
) -> int:
    """
    Initialise la file d'attente en scrapant toutes les années de start_year à end_year.
    
    À utiliser manuellement une seule fois pour le bootstrap initial.
    """
    init_scraping_queue(db_path)
    
    session = requests.Session()
    total_added = 0
    
    for year in range(start_year, end_year + 1):
        added = scrape_year_to_queue(year, session, delay, db_path)
        total_added += added
    
    return total_added


def process_month_scraping(
    year: int,
    month: int,
    db_path: Path,
    delay: float = 2.0,
) -> int:
    """
    Scrape les livres d'un mois spécifique et les ajoute à la file d'attente.
    
    Pour être schedulée le 10 de chaque mois pour analyser le mois précédent.
    """
    session = requests.Session()
    return scrape_month_to_queue(year, month, session, delay, db_path)


def process_scraping_queue(
    queue_db_path: Path,
    catalogue_db_path: Path,
    delay: float = 2.0,
    batch_size: int = 50,
) -> int:
    """
    Vide la file d'attente en scrapant chaque livre et l'ajoutant au catalogue.
    
    Retourne le nombre de livres traités et ajoutés au catalogue.
    """
    from db.catalogue_db import init_catalogue, upsert_book, mark_enriched as mark_cat_enriched, get_connection as get_catalogue_connection
    from enrichment import generate_tags_with_llm
    
    init_catalogue(catalogue_db_path)
    
    session = requests.Session()
    processed = 0
    
    while True:
        with get_scraping_connection(queue_db_path) as queue_conn:
            pending = get_pending_books(queue_conn, limit=batch_size)
            if not pending:
                logger.info("Aucun livre en attente dans la file d'attente")
                break
        
        for book in pending:
            result = scrape_book_details(book["numlivre"], session, delay)
            
            with get_scraping_connection(queue_db_path) as queue_conn:
                mark_scraped(
                    queue_conn,
                    book["id"],
                    result.title,
                    result.author,
                    result.summary,
                )
            
            if result.success and result.summary:
                time.sleep(1.0)
                tags = generate_tags_with_llm(result.title, result.author, result.summary)
                
                book_record = {
                    "id": f"noosfere-{result.numlivre}",
                    "title": result.title,
                    "author": result.author,
                    "year_published": book.get("year"),
                    "source": "noosfere",
                }
                
                with get_catalogue_connection(catalogue_db_path) as cat_conn:
                    upsert_book(cat_conn, book_record)
                    mark_cat_enriched(
                        cat_conn,
                        book_record["id"],
                        description=result.summary,
                        tags=tags,
                        enriched_at=datetime.now(timezone.utc).isoformat(),
                    )
                
                with get_scraping_connection(queue_db_path) as queue_conn:
                    mark_enriched(queue_conn, result.numlivre)
                
                processed += 1
                logger.info("Livre traité et ajouté au catalogue: %s", result.title)
            else:
                logger.warning("Livre non scrapé ou sans résumé: %s", book["numlivre"])
    
    return processed


# ─────────────────────────────────────────────────────────────────────────────
# Debug : Scraper un seul livre avec logs détaillés
# ─────────────────────────────────────────────────────────────────────────────

def debug_scrape_single_book(
    numlivre: str,
    catalogue_db_path: Path,
) -> ScrapeResult:
    """
    Scraper un seul livre depuis Noosfere avec logs de debug détaillés.
    
    Utile pour tester le parsing HTML et le flow d'enrichissement.
    """
    from db.catalogue_db import init_catalogue, upsert_book, mark_enriched as mark_cat_enriched, get_connection as get_catalogue_connection
    from enrichment import generate_tags_with_llm
    
    logger.info("=" * 60)
    logger.info("🔍 DEBUG SCRAPING - Livre numlivre=%s", numlivre)
    logger.info("=" * 60)
    
    init_catalogue(catalogue_db_path)
    
    session = requests.Session()
    result = scrape_book_details(numlivre, session, 0.0)  # Pas de délai en debug
    
    logger.info("📄 Résultat scraped: success=%s", result.success)
    logger.info("📌 Titre: '%s'", result.title)
    logger.info("📌 Auteur: '%s'", result.author)
    logger.info("📌 Résumé (premiers 200 car): '%s...'", result.summary[:200] if result.summary else "")
    
    if result.success and result.summary:
        logger.info("🏷️ Appel au LLM pour génération de tags...")
        tags = generate_tags_with_llm(result.title, result.author, result.summary)
        logger.info("✅ Tags générés: %s", tags)
        
        book_record = {
            "id": f"noosfere-{result.numlivre}",
            "title": result.title,
            "author": result.author,
            "year_published": None,
            "source": "noosfere",
        }
        
        with get_catalogue_connection(catalogue_db_path) as cat_conn:
            logger.info("💾 Insertion dans catalogue.db...")
            upsert_book(cat_conn, book_record)
            mark_cat_enriched(
                cat_conn,
                book_record["id"],
                description=result.summary,
                tags=tags,
                enriched_at=datetime.now(timezone.utc).isoformat(),
            )
        logger.info("✅ Livre ajouté au catalogue avec succès")
    else:
        logger.warning("❌ Échec du scraping ou pas de résumé")
    
    logger.info("=" * 60)
    return result
