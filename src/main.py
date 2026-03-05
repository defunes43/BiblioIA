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


def _print_reading_profile(df) -> None:  # type: ignore[no-untyped-def]
    """Affiche un tableau récapitulatif du profil de lecture pondéré."""
    try:
        from tabulate import tabulate  # type: ignore[import-untyped]

        top_books = (
            df[["Title", "Author", "My Rating", "bias_corrected_score"]]
            .sort_values("bias_corrected_score", ascending=False)
            .head(10)
            .rename(
                columns={
                    "Title": "Titre",
                    "Author": "Auteur",
                    "My Rating": "Note",
                    "bias_corrected_score": "Score corrigé",
                }
            )
        )
        top_books["Score corrigé"] = top_books["Score corrigé"].map("{:.3f}".format)

        print("\n" + "=" * 60)
        print("  📊 Profil de lecture (top 10 après correction des biais)")
        print("=" * 60)
        print(tabulate(top_books, headers="keys", tablefmt="rounded_outline", showindex=False))

        # Auteurs les plus représentés
        top_authors = (
            df.groupby("Author")["bias_corrected_score"]
            .mean()
            .sort_values(ascending=False)
            .head(5)
            .reset_index()
        )
        top_authors["bias_corrected_score"] = top_authors["bias_corrected_score"].map("{:.3f}".format)
        top_authors = top_authors.rename(columns={"Author": "Auteur", "bias_corrected_score": "Score moyen"})

        print("\n  🏆 Auteurs préférés (score moyen pondéré)")
        print(tabulate(top_authors, headers="keys", tablefmt="rounded_outline", showindex=False))
        print()

    except ImportError:
        logger.warning("tabulate non installé, résumé simplifié.")
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
