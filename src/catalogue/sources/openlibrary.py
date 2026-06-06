"""
openlibrary.py — Client Open Library pour la découverte de livres SFF.

Utilisation des dumps Open Library au format txt.gz au lieu de l'API pour réduire
le traffic réseau et profiter des données complètes.

Documentation Open Library : https://openlibrary.org/dumps
"""

from __future__ import annotations

import atexit
import gzip
import json
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

# Chemin vers les dumps
DUMP_DIR = Path("C:/data")

# Types de dump à utiliser
WORKS_DUMP = "works.txt.gz"
AUTHORS_DUMP = "authors.txt.gz"

# Sujets SFF ciblés — on cible le fond du catalogue, pas juste les bestsellers.
# Les sujets Open Library sont en snake_case.
SFF_SUBJECTS = [
    "science_fiction",
    "fantasy",
]

# Cache des auteurs chargés (limité)
_authors_db_path: Path | None = None
_authors_db_lock = threading.Lock()
_cache_size_limit = 5000  # Limite le cache à 5000 auteurs


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


def _process_chunk(args: tuple[list[str], int]) -> Iterator[dict]:
    """
    Traite un chunk de lignes (fonction pour le multiprocessing).
    """
    chunk_lines, chunk_id = args
    logger.debug("Traitement du chunk %d (%d lignes)", chunk_id, len(chunk_lines))
    
    for line in chunk_lines:
        record = _parse_dump_line(line)
        if record:
            yield record


def _load_dump_file_parallel(dump_file: str, num_processes: int = None, chunk_size: int = 10000) -> Iterator[dict]:
    """
    Charge un fichier dump .txt.gz avec traitement parallèle.
    
    Args:
        dump_file: Nom du fichier dump
        num_processes: Nombre de processus (défaut: cpu_count)
        chunk_size: Taille des chunks en lignes
    """
    dump_path = DUMP_DIR / dump_file
    if not dump_path.exists():
        logger.error("Fichier dump non trouvé : %s", dump_path)
        return
    
    if num_processes is None:
        num_processes = min(mp.cpu_count(), 4)  # Limité à 4 processus pour ne pas surcharger
    
    logger.info("Chargement du dump : %s (traitement parallèle avec %d processus)", dump_path, num_processes)
    
    # Lit toutes les lignes (pour le parallélisation)
    with gzip.open(dump_path, 'rt', encoding='utf-8') as f:
        lines = list(f)
    
    logger.info("Fichier lu : %d lignes total", len(lines))
    
    # Divise en chunks
    chunks = [lines[i:i + chunk_size] for i in range(0, len(lines), chunk_size)]
    
    # Traite en parallèle
    with mp.Pool(processes=num_processes) as pool:
        results = pool.imap(
            _process_chunk,
            [(chunk, i) for i, chunk in enumerate(chunks)]
        )
        
        for chunk_result in results:
            for record in chunk_result:
                yield record


def _load_dump_file_hybrid(dump_file: str, buffer_size: int = 8192, 
                          num_threads: int = 4, chunk_size: int = 10000) -> Iterator[dict]:
    """
    Charge un fichier dump .txt.gz avec approche hybride buffered + threading.
    Lit le fichier par blocs et traite chaque bloc avec des threads.
    
    Args:
        dump_file: Nom du fichier dump
        buffer_size: Taille du buffer initial en lignes
        num_threads: Nombre de threads
        chunk_size: Taille des chunks pour chaque thread
    """
    dump_path = DUMP_DIR / dump_file
    if not dump_path.exists():
        logger.error("Fichier dump non trouvé : %s", dump_path)
        return
    
    logger.info("Chargement du dump : %s (mode hybride: buffer=%d, threads=%d)", 
                dump_path, buffer_size, num_threads)
    
    # Lit par blocs et traite avec des threads
    with gzip.open(dump_path, 'rt', encoding='utf-8') as f:
        buffer = []
        buffer_count = 0
        
        for line_num, line in enumerate(f, 1):
            buffer.append(line)
            buffer_count += 1
            
            # Traite le buffer quand il est plein
            if len(buffer) >= buffer_size:
                # Traite le buffer avec des threads
                for record in _process_buffer_with_threads(buffer, num_threads, chunk_size):
                    yield record
                
                buffer.clear()
                buffer_count = 0
                
                if line_num % 50000 == 0:
                    logger.debug("Traitement ligne %d du dump %s", line_num, dump_file)
        
        # Traite les lignes restantes
        if buffer:
            for record in _process_buffer_with_threads(buffer, num_threads, chunk_size):
                yield record


def _process_buffer_with_threads(buffer: list[str], num_threads: int, chunk_size: int) -> Iterator[dict]:
    """
    Traite un buffer avec des threads.
    """
    if len(buffer) <= chunk_size:
        # Traitement simple si le buffer est petit
        for line in buffer:
            record = _parse_dump_line(line)
            if record:
                yield record
        return
    
    # Divise en chunks
    chunks = [buffer[i:i + chunk_size] for i in range(0, len(buffer), chunk_size)]
    
    # Traite avec des threads
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = []
        for i, chunk in enumerate(chunks):
            future = executor.submit(_process_chunk_simple, chunk)
            futures.append(future)
        
        # Récupère les résultats
        for future in as_completed(futures):
            try:
                for record in future.result():
                    yield record
            except Exception as e:
                logger.error("Erreur dans un thread: %s", e)


def _process_chunk_simple(chunk: list[str]) -> Iterator[dict]:
    """
    Traite un chunk de lignes (fonction simple pour les threads).
    """
    for line in chunk:
        record = _parse_dump_line(line)
        if record:
            yield record


def _load_dump_file(dump_file: str, buffer_size: int = 8192, parallel: bool = False, 
                   num_processes: int = None, chunk_size: int = 10000, 
                   num_threads: int = 4, hybrid: bool = False) -> Iterator[dict]:
    """
    Charge un fichier dump .txt.gz et retourne les enregistrements.
    
    Args:
        dump_file: Nom du fichier dump
        buffer_size: Taille du buffer en lignes (lecture par blocs)
        parallel: Utiliser le traitement parallèle (multiprocessing)
        num_processes: Nombre de processus (pour le parallèle)
        chunk_size: Taille des chunks (pour le parallèle)
        num_threads: Nombre de threads (pour l'approche hybride)
        hybrid: Utiliser l'approche hybride buffered + threading
    """
    if hybrid:
        return _load_dump_file_hybrid(dump_file, buffer_size, num_threads, chunk_size)
    elif parallel:
        return _load_dump_file_parallel(dump_file, num_processes, chunk_size)
    else:
        return _load_dump_file_buffered(dump_file, buffer_size)


def _load_dump_file_buffered(dump_file: str, buffer_size: int = 8192) -> Iterator[dict]:
    """
    Charge un fichier dump .txt.gz et retourne les enregistrements.
    Lit par blocs pour un meilleur équilibre entre vitesse et mémoire.
    
    Args:
        dump_file: Nom du fichier dump
        buffer_size: Taille du buffer en lignes (par défaut 8192)
    """
    dump_path = DUMP_DIR / dump_file
    if not dump_path.exists():
        logger.error("Fichier dump non trouvé : %s", dump_path)
        return
    
    logger.info("Chargement du dump : %s (lecture par blocs de %d lignes)", dump_path, buffer_size)
    
    with gzip.open(dump_path, 'rt', encoding='utf-8') as f:
        buffer = []
        for line_num, line in enumerate(f, 1):
            buffer.append(line)
            
            # Traite le buffer quand il est plein
            if len(buffer) >= buffer_size:
                for buffered_line in buffer:
                    record = _parse_dump_line(buffered_line)
                    if record:
                        yield record
                buffer.clear()
                
                if line_num % 50000 == 0:
                    logger.debug("Traitement ligne %d du dump %s", line_num, dump_file)
        
        # Traite les lignes restantes
        for buffered_line in buffer:
            record = _parse_dump_line(buffered_line)
            if record:
                yield record


def _get_authors_db_path() -> Path:
    """Retourne le chemin de la base de données temporaire des auteurs."""
    global _authors_db_path
    if _authors_db_path is None:
        with _authors_db_lock:
            if _authors_db_path is None:
                # Crée une base de données temporaire
                _authors_db_path = Path("temp_authors.db")
                _create_authors_db()
    return _authors_db_path


def _create_authors_db():
    """Crée et remplit la base de données des auteurs."""
    global _authors_db_path
    
    logger.info("Création de la base de données temporaire des auteurs...")
    
    db_path = _authors_db_path
    
    # Crée la table des auteurs
    with sqlite3.connect(db_path) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS authors (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
        ''')
        
        # Crée un index pour les recherches
        conn.execute('CREATE INDEX IF NOT EXISTS idx_authors_key ON authors(key)')
        
        # Importe les auteurs depuis le dump
        count = 0
        batch_size = 1000
        batch = []
        
        try:
            for record in _load_dump_file(AUTHORS_DUMP):
                if record["type"] == "/type/author":
                    author_data = record["data"]
                    author_key = record["key"]
                    author_name = author_data.get("name", "Auteur inconnu")
                    
                    batch.append((author_key, author_name))
                    count += 1
                    
                    # Insère par batch
                    if len(batch) >= batch_size:
                        conn.executemany(
                            'INSERT OR REPLACE INTO authors (key, name) VALUES (?, ?)',
                            batch
                        )
                        conn.commit()
                        batch.clear()
                        
                        if count % 10000 == 0:
                            logger.info("Import de %d auteurs...", count)
            
            # Insère les restes
            if batch:
                conn.executemany(
                    'INSERT OR REPLACE INTO authors (key, name) VALUES (?, ?)',
                    batch
                )
                conn.commit()
            
            logger.info("Base de données des auteurs créée : %d auteurs", count)
            
        except Exception as e:
            logger.error("Erreur lors de l'import des auteurs : %s", e)
            # Supprime la base en cas d'erreur
            if db_path.exists():
                db_path.unlink()
            raise


def _get_author_name(author_key: str) -> str:
    """
    Récupère le nom d'un auteur depuis la base de données SQLite.
    """
    if not author_key:
        return "Auteur inconnu"
    
    try:
        db_path = _get_authors_db_path()
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT name FROM authors WHERE key = ?', (author_key,))
            result = cursor.fetchone()
            return result[0] if result else "Auteur inconnu"
            
    except Exception as e:
        logger.debug("Erreur lors de la recherche de l'auteur %s : %s", author_key, e)
        return "Auteur inconnu"


def cleanup_authors_db():
    """Nettoie la base de données temporaire des auteurs."""
    global _authors_db_path
    if _authors_db_path and _authors_db_path.exists():
        try:
            import time
            time.sleep(0.1)  # Laisse le temps aux connexions de se fermer
            _authors_db_path.unlink()
            logger.info("Base de données temporaire des auteurs nettoyée")
        except Exception as e:
            logger.warning("Erreur lors du nettoyage de la base temporaire : %s", e)
    _authors_db_path = None


# Nettoyage automatique à la fin du programme
atexit.register(cleanup_authors_db)


def fetch_all_sff_works(max_per_subject: int = 25000, 
                        read_mode: str = "buffered", 
                        buffer_size: int = 8192,
                        parallel: bool = False,
                        num_processes: int = None,
                        chunk_size: int = 10000,
                        num_threads: int = 4,
                        hybrid: bool = False) -> Iterator[dict]:
    """
    Itère sur tous les sujets SFF depuis les dumps Open Library et retourne chaque livre sans doublon.
    
    Args:
        max_per_subject: Limite le nombre de livres par sujet
        read_mode: Mode de lecture ("buffered", "parallel", "line_by_line", "hybrid")
        buffer_size: Taille du buffer en lignes (pour le mode buffered)
        parallel: Utiliser le traitement parallèle
        num_processes: Nombre de processus (pour le parallèle)
        chunk_size: Taille des chunks (pour le parallèle)
        num_threads: Nombre de threads (pour l'approche hybride)
        hybrid: Utiliser l'approche hybride buffered + threading
    """
    # Initialise la base de données des auteurs (création au premier appel)
    _get_authors_db_path()
    
    seen_ids: set[str] = set()
    total = 0
    subject_counts = {subject: 0 for subject in SFF_SUBJECTS}
    
    # Configure le mode de lecture
    if read_mode == "hybrid":
        logger.info("Début du traitement du dump works.txt.gz (mode hybride: buffer=%d, threads=%d)", 
                   buffer_size, num_threads)
        dump_iterator = _load_dump_file(WORKS_DUMP, buffer_size=buffer_size, hybrid=True, 
                                       num_threads=num_threads, chunk_size=chunk_size)
    elif read_mode == "buffered":
        logger.info("Début du traitement du dump works.txt.gz (mode buffered, buffer_size=%d)", buffer_size)
        dump_iterator = _load_dump_file(WORKS_DUMP, buffer_size=buffer_size, parallel=False)
    elif read_mode == "parallel":
        logger.info("Début du traitement du dump works.txt.gz (mode parallèle, %d processus)", num_processes or 4)
        dump_iterator = _load_dump_file(WORKS_DUMP, parallel=True, num_processes=num_processes, chunk_size=chunk_size)
    else:  # line_by_line
        logger.info("Début du traitement du dump works.txt.gz (mode ligne par ligne)")
        dump_iterator = _load_dump_file(WORKS_DUMP, buffer_size=1, parallel=False)
    
    for record in dump_iterator:
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
        
        # Extraction de l'auteur (optimisé avec mapping des clés)
        authors_raw = work_data.get("authors", [])
        if authors_raw:
            # Prend le premier auteur et récupère son nom depuis le cache
            first_author_role = authors_raw[0]
            author_key = first_author_role.get("author", {}).get("key", "")
            author = _get_author_name(author_key) if author_key else "Auteur inconnu"
        else:
            author = "Auteur inconnu"
        
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