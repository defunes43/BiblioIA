"""
main.py — Point d'entrée CLI de BiblioIA v2.

Commandes disponibles :
  build-catalogue   Construit ou met à jour le catalogue SFF (tâche longue)
  update-profile    Retraite l'export Goodreads CSV et reconstruit le profil
  recommend         Affiche le Top N recommandations (instantané)
  status            Affiche les statistiques catalogue + profil + noosfere
  noosfere-init    Initialise la file d'attente Noosfere (bootstrap)
  noosfere-process-month  Scrape les livres d'un mois sur Noosfere
  noosfere-process-queue  Traite la file d'attente et ajoute au catalogue
  noosfere-debug-single   Debug: scraper un seul livre avec logs détaillés

Exemples :
  python src/main.py build-catalogue
  python src/main.py update-profile
  python src/main.py recommend
  python src/main.py recommend --genre "Space Opera" --n 10
  python src/main.py status
  python src/main.py noosfere-init
  python src/main.py noosfere-process-month --year 2024 --month 5
  python src/main.py noosfere-process-queue
  python src/main.py noosfere-debug-single --numlivre 2146591788
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
# Commande : noosfere-init
# ─────────────────────────────────────────────────────────────────────────────

def cmd_noosfere_init(args: argparse.Namespace) -> None:
    """Initialise la file d'attente en scrapant les années 1950-2025."""
    from catalogue.sources.noosfere import initialize_scraping_queue, get_queue_stats

    console, Table, Panel, box = _get_rich()
    console.print(Panel(
        "[bold cyan]BiblioIA v2[/] — Initialisation Noosfere\n"
        f"[dim]DB queue : {config.SCRAPING_QUEUE_DB_PATH}[/]",
        border_style="cyan",
    ))

    total = initialize_scraping_queue(
        db_path=config.SCRAPING_QUEUE_DB_PATH,
        start_year=1950,
        end_year=2025,
        delay=config.NOOSFERE_BASE_DELAY,
    )

    stats = get_queue_stats(config.SCRAPING_QUEUE_DB_PATH)
    console.print(f"\n[bold green]✅ Initialisation terminée : {total} livres ajoutés.[/]")
    console.print(f"[dim]Pending: {stats['pending']}[/]")


def cmd_noosfere_process_month(args: argparse.Namespace) -> None:
    """Scrape les livres d'un mois et les ajoute à la file d'attente."""
    from catalogue.sources.noosfere import process_month_scraping, get_queue_stats

    console, Table, Panel, box = _get_rich()
    console.print(Panel(
        f"[bold cyan]BiblioIA v2[/] — Scraping Noosfere : {args.year}/{args.month}\n"
        f"[dim]DB queue : {config.SCRAPING_QUEUE_DB_PATH}[/]",
        border_style="cyan",
    ))

    added = process_month_scraping(
        year=args.year,
        month=args.month,
        db_path=config.SCRAPING_QUEUE_DB_PATH,
        delay=config.NOOSFERE_BASE_DELAY,
    )

    stats = get_queue_stats(config.SCRAPING_QUEUE_DB_PATH)
    console.print(f"\n[bold green]✅ {added} livres ajoutés depuis le mois {args.month}/{args.year}.[/]")
    console.print(f"[dim]Total pending: {stats['pending']}[/]")


def cmd_noosfere_process_queue(args: argparse.Namespace) -> None:
    """Traite la file d'attente et ajoute les livres au catalogue."""
    from catalogue.sources.noosfere import process_scraping_queue, get_queue_stats

    console, Table, Panel, box = _get_rich()
    console.print(Panel(
        "[bold cyan]BiblioIA v2[/] — Traitement file d'attente Noosfere\n"
        f"[dim]DB queue : {config.SCRAPING_QUEUE_DB_PATH}[/]\n"
        f"[dim]DB catalogue : {config.CATALOGUE_DB_PATH}[/]",
        border_style="cyan",
    ))

    processed = process_scraping_queue(
        queue_db_path=config.SCRAPING_QUEUE_DB_PATH,
        catalogue_db_path=config.CATALOGUE_DB_PATH,
        delay=config.NOOSFERE_BASE_DELAY,
        batch_size=50,
    )

    stats = get_queue_stats(config.SCRAPING_QUEUE_DB_PATH)
    console.print(f"\n[bold green]✅ {processed} livres traités et ajoutés au catalogue.[/]")
    console.print(f"[dim]Enriched: {stats['enriched']}[/]")


def cmd_noosfere_debug_single(args: argparse.Namespace) -> None:
    """Scraper un seul livre avec logs de debug détaillés."""
    from catalogue.sources.noosfere import debug_scrape_single_book

    console, Table, Panel, box = _get_rich()
    console.print(Panel(
        f"[bold cyan]BiblioIA v2[/] — Debug scraping Noosfere\n"
        f"[dim]numlivre = {args.numlivre}[/]",
        border_style="cyan",
    ))

    result = debug_scrape_single_book(
        numlivre=args.numlivre,
        catalogue_db_path=config.CATALOGUE_DB_PATH,
    )

    if result.success:
        console.print(f"\n[bold green]✅ Scraping réussi.[/]")
        console.print(f"   Titre : {result.title}")
        console.print(f"   Auteur : {result.author}")
        console.print(f"   Résumé ({len(result.summary)} car) : {result.summary[:100]}...")
    else:
        console.print(f"\n[red]❌ Scraping échoué : {result.error}[/]")


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
        is_ebook = rec.year_published is not None and rec.year_published > 2010
        ebook_icon = "[green]✓[/]" if is_ebook else "[dim]—[/]"
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
    """Affiche les statistiques du catalogue, du profil et de la file d'attente Noosfere."""
    from db.catalogue_db import get_connection as cat_conn, get_stats as cat_stats, init_catalogue
    from db.profile_db import get_connection as prof_conn, get_stats as prof_stats, init_profile
    from catalogue.sources.noosfere import get_queue_stats as get_scraping_stats

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

    # Noosfere scraping queue
    if config.SCRAPING_QUEUE_DB_PATH.exists():
        sq_stats = get_scraping_stats(config.SCRAPING_QUEUE_DB_PATH)
        table.add_row("Noosfere — file d'attente", str(sq_stats["total"]))
        table.add_row("   Pending", str(sq_stats["pending"]))
        table.add_row("   Scraped", str(sq_stats["scraped"]))
        table.add_row("   Enriched", str(sq_stats["enriched"]))
        table.add_row("   DB", str(config.SCRAPING_QUEUE_DB_PATH))
    else:
        table.add_row("Noosfere queue", "[dim]Non initialisée[/]")

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

    # noosfere-init
    p_noosfere_init = sub.add_parser("noosfere-init", help="Initialise la file d'attente Noosfere (bootstrap)")
    p_noosfere_init.set_defaults(func=cmd_noosfere_init)

    # noosfere-process-month
    p_noosfere_month = sub.add_parser("noosfere-process-month", help="Scrape les livres d'un mois sur Noosfere")
    p_noosfere_month.add_argument(
        "--year", type=int, required=True, metavar="YEAR",
        help="Année à scraper (ex: 2024)",
    )
    p_noosfere_month.add_argument(
        "--month", type=int, required=True, metavar="MONTH",
        help="Mois à scraper (1-12)",
    )
    p_noosfere_month.set_defaults(func=cmd_noosfere_process_month)

    # noosfere-process-queue
    p_noosfere_queue = sub.add_parser("noosfere-process-queue", help="Traite la file d'attente Noosfere")
    p_noosfere_queue.set_defaults(func=cmd_noosfere_process_queue)

    # noosfere-debug-single
    p_noosfere_debug = sub.add_parser("noosfere-debug-single", help="Debug: scraper un seul livre avec logs détaillés")
    p_noosfere_debug.add_argument(
        "--numlivre", required=True, metavar="NUMLIVRE",
        help="numlivre du livre à scraper (ex: 2146591788)",
    )
    p_noosfere_debug.set_defaults(func=cmd_noosfere_debug_single)

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