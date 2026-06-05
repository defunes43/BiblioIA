"""
openlibrary.py — Client Open Library pour la découverte de livres SFF.

Utilisation des dumps Open Library au format txt.gz au lieu de l'API pour réduire
le traffic réseau et profiter des données complètes.

Documentation Open Library : https://openlibrary.org/dumps
"""

from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

# Chemin vers les dumps
DUMP_DIR = Path("/data")

# Types de dump à utiliser
WORKS_DUMP = "works.txt.gz"
EDITIONS_DUMP = "editions.txt.gz"

# Sujets SFF ciblés — on cible le fond du catalogue, pas juste les bestsellers.
# Les sujets Open Library sont en snake_case.
SFF_SUBJECTS = [
    "science_fiction",
    "fantasy",
]


def _parse_dump_line(line: str) -> dict | None:
    """
    Parse une ligne de dump Open Library (format TSV avec JSON).
    
    Format : type\tkey\trevision\tlast_modified\tJSON
    """
    try:
        parts = line.strip().split('\t')
        if len(parts) != 5:
            return None
        
        record_type, key, revision, last_modified, json_data = parts
        
        # Extrait l'ID unique (ex: "/works/OL27516W" → "OL27516W")
        unique_id = key.split('/')[-1] if '/' in key else key
        
        return {
            "type": record_type,
            "key": key,
            "id": unique_id,
            "revision": int(revision),
            "last_modified": last_modified,
            "data": json.loads(json_data)
        }
    except (ValueError, json.JSONDecodeError) as e:
        logger.debug("Erreur de parsing de ligne : %s", e)
        return None


def _load_dump_file(dump_file: str) -> Iterator[dict]:
    """
    Charge un fichier dump .txt.gz et retourne les enregistrements.
    Lit ligne par ligne pour minimiser l'utilisation mémoire.
    """
    dump_path = DUMP_DIR / dump_file
    if not dump_path.exists():
        logger.error("Fichier dump non trouvé : %s", dump_path)
        return
    
    logger.info("Chargement du dump : %s (lecture ligne par ligne)", dump_path)
    
    with gzip.open(dump_path, 'rt', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            if line_num % 50000 == 0:  # Log moins fréquent pour ne pas ralentir
                logger.debug("Traitement ligne %d du dump %s", line_num, dump_file)
            
            record = _parse_dump_line(line)
            if record:
                yield record


def fetch_all_sff_works(max_per_subject: int = 25000) -> Iterator[dict]:
    """
    Itère sur tous les sujets SFF depuis les dumps Open Library et retourne chaque livre sans doublon.
    
    Utilise le dump 'works.txt.gz' et filtre par sujet dans les données JSON.
    Lecture ligne par ligne pour une faible utilisation mémoire.
    
    max_per_subject : limite le nombre de livres par sujet (évite les géants
    comme 'science_fiction' qui a 500 000+ entrées).
    """
    seen_ids: set[str] = set()
    total = 0
    subject_counts = {subject: 0 for subject in SFF_SUBJECTS}
    
    logger.info("Début du traitement du dump works.txt.gz...")
    
    for record in _load_dump_file(WORKS_DUMP):
        work_data = record["data"]
        work_id = record["id"]
        
        # Vérification rapide des doublons
        if work_id in seen_ids:
            continue
            
        # Vérifie si le travail est dans les sujets SFF (optimisé)
        subjects = work_data.get("subjects", [])
        has_sff_subject = False
        
        for subject in subjects:
            # Normalise le sujet pour correspondre à notre liste
            normalized_subject = subject.lower().replace(' ', '_')
            if normalized_subject in SFF_SUBJECTS:
                has_sff_subject = True
                subject_counts[normalized_subject] += 1
                
                # Vérifie la limite par sujet
                if subject_counts[normalized_subject] > max_per_subject:
                    logger.info(
                        "Sujet '%s' : limite de %d atteinte, arrêt de la collecte pour ce sujet.",
                        normalized_subject, max_per_subject,
                    )
                    return
                break
        
        if not has_sff_subject:
            continue
        
        # Extraction de l'auteur (optimisé)
        authors_raw = work_data.get("authors", [])
        author = authors_raw[0].get("name", "Auteur inconnu") if authors_raw else "Auteur inconnu"
        
        # Validation rapide
        if not work_data.get("title"):
            continue
        
        seen_ids.add(work_id)
        total += 1
        
        # Logs de progression moins fréquents
        if total % 100000 == 0:
            logger.info("Progression : %d livres traités", total)
        
        yield {
            "id": f"ol_{work_id}",
            "title": work_data.get("title", "").strip(),
            "title_fr": None,  # Sera rempli si traduction FR trouvée via Google Books
            "author": author.strip(),
            "year_published": work_data.get("first_publish_year"),
            "source": "openlibrary",
        }
    
    logger.info("Traitement terminé : %d livres SFF uniques trouvés dans les dumps", total)



