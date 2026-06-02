from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent import _build_profile_df  # noqa: E402


def test_build_profile_df_uses_functional_score_when_available() -> None:
    df = pd.DataFrame(
        {
            "Micro-genre": ["Cyberpunk, Space opera", "Cyberpunk", "High fantasy"],
            "bias_corrected_score": [0.2, 0.3, 0.4],
            "functional_relevance_score": [0.8, 0.6, 0.4],
        }
    )
    profile = _build_profile_df(df)

    assert {"Micro_genre", "score_sum", "score_mean", "books_count", "profile_priority"} <= set(profile.columns)
    first_tag = profile.iloc[0]["Micro_genre"]
    assert first_tag == "Cyberpunk"


def test_build_profile_df_filters_noise_tags() -> None:
    df = pd.DataFrame(
        {
            "Micro-genre": ["Non classifié", "Erreur LLM", "Space opera"],
            "bias_corrected_score": [0.4, 0.5, 0.6],
        }
    )
    profile = _build_profile_df(df)
    assert "Space opera" in profile["Micro_genre"].values
    assert "Non classifié" not in profile["Micro_genre"].values
