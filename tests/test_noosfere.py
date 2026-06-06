"""
tests/test_noosfere.py — Tests unitaires du scraper Noosfere.

Chaque test est autonome et utilise des HTML synthétiques (pas de requêtes réelles).
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from catalogue.sources.noosfere import (
    _find_books_with_summary,
    _parse_book_details,
    ScrapeResult,
    init_scraping_queue,
    add_to_scraping_queue,
    get_pending_books,
    clear_scraping_queue,
    get_queue_stats,
    get_scraping_connection,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_year_html() -> str:
    """HTML synthétique d'une page de parutions annuelle."""
    return """
    <table class="noocadre_pad0" cellpadding="0" cellspacing="0" width="100%">
      <tbody><tr><td valign="top">   
<div style="padding:10px">
<div class="AuteurNiourf" id="H"><a href="/livres/editeur.asp?numediteur=2078944448">HETZEL</a></div>
<span style="display: inline-block; width:5em"></span>
<span class="ficheNiourf"><span style="width:8em;display:inline-block;">avril : </span>
<a href="/livres/niourf.asp?numlivre=2146591788">Magasin d'education et de recreation n° 15</a>, REVUE
</span>&nbsp;<span class="cadre1" title="Présence d'une image">I</span>&nbsp;
<span class="cadre1" title="Présence d'un résumé">R</span><br>
</div>
</td></tr></tbody></table>
    """


@pytest.fixture
def sample_book_html_no_summary() -> str:
    """HTML synthétique d'un livre SANS résumé."""
    return """
    <tr>
<span class="ficheNiourf"><a href="/livres/niourf.asp?numlivre=123456789">Livre sans résumé</a></span>
<span class="cadre1" title="Présence d'une image">I</span>
    </tr>
    """


@pytest.fixture
def sample_book_details_html() -> str:
    """HTML synthétique d'une fiche livre complète."""
    return """
    <html><body>
    <span class="TitreNiourf">Le Titre du Livre</span>
    <span class="AuteurNiourf"><a href="/auteur.asp?numauteur=123">Jean Dupont</a></span>
    <div id="quatrieme">
        C'est l'histoire fantastastique d'un héros qui voyage dans l'espace...
    </div>
    </body></html>
    """


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Chemin vers une base SQLite temporaire."""
    return tmp_path / "test_scraping_queue.db"


# ─────────────────────────────────────────────────────────────────────────────
# Tests d'extraction des livres avec résumé
# ─────────────────────────────────────────────────────────────────────────────

def test_find_books_with_summary_extracts_correct_ids(sample_year_html: str) -> None:
    """Doit extraire les numlivres des livres marqués comme ayant un résumé."""
    numlivres = _find_books_with_summary(sample_year_html)
    assert "2146591788" in numlivres


def test_find_books_with_summary_ignores_books_without_summary(sample_book_html_no_summary: str) -> None:
    """Doit ignorer les livres qui n'ont pas le marqueur de résumé."""
    numlivres = _find_books_with_summary(sample_book_html_no_summary)
    assert "123456789" not in numlivres


def test_find_books_with_summary_handles_empty_html() -> None:
    """Doit gérer un HTML vide sans erreur."""
    numlivres = _find_books_with_summary("")
    assert numlivres == []


# ─────────────────────────────────────────────────────────────────────────────
# Tests de parsing des fiches livres
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_book_details_extracts_title(sample_book_details_html: str) -> None:
    """Doit extraire le titre depuis la balise TitreNiourf."""
    result = _parse_book_details(sample_book_details_html, "12345")
    assert result.title == "Le Titre du Livre"
    assert result.success is True


def test_parse_book_details_extracts_author(sample_book_details_html: str) -> None:
    """Doit extraire l'auteur depuis la balise AuteurNiourf."""
    result = _parse_book_details(sample_book_details_html, "12345")
    assert result.author == "Jean Dupont"


def test_parse_book_details_extracts_summary(sample_book_details_html: str) -> None:
    """Doit extraire le résumé depuis la div quatrieme."""
    result = _parse_book_details(sample_book_details_html, "12345")
    assert "histoire fantastastique" in result.summary


def test_parse_book_details_handles_missing_elements() -> None:
    """Doit gérer les éléments manquants sans crash."""
    result = _parse_book_details("<html><body></body></html>", "999")
    assert result.title == ""
    assert result.author == ""
    assert result.summary == ""
    assert result.success is False


# ─────────────────────────────────────────────────────────────────────────────
# Tests de la base de données de file d'attente
# ─────────────────────────────────────────────────────────────────────────────

def test_init_scraping_queue_creates_tables(temp_db_path: Path) -> None:
    """Doit créer la table scraping_queue."""
    init_scraping_queue(temp_db_path)
    
    assert temp_db_path.exists()
    
    with get_scraping_connection(temp_db_path) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scraping_queue'"
        ).fetchone()
        assert tables is not None


def test_add_to_scraping_queue_inserts_record(temp_db_path: Path) -> None:
    """Doit insérer un livre dans la file d'attente."""
    init_scraping_queue(temp_db_path)
    
    with get_scraping_connection(temp_db_path) as conn:
        add_to_scraping_queue(conn, "12345", "https://www.noosfere.org/livres/niourf.asp?numlivre=12345", year=2023, month=5)
        
        row = conn.execute(
            "SELECT numlivre, url, year, month FROM scraping_queue WHERE numlivre = ?",
            ("12345",),
        ).fetchone()
        
        assert row is not None
        assert row["numlivre"] == "12345"
        assert row["year"] == 2023
        assert row["month"] == 5


def test_add_to_scraping_queue_ignores_duplicates(temp_db_path: Path) -> None:
    """Doit ignorer les doublons."""
    init_scraping_queue(temp_db_path)
    
    with get_scraping_connection(temp_db_path) as conn:
        add_to_scraping_queue(conn, "12345", "url1")
        add_to_scraping_queue(conn, "12345", "url2")
        
        count = conn.execute("SELECT COUNT(*) FROM scraping_queue").fetchone()[0]
        assert count == 1


def test_get_pending_books_returns_unscraped(temp_db_path: Path) -> None:
    """Doit retourner uniquement les livres non encore scrapés."""
    init_scraping_queue(temp_db_path)
    
    with get_scraping_connection(temp_db_path) as conn:
        add_to_scraping_queue(conn, "111", "url1")
        add_to_scraping_queue(conn, "222", "url2")
        conn.execute(
            "UPDATE scraping_queue SET scraped_at = ? WHERE numlivre = ?",
            (datetime.now(timezone.utc).isoformat(), "222"),
        )
        
        pending = get_pending_books(conn)
        assert len(pending) == 1
        assert pending[0]["numlivre"] == "111"


def test_clear_scraping_queue_removes_all(temp_db_path: Path) -> None:
    """Doit vider complètement la file d'attente."""
    init_scraping_queue(temp_db_path)
    
    with get_scraping_connection(temp_db_path) as conn:
        add_to_scraping_queue(conn, "111", "url1")
        add_to_scraping_queue(conn, "222", "url2")
    
    cleared = clear_scraping_queue(temp_db_path)
    assert cleared == 2
    
    with get_scraping_connection(temp_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM scraping_queue").fetchone()[0]
        assert count == 0


def test_get_queue_stats_returns_counts(temp_db_path: Path) -> None:
    """Doit retourner les statistiques de la file d'attente."""
    init_scraping_queue(temp_db_path)
    
    with get_scraping_connection(temp_db_path) as conn:
        add_to_scraping_queue(conn, "111", "url1")
        add_to_scraping_queue(conn, "222", "url2")
    
    stats = get_queue_stats(temp_db_path)
    assert stats["total"] == 2
    assert stats["pending"] == 2
    assert stats["scraped"] == 0
    assert stats["enriched"] == 0

# ─────────────────────────────────────────────────────────────────────────────
# Test import de la fonction debug
# ─────────────────────────────────────────────────────────────────────────────

def test_debug_scrape_single_book_is_callable() -> None:
    """Vérifie que la fonction debug_scrape_single_book existe et est appelable."""
    from catalogue.sources.noosfere import debug_scrape_single_book
    import inspect
    assert callable(debug_scrape_single_book)
    sig = inspect.signature(debug_scrape_single_book)
    params = list(sig.parameters.keys())
    assert "numlivre" in params
    assert "catalogue_db_path" in params
