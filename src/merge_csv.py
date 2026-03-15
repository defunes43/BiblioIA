"""
merge_csv.py — Utilitaire pour fusionner les anciens tags avec un nouvel export Goodreads.

Ce script prend la précieuse colonne 'Micro-genre' de l'ancien fichier
et l'injecte dans le nouveau fichier en utilisant 'Book Id' comme clé de correspondance.
"""

import pandas as pd
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# --- Chemins des fichiers (à adapter si besoin) ---
OLD_CSV_PATH = "books_old.csv"   # L'export avec tes micro-genres LLM
NEW_CSV_PATH = "books_new.csv"   # Le nouvel export Goodreads vierge
OUTPUT_PATH = "books.csv"        # Le fichier final pour ton appli

def merge_goodreads_csv() -> None:
    logger.info("Chargement des fichiers CSV...")
    
    try:
        df_old = pd.read_csv(OLD_CSV_PATH, dtype=str)
        df_new = pd.read_csv(NEW_CSV_PATH, dtype=str)
    except FileNotFoundError as e:
        logger.error(f"Fichier introuvable : {e}")
        return

    # S'assurer que la colonne existe
    if "Micro-genre" not in df_old.columns:
        logger.error("L'ancien fichier n'a pas de colonne 'Micro-genre' !")
        return
        
    if "Micro-genre" not in df_new.columns:
        df_new["Micro-genre"] = ""

    # 1. Créer un dictionnaire de mapping depuis l'ancien fichier
    # Format : {'ID_du_livre': 'Tag1, Tag2, Tag3'}
    # On ignore les lignes où le micro-genre est vide ou NaN
    df_old_valid = df_old[df_old["Micro-genre"].notna() & (df_old["Micro-genre"] != "")]
    
    # Nettoyage des éventuels "Erreur LLM" pour forcer la repasse
    df_old_valid = df_old_valid[df_old_valid["Micro-genre"] != "Erreur LLM"]
    
    mapping_genres = dict(zip(df_old_valid["Book Id"], df_old_valid["Micro-genre"]))
    
    logger.info(f"{len(mapping_genres)} livres avec des tags valides trouvés dans l'ancien fichier.")

    # 2. Appliquer le mapping sur le nouveau fichier
    # Si le 'Book Id' est dans le dictionnaire, on met le tag. Sinon, on met vide ("").
    df_new["Micro-genre"] = df_new["Book Id"].map(mapping_genres).fillna("")

    # 3. Compter les nouveaux livres à enrichir
    livres_a_enrichir = len(df_new[df_new["Micro-genre"] == ""])
    logger.info(f"Fusion terminée ! Il y a {livres_a_enrichir} nouveaux livres qui n'ont pas de tags.")

    # 4. Sauvegarder
    df_new.to_csv(OUTPUT_PATH, index=False, encoding="utf-8")
    logger.info(f"Fichier sauvegardé avec succès sous : {OUTPUT_PATH}")

if __name__ == "__main__":
    merge_goodreads_csv()