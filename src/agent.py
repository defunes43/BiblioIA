"""
agent.py — Agent LangChain bibliothécaire (Basé sur les Facettes/Micro-genres).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

import pandas as pd
from langchain_core.tools import Tool
from langchain_experimental.agents import create_pandas_dataframe_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.tools import DuckDuckGoSearchRun

from api_client import is_available_french_ebook
from config import AGENT_LLM_MODEL, AGENT_LLM_TEMPERATURE, GOOGLE_API_KEY

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Outil de vérification Ebook & Doublons
# ─────────────────────────────────────────────────────────────────────────────

_AVAILABILITY_TOOL_DESCRIPTION = """
Vérifie si un ou plusieurs livres sont déjà lus OU s'ils sont disponibles en ebook français.
UTILISATION OBLIGATOIRE avant de proposer définitivement une recommandation.
Entrée : une liste de un ou plusieurs livres, un par ligne.
Format EXACT pour chaque ligne : "Titre Français | Titre Original | Auteur".
Exemple :
La Stratégie Ender | Ender's Game | Orson Scott Card
Dune | Dune | Frank Herbert
(Si le livre est originellement en français, mets le même titre deux fois).
Sortie : rapport textuel indiquant pour chaque livre si tu as le droit de le recommander.
"""

def _normalize_string(s: str) -> str:
    """Retire les accents, les majuscules et la ponctuation pour la comparaison."""
    if not isinstance(s, str):
        return ""
    s_no_accents = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s_no_accents.lower())

def _is_book_in_library(suggested_title: str, suggested_author: str, df: pd.DataFrame) -> bool:
    """Vérifie si le titre et l'auteur correspondent approximativement dans le CSV."""
    norm_title = _normalize_string(suggested_title)
    norm_author_words = set(re.findall(r"[a-z]+", _normalize_string(suggested_author)))
    
    if not norm_title:
        return False
        
    for _, row in df.iterrows():
        lib_title = _normalize_string(str(row.get("Title", "")))
        lib_author = _normalize_string(str(row.get("Author", "")))
        
        # Le titre suggéré est inclus dans le titre CSV (ou l'inverse)
        title_match = (norm_title in lib_title) or (lib_title and lib_title in norm_title)
        if title_match:
            # Vérification de l'auteur pour éviter les faux positifs
            lib_author_words = set(re.findall(r"[a-z]+", lib_author))
            if norm_author_words.intersection(lib_author_words):
                return True
    return False

def build_availability_tool(df: pd.DataFrame) -> Tool:
    def _availability_tool_func(input_str: str) -> str:
        lines = [line.strip() for line in input_str.strip().split("\n") if line.strip()]
        results = []
        for line in lines:
            parts = [p.strip() for p in line.split("|")]
            
            if len(parts) >= 3:
                title_fr = parts[0]
                title_orig = parts[1]
                author = parts[2]
            elif len(parts) == 2:
                title_fr = parts[0]
                title_orig = parts[0]
                author = parts[1]
            else:
                title_fr = line.strip()
                title_orig = title_fr
                author = ""

            # 1. Vérification dans la bibliothèque avec le titre original ET le titre FR
            if _is_book_in_library(title_orig, author, df) or _is_book_in_library(title_fr, author, df):
                logger.info("❌ Rejeté (Déjà lu) : %s / %s", title_fr, title_orig)
                results.append(f"INTERDIT : Le livre '{title_orig}' de {author} a déjà été lu. Ne propose plus les livres les plus connus de ce genre.")
                continue

            # 2. Vérification Ebook avec le titre FR
            logger.info("🔍 Recherche Ebook : %s", title_fr)
            availability_res = str(is_available_french_ebook(title_fr, author))
            results.append(f"Rapport pour '{title_fr}' : {availability_res}")

        return "\n".join(results) if results else "Erreur : Fournis au moins un livre."

    return Tool(
        name="CheckFrenchEbookAvailability",
        func=_availability_tool_func,
        description=_AVAILABILITY_TOOL_DESCRIPTION,
    )

def build_web_search_recommendations_tool() -> Tool:
    import datetime
    current_year = datetime.date.today().year
    # Délai de traduction anglais→français : ~1-2 ans en moyenne.
    # On cible donc les livres anglais de (current_year-3) à (current_year-1)
    # et les parutions francophones de (current_year-1) à current_year.
    en_range = f"{current_year - 3}..{current_year - 1}"
    fr_range = f"{current_year - 1}..{current_year}"
    trusted_domains = (
        "goodreads.com",
        "babelio.com",
        "booknode.com",
        "noosfere.org",
        "locusmag.com",
        "tor.com",
        "reactormag.com",
        "kirkusreviews.com",
        "bookriot.com",
    )
    book_keywords = (
        "roman", "romans", "novel", "novels", "book", "books", "livre", "livres",
        "sf", "science-fiction", "science fiction", "fantasy", "space opera",
        "cyberpunk", "dystopie", "dystopian",
    )
    genre_keywords = (
        "science-fiction", "science fiction", "sf", "fantasy", "space opera",
        "cyberpunk", "dystopie", "dystopian", "imaginaire",
    )
    negative_keywords = (
        "film", "movie", "series", "tv", "anime", "manga", "jeu", "game", "gaming",
        "wiki", "wikipedia", "fanfic", "fanfiction", "torrent", "streaming",
    )
    blocked_domains = (
        "developpez.net",
        "stackoverflow.com",
        "reddit.com",
        "youtube.com",
        "imdb.com",
    )

    def _extract_domain(url: str) -> str:
        if not url:
            return ""
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return ""

    def _build_query_variants(query: str) -> list[str]:
        base = query.strip()
        if not base:
            return []
        return [
            f'{base} novels books recommandations livres',
            f'{base} hidden gems books site:goodreads.com',
            f'{base} romans ebook français',
            f'{base} site:babelio.com',
            f'{base} site:booknode.com',
        ]

    def _result_score(result: dict[str, Any], query: str) -> int:
        title = str(result.get("title", "")).lower()
        body = str(result.get("body", "")).lower()
        href = str(result.get("href", "")).lower()
        text_blob = f"{title} {body} {href}"
        score = 0

        domain = _extract_domain(href)
        if any(b in domain for b in blocked_domains):
            return -10
        if any(d in domain for d in trusted_domains):
            score += 5

        query_tokens = re.findall(r"[a-z0-9]+", query.lower())
        for token in query_tokens:
            if len(token) >= 4 and token in text_blob:
                score += 1

        if any(k in text_blob for k in book_keywords):
            score += 4
        if any(g in text_blob for g in genre_keywords):
            score += 3
        if any(bad in text_blob for bad in negative_keywords):
            score -= 5
        return score

    def _search_web(input_str: str) -> str:
        """Effectue jusqu'à 3 requêtes séparées par '|' et retourne les résultats fusionnés."""
        queries = [q.strip() for q in input_str.split("|") if q.strip()][:3]
        if not queries:
            return "Erreur : fournis au moins une requête."

        all_scored_results: list[tuple[int, dict[str, Any], str]] = []
        seen_urls: set[str] = set()
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                for query in queries:
                    logger.info("🌐 Recherche Web : %s", query)
                    variants = _build_query_variants(query)
                    for variant in variants:
                        results = ddgs.text(variant, max_results=8)
                        for r in results or []:
                            href = str(r.get("href", "")).strip()
                            if not href or href in seen_urls:
                                continue
                            seen_urls.add(href)
                            score = _result_score(r, query)
                            text_blob = (
                                f"{str(r.get('title', '')).lower()} "
                                f"{str(r.get('body', '')).lower()} "
                                f"{str(r.get('href', '')).lower()}"
                            )
                            # Garde seulement les résultats liés aux livres ET au genre demandé.
                            has_book_signal = any(k in text_blob for k in book_keywords)
                            has_genre_signal = any(g in text_blob for g in genre_keywords)
                            if score < 4 or not (has_book_signal and has_genre_signal):
                                continue
                            all_scored_results.append((score, r, query))
        except Exception as e:
            logger.error("Erreur de recherche Web : %s", e)
            return f"Erreur de recherche : {e}"

        if not all_scored_results:
            return "Aucun résultat pertinent trouvé sur le web."

        all_scored_results.sort(key=lambda item: item[0], reverse=True)
        top_results = all_scored_results[:12]
        formatted_results: list[str] = []
        for score, result, source_query in top_results:
            formatted_results.append(
                f"Score  : {score}\n"
                f"Requête: {source_query}\n"
                f"Source : {result.get('href', '')}\n"
                f"Titre  : {result.get('title', '')}\n"
                f"Extrait: {result.get('body', '')}"
            )

        return "\n\n---\n\n".join(formatted_results)

    description = (
        "Moteur de recherche Internet. UTILISE-LE OBLIGATOIREMENT avant d'utiliser ton intuition, "
        "pour trouver des livres (nouveautés ou pépites méconnues). "
        "IMPORTANT — délai de traduction : un livre anglais prend en moyenne 1 à 2 ans pour paraître en français. "
        f"Pour des ebooks français, ex: "
        f"(1) 'best obscure [genre] novels {en_range} site:goodreads.com', "
        f"(2) 'meilleurs romans [genre] {fr_range} ebook français originaux'. "
        "Tu peux passer jusqu'à 3 requêtes séparées par '|' pour diversifier les sources d'un coup."
    )

    return Tool(
        name="SearchRecommendations",
        func=_search_web,
        description=description,
    )
# ─────────────────────────────────────────────────────────────────────────────
# Agrégation du Profil
# ─────────────────────────────────────────────────────────────────────────────

def _build_profile_df(df: pd.DataFrame) -> pd.DataFrame:
    """Génère un dataframe simplifié avec uniquement les tags et leur score cumulé."""
    df_temp = df.copy()
    
    # On sépare les tags par virgule et on les met sur plusieurs lignes (explode)
    df_exploded = df_temp.assign(Micro_genre=df_temp['Micro-genre'].astype(str).str.split(',')).explode('Micro_genre')
    df_exploded['Micro_genre'] = df_exploded['Micro_genre'].str.strip().str.capitalize()
    
    # On nettoie les parasites
    df_exploded = df_exploded[~df_exploded['Micro_genre'].isin(["", "Nan", "Erreur llm", "Non classifié"])]
    
    # On groupe par tag et on somme le score pondéré
    df_profile = df_exploded.groupby('Micro_genre')['bias_corrected_score'].sum().reset_index()
    
    # On trie du plus grand au plus petit pour simplifier la vie de l'Agent
    df_profile = df_profile.sort_values(by='bias_corrected_score', ascending=False).reset_index(drop=True)
    
    # OPTIMISATION : On renvoie le Top 30 pour donner une vision globale
    return df_profile.head(30)

# ─────────────────────────────────────────────────────────────────────────────
# Prompt Système (Moteur de Recommandation par Micro-genres)
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """
Tu es un agent bibliothécaire expert.
Tu as accès à un DataFrame Pandas nommé `df` qui contient le PROFIL DE GOÛTS de l'utilisateur.
Colonnes : `Micro_genre` et `bias_corrected_score`.

INSTRUCTIONS DE TRAVAIL OBLIGATOIRES (À SUIVRE DANS L'ORDRE) :
1. UTILISE L'OUTIL PYTHON : Tu DOIS exécuter `df.head(30)` via tes outils python pour lire le profil.
2. RECHERCHE WEB OBLIGATOIRE : Trouve de nouveaux ouvrages en utilisant l'outil SearchRecommendations avec les tags identifiés (cherche des listes sur le web, des 'hidden gems' ou des nouveautés). Ne te base pas uniquement sur tes connaissances internes qui génèrent presque toujours des classiques déjà lus.
3. SÉLECTION ET VÉRIFICATION PAR LOT : Sélectionne 3 à 5 livres issus de tes recherches web et utilise l'outil CheckFrenchEbookAvailability en leur passant tous ces livres d'un coup. Passe EXACTEMENT la chaîne "Titre Français | Titre Original | Nom de l'auteur" (un livre par ligne).
4. GÈRE LES ERREURS : Si l'outil te répond "INTERDIT" (déjà lu) pour l'un des ouvrages, ignore-le. S'ils sont tous interdits ou indisponibles, recommence à l'étape 2 avec une recherche Web différente (et des requêtes de type 'livres moins connus [tag]').
5. RÉPONSE FINALE : Génère une réponse texte finale listant les tags qui ont motivé ton choix parmi un des résultats renvoyés par l'outil de check, et ajoute le lien de l'ebook trouvé.
"""

def build_agent(df: pd.DataFrame) -> Any:
    llm = ChatGoogleGenerativeAI(
        model=AGENT_LLM_MODEL, temperature=AGENT_LLM_TEMPERATURE, google_api_key=GOOGLE_API_KEY
    )
    
    # On génère le profil ultra-simplifié (Top 30)
    df_profile = _build_profile_df(df)

    system_prompt = _SYSTEM_PROMPT_TEMPLATE
    
    return create_pandas_dataframe_agent(
        llm=llm, 
        df=df_profile, 
        extra_tools=[build_availability_tool(df), build_web_search_recommendations_tool()], 
        agent_type="tool-calling", 
        prefix=system_prompt, 
        verbose=True, 
        allow_dangerous_code=True
    )

def run_interactive_loop(agent: Any) -> None:
    print("\n" + "=" * 60 + "\n  📚 BiblioIA — Agent Bibliothécaire (Moteur Micro-genres)\n" + "=" * 60 + "\n")
    while True:
        try:
            user_input = input("Toi : ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAu revoir !")
            break
        if not user_input: continue
        if user_input.lower() in {"quit", "exit"}:
            print("Au revoir !")
            break
            
        try:
            response = agent.invoke({"input": user_input})
            raw_out = response.get("output", response)
            final_out = "".join([p.get("text", "") if isinstance(p, dict) else str(p) for p in raw_out]).strip() if isinstance(raw_out, list) else str(raw_out).strip()
            
            if not final_out:
                final_out = "Désolé, je suis resté bloqué pendant ma réflexion. Peux-tu reformuler ?"
                
            print(f"\nAgent : {final_out}\n")
        except Exception as exc: 
            logger.error("Erreur : %s", exc)