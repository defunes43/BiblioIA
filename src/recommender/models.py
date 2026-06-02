"""
models.py — Structures de données pour le recommandeur BiblioIA.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BookRecommendation:
    """Un livre recommandé avec son score de pertinence et le détail du matching."""

    title: str
    author: str
    score: float
    matching_tags: list[str] = field(default_factory=list)
    ebook_link: str = ""
    title_fr: str | None = None
    year_published: int | None = None

    @property
    def display_title(self) -> str:
        """Retourne le meilleur titre à afficher (FR si disponible)."""
        return self.title_fr if self.title_fr and self.title_fr != self.title else self.title

    @property
    def score_pct(self) -> int:
        """Score normalisé en pourcentage pour l'affichage."""
        return min(100, int(self.score * 100))
