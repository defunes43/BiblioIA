"""
profile_builder.py — Construction du profil utilisateur depuis l'export Goodreads.

Logique :
- Calcule le hash MD5 du CSV source.
- Si le hash n'a pas changé depuis le dernier traitement → skip (profil à jour).
- Sinon → relance le pipeline complet (preprocessing + enrichment) et sauvegarde dans profile.db.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from db.profile_db import (
    get_connection,
    get_metadata,
    init_profile,
    save_profile,
    set_metadata,
)
from preprocessing import load_and_prepare

logger = logging.getLogger(__name__)


def _md5(path: Path) -> str:
    """Calcule le hash MD5 d'un fichier."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_profile(csv_path: Path, profile_db: Path, *, force: bool = False) -> bool:
    """
    Construit ou met à jour le profil utilisateur.

    Args:
        csv_path:   Chemin vers l'export Goodreads CSV.
        profile_db: Chemin vers le fichier profile.db SQLite.
        force:      Si True, retraite même si le CSV n'a pas changé.

    Returns:
        True si le profil a été (re)construit, False si déjà à jour.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Export Goodreads introuvable : {csv_path}")

    init_profile(profile_db)
    current_hash = _md5(csv_path)

    with get_connection(profile_db) as conn:
        stored_hash = get_metadata(conn, "csv_hash")

    if not force and stored_hash == current_hash:
        logger.info("Profil déjà à jour (hash CSV inchangé). Utilise --force pour forcer.")
        return False

    logger.info("Changement détecté (ou premier lancement). Reconstruction du profil…")
    logger.info("   CSV : %s", csv_path)

    # Pipeline existant : chargement → enrichissement LLM → correction biais
    df = load_and_prepare(csv_path)

    if df.empty:
        raise ValueError("Aucun livre 'read' trouvé dans le CSV. Vérifie l'export Goodreads.")

    # Sauvegarde dans SQLite
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(profile_db) as conn:
        save_profile(conn, df)
        set_metadata(conn, "csv_hash", current_hash)
        set_metadata(conn, "last_updated", now)
        set_metadata(conn, "book_count", str(len(df)))

    logger.info("Profil construit : %d livres, sauvegardé dans %s", len(df), profile_db)
    return True
