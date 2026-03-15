"""
main.py — Point d'entrée de BiblioIA.

Orchestre le pipeline complet :
1. Validation de la configuration (.env)
2. Chargement et nettoyage du CSV Goodreads
3. Affichage d'un résumé du profil de lecture
4. Initialisation de l'agent LangChain
5. Lancement de la boucle interactive
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

# Assure que le dossier src/ est dans le path pour les imports relatifs
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402 — doit être importé avant les autres modules
from agent import build_agent, run_interactive_loop  # noqa: E402
from preprocessing import load_and_prepare  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Résumé du profil de lecture
# ─────────────────────────────────────────────────────────────────────────────

def _print_reading_profile(df: pd.DataFrame) -> None:
    """Affiche un tableau récapitulatif du profil de lecture pondéré."""
    try:
        from tabulate import tabulate  # type: ignore[import-untyped]

        # 1. Top 10 des livres ayant le plus de "poids" dans le profil
        top_books = (
            df[["Title", "Author", "bias_corrected_score"]]
            .sort_values("bias_corrected_score", ascending=False)
            .head(10)
            .rename(
                columns={
                    "Title": "Titre",
                    "Author": "Auteur",
                    "bias_corrected_score": "Score corrigé",
                }
            )
        )
        top_books["Score corrigé"] = top_books["Score corrigé"].map("{:.3f}".format)

        print("\n" + "=" * 70)
        print("  📊 Profil de lecture (Top 10 livres structurants)")
        print("=" * 70)
        print(tabulate(top_books, headers="keys", tablefmt="rounded_outline", showindex=False))

        # 2. Tags/Micro-genres préférés (Extraction depuis la chaîne séparée par des virgules)
        # On ignore les lignes vides ou non classifiées
        valid_genres = df[~df["Micro-genre"].isin(["", "Non classifié", "NaN"])].copy()
        
        if not valid_genres.empty:
            # Transformation : "tag1, tag2" -> ["tag1", "tag2"]
            valid_genres["tag_list"] = valid_genres["Micro-genre"].apply(
                lambda x: [tag.strip().capitalize() for tag in str(x).split(",") if tag.strip()]
            )
            
            # Explode permet de créer une ligne par tag pour le calcul
            exploded = valid_genres.explode("tag_list")
            
            # Calcul du score moyen et du nombre d'occurrences pour chaque tag
            top_tags = (
                exploded.groupby("tag_list")
                .agg(
                    Score_moyen=("bias_corrected_score", "mean"),
                    Occurrences=("Book Id", "count")
                )
                .sort_values(by="Score_moyen", ascending=False)
                .head(10)
                .reset_index()
                .rename(columns={"tag_list": "Tag (Micro-genre)"})
            )
            
            top_tags["Score_moyen"] = top_tags["Score_moyen"].map("{:.3f}".format)

            print("\n  🏆 Tags préférés (OpenLibrary - pondérés par score)")
            print(tabulate(top_tags, headers="keys", tablefmt="rounded_outline", showindex=False))
            print()

    except ImportError:
        logger.warning("Bibliothèque 'tabulate' non installée, affichage simplifié.")
        print(f"\n📚 {len(df)} livres chargés.")
        top = df.nlargest(5, "bias_corrected_score")[["Title", "Author"]]
        for _, row in top.iterrows():
            print(f"  • {row['Title']} — {row['Author']}")
        print()


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Point d'entrée principal de BiblioIA."""
    # 1. Validation de la configuration
    try:
        config.validate()
    except EnvironmentError as exc:
        logger.critical("%s", exc)
        sys.exit(1)

    # 2. Chargement et nettoyage du CSV
    try:
        df = load_and_prepare()
    except FileNotFoundError as exc:
        logger.critical("%s", exc)
        sys.exit(1)
    except ValueError as exc:
        logger.critical("Erreur de format CSV : %s", exc)
        sys.exit(1)

    if df.empty:
        logger.critical("Aucun livre 'read' trouvé dans le CSV. Vérifie ton export Goodreads.")
        sys.exit(1)

    # 3. Résumé du profil
    _print_reading_profile(df)

    # 4. Initialisation de l'agent
    try:
        agent = build_agent(df)
    except ValueError as exc:
        logger.critical("%s", exc)
        sys.exit(1)

    # 5. Boucle interactive
    run_interactive_loop(agent)

if __name__ == "__main__":
    main()