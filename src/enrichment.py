"""
enrichment.py — Enrichissement par JSON Strict & Règle de Tangibilité (Multithread).

- Utilise l'API Google Books pour récupérer les résumés.
- Utilise Gemini pour extraire des tropes matériels et techniques sous forme de JSON.
- Parse le JSON de manière sécurisée (sans regex) pour éviter les bugs d'affichage web.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd
from google.api_core.exceptions import ResourceExhausted
from langchain_google_genai import ChatGoogleGenerativeAI

from api_client import search_books_google
from config import (
    CSV_PATH,
    GOOGLE_API_KEY,
    ENRICHMENT_LLM_MODEL,
    ENRICHMENT_LLM_TEMPERATURE,
    ENRICHMENT_MAX_WORKERS,
    ENRICHMENT_SAVE_EVERY,
    FORCE_REFRESH_UNCLASSIFIED,
)

logger = logging.getLogger(__name__)

MAX_WORKERS = max(1, ENRICHMENT_MAX_WORKERS)
SAVE_EVERY = max(1, ENRICHMENT_SAVE_EVERY)

_DESCRIPTION_CACHE: dict[tuple[str, str, str, str], str] = {}
_TAGS_CACHE: dict[tuple[str, str, str], list[str]] = {}

def _clean_isbn(isbn_raw: Any) -> str:
    """Nettoie le formatage Excel étrange des ISBN."""
    val = str(isbn_raw).strip()
    if val.lower() == "nan" or not val:
        return ""
    return val.replace('="', '').replace('"', '').replace('=', '').strip()

def fetch_book_description(title: str, author: str, isbn13: str, isbn10: str) -> str:
    """Récupère le résumé via l'API Google Books (cascade ISBN -> Texte)."""
    cache_key = (title.strip().lower(), author.strip().lower(), isbn13, isbn10)
    if cache_key in _DESCRIPTION_CACHE:
        return _DESCRIPTION_CACHE[cache_key]

    def _extract_desc(items: list[dict[str, Any]]) -> str:
        for item in items:
            desc = item.get("volumeInfo", {}).get("description", "").strip()
            if desc: return desc
        return ""

    if isbn13:
        desc = _extract_desc(search_books_google("", "", isbn=isbn13))
        if desc:
            _DESCRIPTION_CACHE[cache_key] = desc
            return desc
        
    if isbn10:
        desc = _extract_desc(search_books_google("", "", isbn=isbn10))
        if desc:
            _DESCRIPTION_CACHE[cache_key] = desc
            return desc

    if title:
        desc = _extract_desc(search_books_google(title, author, strict_search=True))
        if desc:
            _DESCRIPTION_CACHE[cache_key] = desc
            return desc
        desc = _extract_desc(search_books_google(title, author, strict_search=False))
        if desc:
            _DESCRIPTION_CACHE[cache_key] = desc
            return desc

    _DESCRIPTION_CACHE[cache_key] = ""
    return ""

def generate_tags_with_llm(title: str, author: str, description: str) -> list[str]:
    """Génération de tags par JSON structuré selon la Taxonomie V4."""
    cache_key = (title.strip().lower(), author.strip().lower(), description[:300].strip().lower())
    if cache_key in _TAGS_CACHE:
        return _TAGS_CACHE[cache_key]
    
    if not description:
        context = f"Je n'ai pas de résumé. Fais appel à tes connaissances sur l'œuvre '{title}' de '{author}'."
    else:
        context = f"Résumé : {description[:1500]}"

    # Le Prompt V4 avec Référentiel Fermé et Few-Shot
    prompt = f"""
Tu es un data-scientist expert en littérature de l'imaginaire. Ta mission est de classifier des livres selon une taxonomie stricte et matérielle.

Livre : "{title}" de {author}
Contexte : {context}

### RÉFÉRENTIEL TAXONOMIQUE (Utilise UNIQUEMENT ces termes) :
1. SOUS-GENRES : Space Opera, Hard SF, Cyberpunk, High Fantasy, Urban Fantasy, Post-Apo, Dystopie, Uchronie, Steampunk, Dark Fantasy, Grimdark, Science Fantasy, Planet Opera, Solarpunk, Military SF, New Weird, LitRPG, Heroic Fantasy, Gaslamp, High Concept.
2. CADRES : Médiéval-fantastique, Station spatiale, Mégalopole, Wasteland, Vaisseau-génération, Cité sous-marine, Îles flottantes, Planète désertique, Forêt ancienne, Monde souterrain, Époque Victorienne, Cyberespace, École/Institut, Inframonde, Forteresse, Jungle hostile, Dimension parallèle, Boucle temporelle, Antiquité mythique, Cité-État/Renaissance, Continent perdu, Planète océan, Laboratoire, Vaisseau en stase, Frontière galactique, Manoir hanté, Donjon/Arène, Société secrète, Utopie technologique, Nébuleuse.
3. TROPES (TANGIBLES) : IA, Vaisseau spatial, Épée légendaire, Implant cybernétique, Portail, Robot, Baguette/Sceptre, Exosquelette, Grimoire, Blaster, Cape d'invisibilité, Machine temporelle, Dragon, Potion/Poison, Nanites, Artefact alien, Clone, Runes, Téléporteur, Golem, Hologramme, Cristal d'énergie, Ascenseur spatial, Carte, Familier, Sérum génétique, Bouclier énergétique, Moteur à distorsion, Méca, Pierre philosophale, Drone, Cryopod, Interface/HUD, Loot Box, Bio-armure, Puce mémorielle, Document Critique, Inhibiteur de pouvoir, Véhicule antigravité, Bombes à antimatière.

### RÈGLES CRITIQUES :
- TANGIBILITÉ : Bannis l'abstrait (Ex: Mémoire, Identité, Politique, Survie). Ne garde que le MATÉRIEL.
- HIÉRARCHIE : 1 sous-genre principal OBLIGATOIRE. 0 à 2 sous-genres secondaires.
- CADRE : 1 à 2 cadres maximum.
- TROPES : 2 à 4 tropes maximum.

### EXEMPLES (FEW-SHOT) :
Livre : "Les quinze premières vies d'Harry August" de Claire North
JSON: {{ "sous_genre_principal": "High Concept", "sous_genres_secondaires": ["Uchronie"], "cadre": ["Boucle temporelle", "Société secrète"], "tropes": ["Puce mémorielle", "Document Critique", "Inhibiteur de pouvoir"] }}

Livre : "Klara et le Soleil" de Kazuo Ishiguro
JSON: {{ "sous_genre_principal": "High Concept", "sous_genres_secondaires": ["Dystopie"], "cadre": ["Utopie technologique"], "tropes": ["Robot", "IA", "Sérum génétique"] }}

FORMAT OBLIGATOIRE (JSON uniquement) :
{{
  "sous_genre_principal": "...",
  "sous_genres_secondaires": [],
  "cadre": [],
  "tropes": []
}}
"""
    max_retries = 4
    for attempt in range(max_retries):
        try:
            llm = ChatGoogleGenerativeAI(
                model=ENRICHMENT_LLM_MODEL, 
                google_api_key=GOOGLE_API_KEY, 
                temperature=ENRICHMENT_LLM_TEMPERATURE 
            )
            response = llm.invoke(prompt)
            # response.content peut être une str ou une liste de blocs (ex: [{"type": "text", "text": "..."}])
            raw_content = response.content if hasattr(response, 'content') else str(response)
            if isinstance(raw_content, list):
                text = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in raw_content
                ).strip()
            else:
                text = str(raw_content).strip()
            
            # Extraction du bloc JSON
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            
            if start_idx != -1 and end_idx != -1:
                json_str = text[start_idx:end_idx+1]
                data = json.loads(json_str)
            else:
                logger.error("❌ Pas de JSON pour '%s'", title)
                return []
            
            # Reconstruction de la liste de tags à partir du nouveau format
            raw_tags = []
            
            # 1. Sous-genres
            if data.get("sous_genre_principal"):
                raw_tags.append(data["sous_genre_principal"])
            if isinstance(data.get("sous_genres_secondaires"), list):
                raw_tags.extend(data["sous_genres_secondaires"])
                
            # 2. Cadres (désormais une liste)
            if isinstance(data.get("cadre"), list):
                raw_tags.extend(data["cadre"])
            elif isinstance(data.get("cadre"), str): # Backup si l'IA oublie la liste
                raw_tags.append(data["cadre"])
                
            # 3. Tropes
            if isinstance(data.get("tropes"), list):
                raw_tags.extend(data["tropes"])

            # Nettoyage, Capitalisation et dédoublonnage
            processed_tags = []
            seen = set()
            for t in raw_tags:
                if t and isinstance(t, str):
                    clean_tag = t.strip().capitalize()
                    if clean_tag not in seen:
                        processed_tags.append(clean_tag)
                        seen.add(clean_tag)
            
            # Filtre final sur la longueur (pas de phrases)
            final_tags = [t for t in processed_tags if len(t.split()) <= 3]
            
            _TAGS_CACHE[cache_key] = final_tags
            return final_tags
            
        except ResourceExhausted as exc:
            logger.warning("⏳ Quota LLM atteint pour '%s'. Pause de 60 secondes...", title)
            time.sleep(60)
        except json.JSONDecodeError:
            logger.error("❌ JSON Decode Error pour '%s'.", title)
        except Exception as exc:
            # Si c'est un autre type d'erreur 429 qui n'est pas rattrapé par ResourceExhausted
            if "429" in str(exc) or "exhausted" in str(exc).lower() or "quota" in str(exc).lower():
                logger.warning("⏳ Quota API détecté pour '%s'. Pause de 60 secondes...", title)
                time.sleep(60)
            else:
                logger.error("❌ Erreur pour '%s' : %s", title, exc)
                time.sleep(10 * (attempt + 1))
            
    _TAGS_CACHE[cache_key] = []
    return []

def _process_single_book(idx: int, row: pd.Series) -> tuple[int, str, list[str]]:
    """Fonction exécutée par chaque thread (worker). Sans état partagé."""
    title = str(row.get("Title", "")).strip()
    author = str(row.get("Author", "")).strip()
    isbn13 = _clean_isbn(row.get("ISBN13", ""))
    isbn10 = _clean_isbn(row.get("ISBN", ""))

    logger.info("🔍 [Thread] Démarrage : '%s'", title)
    description = fetch_book_description(title, author, isbn13, isbn10)
    
    new_tags_list = generate_tags_with_llm(title, author, description)
    
    if new_tags_list:
        tags_string = ", ".join(new_tags_list)
    else:
        tags_string = "Erreur LLM"
        
    logger.info("✅ [Thread] Terminé : '%s' -> %s", title, tags_string)
    return idx, tags_string, new_tags_list

def enrich_dataframe_with_genres(df: pd.DataFrame, source_csv_path: Path | str | None = None) -> pd.DataFrame:
    logger.info("🚀 Début de l'enrichissement JSON Strict (Max Workers: %d)...", MAX_WORKERS)
    
    from db.profile_db import init_profile, get_connection, get_tags_from_cache, save_tags_to_cache
    from config import PROFILE_DB_PATH
    
    init_profile(PROFILE_DB_PATH)
    
    df_result = df.copy()
    if "Micro-genre" not in df_result.columns:
        df_result["Micro-genre"] = ""
        
    books_to_process = []
    
    with get_connection(PROFILE_DB_PATH) as conn:
        for idx, row in df_result.iterrows():
            current_tags = str(row.get("Micro-genre", "")).strip()
            book_id = str(row.get("Book Id", ""))
            title = str(row.get("Title", "")).strip()
            
            needs_processing = False
            
            if not current_tags or current_tags.lower() == "nan":
                # Check le cache en priorité !
                cached_tags = get_tags_from_cache(conn, book_id)
                if cached_tags:
                    df_result.at[idx, "Micro-genre"] = ", ".join(cached_tags)
                    logger.debug("⚡ Cache touch pour '%s'", title)
                    continue
                else:
                    needs_processing = True
            elif current_tags in ["Non classifié", "Erreur LLM"] and FORCE_REFRESH_UNCLASSIFIED:
                needs_processing = True
                
            if needs_processing and title and title.lower() != "nan":
                books_to_process.append((idx, row))

    if not books_to_process:
        logger.info("Aucun livre à enrichir.")
        return df_result

    logger.info("📚 %d livres mis en file d'attente.", len(books_to_process))
    
    fetched_count = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_process_single_book, idx, row): idx 
            for idx, row in books_to_process
        }
        
        for future in concurrent.futures.as_completed(futures):
            try:
                idx, tags_string, new_tags_list = future.result()
                df_result.at[idx, "Micro-genre"] = tags_string
                fetched_count += 1
                
                # Mise à jour du cache SQLite
                if new_tags_list:
                    book_id = str(df_result.at[idx, "Book Id"])
                    with get_connection(PROFILE_DB_PATH) as conn:
                        save_tags_to_cache(conn, book_id, new_tags_list)
                
                # Sauvegarde d'étape paramétrable
                if fetched_count % SAVE_EVERY == 0:
                    _save_to_csv(df_result, source_csv_path=source_csv_path)
                    logger.info("💾 Sauvegarde d'étape réussie (%d/%d).", fetched_count, len(books_to_process))
                    
            except Exception as exc:
                logger.error("Erreur critique sur un thread : %s", exc)

    if fetched_count > 0:
        _save_to_csv(df_result, source_csv_path=source_csv_path)

    logger.info("🏁 Enrichissement terminé (%d livres traités).", fetched_count)
    return df_result

def _save_to_csv(df_updated: pd.DataFrame, source_csv_path: Path | str | None = None) -> None:
    """Isole la logique de sauvegarde pour les étapes intermédiaires."""
    target_path = Path(source_csv_path) if source_csv_path else CSV_PATH
    try:
        full_df = pd.read_csv(target_path, dtype=str, encoding="utf-8")
        if "Micro-genre" not in full_df.columns:
            full_df["Micro-genre"] = ""
        
        updated_rows = df_updated[df_updated["Micro-genre"] != ""]
        mapping = updated_rows.set_index("Book Id")["Micro-genre"].to_dict()
        
        def _update_row(row_series: pd.Series) -> pd.Series:
            bid = str(row_series["Book Id"])
            if bid in mapping:
                row_series["Micro-genre"] = mapping[bid]
            return row_series

        full_df = full_df.apply(_update_row, axis=1)
        full_df.to_csv(target_path, index=False, encoding="utf-8")
    except Exception as exc:
        logger.error("Erreur de sauvegarde CSV : %s", exc)