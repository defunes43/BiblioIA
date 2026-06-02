"""
tests/test_preprocessing.py — Tests unitaires du pipeline de prétraitement BiblioIA.

Chaque test est autonome et utilise des DataFrames synthétiques (pas de CSV réel requis).
"""

from __future__ import annotations

import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

# Assure que src/ est dans le path Python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from preprocessing import (
    _parse_dates_to_years,
    apply_micro_genre_relevance_boost,
    apply_author_bias_correction,
    apply_older_books_rule,
    apply_recency_bias_correction,
    compute_bias_corrected_score,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _make_base_df() -> pd.DataFrame:
    """Crée un DataFrame minimal simulant des données Goodreads nettoyées."""
    today = pd.Timestamp(date.today())
    return pd.DataFrame(
        {
            "Book Id": ["1", "2", "3", "4", "5"],
            "Title": ["Livre A", "Livre B", "Livre C", "Livre D", "Livre E"],
            "Author": ["Auteur X", "Auteur X", "Auteur X", "Auteur Y", "Auteur Z"],
            "My Rating": [5.0, 4.0, 3.0, 5.0, 4.0],
            "Average Rating": [4.5, 4.2, 3.8, 4.7, 4.3],
            "Bookshelves": ["fiction", "older_books, fantasy", "fantasy", "sci-fi", "thriller"],
            "Date Read": [
                today - timedelta(days=30),   # récent
                today - timedelta(days=500),  # il y a ~1.5 ans
                today - timedelta(days=3000), # il y a ~8 ans
                today - timedelta(days=100),  # récent
                pd.NaT,                       # date manquante
            ],
            "Date Added": [
                today - timedelta(days=60),
                today - timedelta(days=600),
                today - timedelta(days=3100),
                today - timedelta(days=150),
                today - timedelta(days=200),
            ],
            "Category": [
                "Fiction",
                "Fiction",
                "Fiction",
                "Fiction",
                "Fiction",
            ],
            "Genre": [
                "Fantasy",
                "Fantasy",
                "Fantasy",
                "Science-Fiction",
                "Thriller",
            ],
            "Micro-genre": [
                "Epic Fantasy",
                "Urban Fantasy",
                "Gothic Fantasy",
                "Cyberpunk",
                "Medical Thriller",
            ],
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Règle older_books
# ─────────────────────────────────────────────────────────────────────────────


def test_older_books_rule_forces_old_date() -> None:
    """Les livres avec 'older_books' dans Bookshelves doivent avoir une Date Read >= 10 ans."""
    df = _make_base_df()
    df = _parse_dates_to_years(df)  # Ajoute action_year
    df_result = apply_older_books_rule(df)

    cutoff = date.today().year - 10

    mask = df_result["Bookshelves"].str.contains("older_books", case=False, na=False)
    for _, row in df_result[mask].iterrows():
        assert row["action_year"] <= cutoff, (
            f"Le livre older_books '{row['Title']}' devrait avoir action_year <= {cutoff}, "
            f"mais a {row['action_year']}."
        )


def test_older_books_rule_preserves_older_dates() -> None:
    """Si un livre older_books a déjà une Date Read assez ancienne, elle ne doit pas changer."""
    df = _make_base_df()
    # Force Livre B (older_books) à être lu il y a 15 ans
    ancient_date = pd.Timestamp(date.today() - timedelta(days=365 * 15))
    df.loc[df["Title"] == "Livre B", "Date Read"] = ancient_date

    df = _parse_dates_to_years(df)
    df_result = apply_older_books_rule(df)

    livre_b_year = df_result.loc[df_result["Title"] == "Livre B", "action_year"].iloc[0]
    assert livre_b_year <= (date.today().year - 15)


def test_older_books_rule_no_tagged_books_unchanged() -> None:
    """Sans livres marqués, le DataFrame ne doit pas être modifié."""
    df = _make_base_df()
    df["Bookshelves"] = "fiction"  # supprime tout "older_books"
    df = _parse_dates_to_years(df)
    years_before = df["action_year"].copy()
    df_result = apply_older_books_rule(df)
    pd.testing.assert_series_equal(df_result["action_year"], years_before)


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Biais auteur
# ─────────────────────────────────────────────────────────────────────────────


def test_author_bias_weight_inversely_proportional() -> None:
    """Auteur X (3 livres) doit avoir un poids plus faible que Auteur Y ou Z (1 livre)."""
    df = _make_base_df()
    df_result = apply_author_bias_correction(df)

    weight_x = df_result.loc[df_result["Author"] == "Auteur X", "author_weight"].iloc[0]
    weight_y = df_result.loc[df_result["Author"] == "Auteur Y", "author_weight"].iloc[0]

    assert weight_x < weight_y
    assert math.isclose(weight_x, 1/3, rel_tol=1e-6)
    assert math.isclose(weight_y, 1.0, rel_tol=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — Biais de nouveauté
# ─────────────────────────────────────────────────────────────────────────────


def test_recency_bias_recent_higher_than_old() -> None:
    """Un livre récent (30 jours) doit avoir un poids de nouveauté > livre ancien (3000 jours)."""
    df = _make_base_df()
    df = _parse_dates_to_years(df)
    df_result = apply_recency_bias_correction(df)

    recent_weight = df_result.loc[df_result["Title"] == "Livre A", "recency_weight"].iloc[0]
    old_weight = df_result.loc[df_result["Title"] == "Livre C", "recency_weight"].iloc[0]

    assert recent_weight > old_weight, (
        f"Poids récent ({recent_weight:.3f}) devrait > poids ancien ({old_weight:.3f})."
    )


def test_recency_bias_weights_in_range() -> None:
    """Tous les poids de nouveauté doivent être entre 0 et 1."""
    df = _make_base_df()
    df = _parse_dates_to_years(df)
    df_result = apply_recency_bias_correction(df)
    assert (df_result["recency_weight"] >= 0).all()
    assert (df_result["recency_weight"] <= 1).all()


def test_recency_bias_missing_date_gets_neutral_weight() -> None:
    """Un livre sans date (NaT) doit recevoir le poids lié à l'année d'ajout (priorité après Date Read)."""
    df = _make_base_df()
    df = _parse_dates_to_years(df)
    df_result = apply_recency_bias_correction(df)

    # Livre E a Date Read = NaT, mais Date Added = 200 jours ago. 
    # _parse_dates_to_years remplit action_year avec Date Added.
    expected_year = df.loc[df["Title"] == "Livre E", "action_year"].iloc[0]
    years_ago = date.today().year - expected_year
    expected_weight = math.exp(-0.2 * years_ago)

    nat_weight = df_result.loc[df_result["Title"] == "Livre E", "recency_weight"].iloc[0]
    assert math.isclose(nat_weight, expected_weight, rel_tol=1e-6), (
        f"Poids attendu {expected_weight} pour date manquante, obtenu {nat_weight}."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — Dates manquantes (stabilité du pipeline)
# ─────────────────────────────────────────────────────────────────────────────


def test_missing_dates_do_not_crash_pipeline() -> None:
    """Un DataFrame avec toutes les dates manquantes doit être traitable sans exception."""
    df = _make_base_df()
    df["Date Read"] = pd.NaT
    df["Date Added"] = pd.NaT

    try:
        df = _parse_dates_to_years(df)
        df = apply_older_books_rule(df)
        df = apply_author_bias_correction(df)
        df = apply_recency_bias_correction(df)
        df = compute_bias_corrected_score(df)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"Le pipeline a planté sur des dates manquantes : {exc}")

    assert "bias_corrected_score" in df.columns


def test_bias_corrected_score_normalized() -> None:
    """Le score global doit être normalisé entre 0 et 1."""
    df = _make_base_df()
    df = _parse_dates_to_years(df)
    df = apply_author_bias_correction(df)
    df = apply_recency_bias_correction(df)
    df = compute_bias_corrected_score(df)

    assert df["bias_corrected_score"].min() >= 0.0
    assert df["bias_corrected_score"].max() <= 1.0


def test_micro_genre_boost_adds_functional_score_column() -> None:
    """Le bonus micro-genre doit produire une colonne de score fonctionnel bornée."""
    df = _make_base_df()
    df = _parse_dates_to_years(df)
    df = apply_author_bias_correction(df)
    df = apply_recency_bias_correction(df)
    df = compute_bias_corrected_score(df)
    df = apply_micro_genre_relevance_boost(df)

    assert "functional_relevance_score" in df.columns
    assert (df["functional_relevance_score"] >= 0.0).all()
    assert (df["functional_relevance_score"] <= 1.0).all()


def test_micro_genre_boost_preserves_ordering_signal() -> None:
    """Le boost ne doit pas inverser complètement la logique de score historique."""
    df = _make_base_df()
    df = _parse_dates_to_years(df)
    df = apply_author_bias_correction(df)
    df = apply_recency_bias_correction(df)
    df = compute_bias_corrected_score(df)
    df = apply_micro_genre_relevance_boost(df)

    top_bias = df.sort_values("bias_corrected_score", ascending=False)["Title"].head(2).tolist()
    top_func = df.sort_values("functional_relevance_score", ascending=False)["Title"].head(3).tolist()
    assert any(title in top_func for title in top_bias)
