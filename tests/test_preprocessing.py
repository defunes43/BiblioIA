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
    apply_arsac_rule,
    apply_author_bias_correction,
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
            "Bookshelves": ["fiction", "arsac, fantasy", "fantasy", "sci-fi", "thriller"],
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
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Règle arsac
# ─────────────────────────────────────────────────────────────────────────────


def test_arsac_rule_forces_old_date() -> None:
    """Les livres avec 'arsac' dans Bookshelves doivent avoir une Date Read >= 10 ans."""
    df = _make_base_df()
    df_result = apply_arsac_rule(df)

    cutoff = pd.Timestamp(date.today() - timedelta(days=365 * 10))

    arsac_mask = df_result["Bookshelves"].str.contains("arsac", case=False, na=False)
    for _, row in df_result[arsac_mask].iterrows():
        assert row["Date Read"] <= cutoff, (
            f"Le livre arsac '{row['Title']}' devrait avoir Date Read <= {cutoff}, "
            f"mais a {row['Date Read']}."
        )


def test_arsac_rule_preserves_older_dates() -> None:
    """Si un livre arsac a déjà une Date Read assez ancienne, elle ne doit pas changer."""
    df = _make_base_df()
    # Force Livre B (arsac) à être lu il y a 15 ans
    ancient_date = pd.Timestamp(date.today() - timedelta(days=365 * 15))
    df.loc[df["Title"] == "Livre B", "Date Read"] = ancient_date

    df_result = apply_arsac_rule(df)

    livre_b_date = df_result.loc[df_result["Title"] == "Livre B", "Date Read"].iloc[0]
    assert livre_b_date == ancient_date, "Une date déjà ancienne ne doit pas être modifiée."


def test_arsac_rule_no_arsac_books_unchanged() -> None:
    """Sans livres arsac, le DataFrame ne doit pas être modifié."""
    df = _make_base_df()
    df["Bookshelves"] = "fiction"  # supprime tout "arsac"
    dates_before = df["Date Read"].copy()
    df_result = apply_arsac_rule(df)
    pd.testing.assert_series_equal(df_result["Date Read"], dates_before)


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Biais auteur
# ─────────────────────────────────────────────────────────────────────────────


def test_author_bias_weight_inversely_proportional() -> None:
    """Auteur X (3 livres) doit avoir un poids ≈ 1/3, Auteur Y et Z un poids = 1."""
    df = _make_base_df()
    df_result = apply_author_bias_correction(df)

    x_weight = df_result.loc[df_result["Author"] == "Auteur X", "author_weight"].iloc[0]
    y_weight = df_result.loc[df_result["Author"] == "Auteur Y", "author_weight"].iloc[0]
    z_weight = df_result.loc[df_result["Author"] == "Auteur Z", "author_weight"].iloc[0]

    assert math.isclose(x_weight, 1 / 3, rel_tol=1e-6), f"Poids X attendu 1/3, obtenu {x_weight}"
    assert math.isclose(y_weight, 1.0, rel_tol=1e-6), f"Poids Y attendu 1.0, obtenu {y_weight}"
    assert math.isclose(z_weight, 1.0, rel_tol=1e-6), f"Poids Z attendu 1.0, obtenu {z_weight}"


def test_author_bias_weight_all_positive() -> None:
    """Tous les poids auteur doivent être strictement positifs."""
    df = _make_base_df()
    df_result = apply_author_bias_correction(df)
    assert (df_result["author_weight"] > 0).all(), "Des poids nuls ou négatifs détectés !"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — Biais de nouveauté
# ─────────────────────────────────────────────────────────────────────────────


def test_recency_bias_recent_higher_than_old() -> None:
    """Un livre récent (30 jours) doit avoir un poids de nouveauté > livre ancien (3000 jours)."""
    df = _make_base_df()
    df_result = apply_recency_bias_correction(df)

    recent_weight = df_result.loc[df_result["Title"] == "Livre A", "recency_weight"].iloc[0]
    old_weight = df_result.loc[df_result["Title"] == "Livre C", "recency_weight"].iloc[0]

    assert recent_weight > old_weight, (
        f"Poids récent ({recent_weight:.3f}) devrait > poids ancien ({old_weight:.3f})."
    )


def test_recency_bias_weights_in_range() -> None:
    """Tous les poids de nouveauté doivent être entre 0 et 1."""
    df = _make_base_df()
    df_result = apply_recency_bias_correction(df)
    assert (df_result["recency_weight"] >= 0).all()
    assert (df_result["recency_weight"] <= 1).all()


def test_recency_bias_missing_date_gets_neutral_weight() -> None:
    """Un livre sans date (NaT) doit recevoir le poids neutre de 0.5."""
    df = _make_base_df()
    df_result = apply_recency_bias_correction(df)

    nat_weight = df_result.loc[df_result["Title"] == "Livre E", "recency_weight"].iloc[0]
    assert math.isclose(nat_weight, 0.5, rel_tol=1e-6), (
        f"Poids neutre attendu 0.5 pour date manquante, obtenu {nat_weight}."
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
        df = apply_arsac_rule(df)
        df = apply_author_bias_correction(df)
        df = apply_recency_bias_correction(df)
        df = compute_bias_corrected_score(df)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"Le pipeline a planté sur des dates manquantes : {exc}")

    assert "bias_corrected_score" in df.columns


def test_bias_corrected_score_normalized() -> None:
    """Le score global doit être normalisé entre 0 et 1."""
    df = _make_base_df()
    df = apply_author_bias_correction(df)
    df = apply_recency_bias_correction(df)
    df = compute_bias_corrected_score(df)

    assert df["bias_corrected_score"].min() >= 0.0
    assert df["bias_corrected_score"].max() <= 1.0
