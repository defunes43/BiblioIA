"""
main.py — Point d'entrée CLI de BiblioIA v2.

Commandes disponibles :
  build-catalogue   Construit ou met à jour le catalogue SFF (tâche longue)
  update-profile    Retraite l'export Goodreads CSV et reconstruit le profil
  recommend         Affiche le Top N recommandations (instantané)
  status            Affiche les statistiques catalogue + profil

Exemples :
  python src/main.py build-catalogue
  python src/main.py update-profile
  python src/main.py recommend
  python src/main.py recommend --genre "Space Opera" --n 10
  python src/main.py status
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
# Permet les imports absolus depuis src/ quel que soit le répertoire de lancement.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402 — doit être importé avant tout autre module BiblioIA

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Imports lazy (après config) ───────────────────────────────────────────────
# Importés ici pour éviter les effets de bord au chargement du module.

def _get_rich():
    """Importe rich — lève une erreur claire si absent."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich import box
        return Console(), Table, Panel, box
    except ImportError:
        print("❌ 'rich' n'est pas installé. Lance : pip install rich")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Commande : build-catalogue
# ─────────────────────────────────────────────────────────────────────────────

def cmd_build_catalogue(args: argparse.Namespace) -> None:
    """Lance le pipeline complet de construction du catalogue SFF."""
    from catalogue.builder import build_catalogue

    console, Table, Panel, box = _get_rich()
    console.print(Panel(
        "[bold cyan]BiblioIA v2[/] — Construction du catalogue SFF\n"
        f"[dim]DB cible : {config.CATALOGUE_DB_PATH}[/]",
        border_style="cyan",
    ))

    build_catalogue(
        db_path=config.CATALOGUE_DB_PATH,
        max_per_subject=config.MAX_BOOKS_PER_SUBJECT,
        max_workers=config.ENRICHMENT_MAX_WORKERS,
    )

    console.print("\n[bold green]✅ Catalogue construit avec succès.[/]")
    console.print(f"[dim]Lance 'python src/main.py status' pour voir les statistiques.[/]")


# ─────────────────────────────────────────────────────────────────────────────
# Commande : update-profile
# ─────────────────────────────────────────────────────────────────────────────

def cmd_update_profile(args: argparse.Namespace) -> None:
    """Retraite le CSV Goodreads et met à jour le profil utilisateur."""
    from profile_builder import build_profile

    console, Table, Panel, box = _get_rich()
    console.print(Panel(
        "[bold cyan]BiblioIA v2[/] — Mise à jour du profil\n"
        f"[dim]CSV source : {config.CSV_PATH}[/]\n"
        f"[dim]DB cible   : {config.PROFILE_DB_PATH}[/]",
        border_style="cyan",
    ))

    try:
        rebuilt = build_profile(
            csv_path=config.CSV_PATH,
            profile_db=config.PROFILE_DB_PATH,
            force=args.force,
        )
    except FileNotFoundError as exc:
        console.print(f"[bold red]❌ {exc}[/]")
        sys.exit(1)
    except ValueError as exc:
        console.print(f"[bold red]❌ {exc}[/]")
        sys.exit(1)

    if rebuilt:
        console.print("\n[bold green]✅ Profil mis à jour avec succès.[/]")
    else:
        console.print("\n[yellow]ℹ️  Profil déjà à jour — CSV inchangé.[/]")
        console.print("[dim]Utilise --force pour forcer le retraitement.[/]")


# ─────────────────────────────────────────────────────────────────────────────
# Commande : recommend
# ─────────────────────────────────────────────────────────────────────────────

def cmd_recommend(args: argparse.Namespace) -> None:
    """Affiche le Top N recommandations personnalisées."""
    from recommender.engine import get_recommendations

    console, Table, Panel, box = _get_rich()

    # Vérifie que les deux bases existent
    if not config.PROFILE_DB_PATH.exists():
        console.print(
            "[bold red]❌ Profil introuvable.[/] Lance d'abord :\n"
            "  [cyan]python src/main.py update-profile[/]"
        )
        sys.exit(1)
    if not config.CATALOGUE_DB_PATH.exists():
        console.print(
            "[bold red]❌ Catalogue introuvable.[/] Lance d'abord :\n"
            "  [cyan]python src/main.py build-catalogue[/]"
        )
        sys.exit(1)

    genre = args.genre if hasattr(args, "genre") else None
    n = args.n if hasattr(args, "n") else 15

    titre_panel = f"[bold cyan]BiblioIA v2[/] — Top {n} recommandations SFF"
    if genre:
        titre_panel += f" · [italic]{genre}[/]"

    console.print(Panel(titre_panel, border_style="cyan"))

    recs = get_recommendations(
        profile_db=config.PROFILE_DB_PATH,
        catalogue_db=config.CATALOGUE_DB_PATH,
        n=n,
        genre_filter=genre,
    )

    if not recs:
        console.print(
            "[yellow]Aucune recommandation trouvée.[/]\n"
            "• Vérifie que le catalogue est construit ([cyan]build-catalogue[/])\n"
            "• Vérifie que le profil est à jour ([cyan]update-profile[/])\n"
            + (f"• Le filtre genre '[italic]{genre}[/]' est peut-être trop restrictif" if genre else "")
        )
        return

    # ── Tableau principal ──────────────────────────────────────────────────
    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        border_style="dim",
        expand=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Score", width=7, justify="center")
    table.add_column("Titre", style="bold white", min_width=28)
    table.add_column("Auteur", style="cyan", min_width=18)
    table.add_column("Année", width=6, justify="center", style="dim")
    table.add_column("Tags correspondants", style="green")
    table.add_column("Ebook FR", width=8, justify="center")

    for i, rec in enumerate(recs, start=1):
        score_bar = _score_bar(rec.score)
        tags_str = ", ".join(rec.matching_tags) if rec.matching_tags else "—"
        ebook_icon = "[green]✓[/]" if rec.ebook_link else "[dim]—[/]"
        year_str = str(rec.year_published) if rec.year_published else "—"

        table.add_row(
            str(i),
            score_bar,
            rec.display_title,
            rec.author,
            year_str,
            tags_str,
            ebook_icon,
        )

    console.print(table)

    # ── Liens ebooks ──────────────────────────────────────────────────────
    links = [(r.display_title, r.ebook_link) for r in recs if r.ebook_link]
    if links:
        console.print("\n[bold]🔗 Liens ebook :[/]")
        for title, link in links:
            console.print(f"  [dim]•[/] [cyan]{title}[/] → {link}")

    console.print(
        f"\n[dim]{len(recs)} recommandation(s) | "
        "profil : [/][cyan]update-profile[/][dim] | "
        "catalogue : [/][cyan]build-catalogue[/]"
    )


def _score_bar(score: float) -> str:
    """Convertit un score [0, ∞] en une barre visuelle colorée."""
    # Normalise sur 5 blocs max (le score peut dépasser 1.0 car c'est une somme)
    clamped = min(score / 3.0, 1.0)
    filled = round(clamped * 5)
    bar = "█" * filled + "░" * (5 - filled)
    pct = min(int(score / 3.0 * 100), 100)

    if pct >= 70:
        color = "green"
    elif pct >= 40:
        color = "yellow"
    else:
        color = "red"

    return f"[{color}]{bar}[/]"


# ─────────────────────────────────────────────────────────────────────────────
# Commande : status
# ─────────────────────────────────────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> None:
    """Affiche les statistiques du catalogue et du profil."""
    from db.catalogue_db import get_connection as cat_conn, get_stats as cat_stats, init_catalogue
    from db.profile_db import get_connection as prof_conn, get_stats as prof_stats, init_profile

    console, Table, Panel, box = _get_rich()
    console.print(Panel("[bold cyan]BiblioIA v2[/] — Statut", border_style="cyan"))

    # Catalogue
    table = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    table.add_column("Clé", style="dim", width=28)
    table.add_column("Valeur", style="bold white")

    if config.CATALOGUE_DB_PATH.exists():
        init_catalogue(config.CATALOGUE_DB_PATH)
        with cat_conn(config.CATALOGUE_DB_PATH) as conn:
            cs = cat_stats(conn)
        table.add_row("Catalogue — livres total", str(cs["total"]))
        table.add_row("   Enrichis", str(cs["enriched"]))
        table.add_row("   Ebook FR disponibles", f"[green]{cs['ebook_fr']}[/]")
        table.add_row("   DB", str(config.CATALOGUE_DB_PATH))
    else:
        table.add_row("Catalogue", "[red]Non construit — lance build-catalogue[/]")

    table.add_row("", "")

    # Profil
    if config.PROFILE_DB_PATH.exists():
        init_profile(config.PROFILE_DB_PATH)
        with prof_conn(config.PROFILE_DB_PATH) as conn:
            ps = prof_stats(conn)
        table.add_row("Profil — livres lus", str(ps["read_books"]))
        table.add_row("   Tags uniques", str(ps["unique_tags"]))
        table.add_row("   Dernière mise à jour", ps["last_updated"])
        table.add_row("   DB", str(config.PROFILE_DB_PATH))
    else:
        table.add_row("Profil", "[red]Non construit — lance update-profile[/]")

    console.print(table)


# ─────────────────────────────────────────────────────────────────────────────
# Parser CLI
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="biblio",
        description="BiblioIA v2 — Recommandateur SFF personnalisé (ebook français)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            "  python src/main.py build-catalogue\n"
            "  python src/main.py update-profile\n"
            "  python src/main.py recommend\n"
            "  python src/main.py recommend --genre 'Space Opera' --n 10\n"
            "  python src/main.py status\n"
        ),
    )

    sub = parser.add_subparsers(dest="command", metavar="<commande>")
    sub.required = True

    # build-catalogue
    p_build = sub.add_parser("build-catalogue", help="Construit/met à jour le catalogue SFF")
    p_build.set_defaults(func=cmd_build_catalogue)

    # update-profile
    p_profile = sub.add_parser("update-profile", help="Retraite l'export Goodreads CSV")
    p_profile.add_argument(
        "--force", action="store_true",
        help="Force le retraitement même si le CSV n'a pas changé",
    )
    p_profile.set_defaults(func=cmd_update_profile)

    # recommend
    p_rec = sub.add_parser("recommend", help="Affiche le Top N recommandations (instantané)")
    p_rec.add_argument(
        "--genre", metavar="GENRE",
        help="Filtre par sous-genre (ex: 'Space Opera', 'Cyberpunk', 'High Fantasy')",
    )
    p_rec.add_argument(
        "--n", type=int, default=15, metavar="N",
        help="Nombre de recommandations à afficher (défaut: 15)",
    )
    p_rec.set_defaults(func=cmd_recommend)

    # status
    p_status = sub.add_parser("status", help="Affiche les statistiques catalogue + profil")
    p_status.set_defaults(func=cmd_status)

    return parser


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        config.validate()
    except EnvironmentError as exc:
        print(f"❌ Configuration invalide : {exc}")
        sys.exit(1)

    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()