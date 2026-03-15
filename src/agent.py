"""
agent.py — Agent LangChain bibliothécaire (Basé sur les Facettes/Micro-genres).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

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
Vérifie si un livre est déjà lu OU s'il est disponible en ebook français.
UTILISATION OBLIGATOIRE avant de proposer définitivement une recommandation.
Entrée : chaîne au format EXACT "Titre Français | Titre Original | Auteur".
Exemple : "La Stratégie Ender | Ender's Game | Orson Scott Card".
(Si le livre est originellement en français, mets le même titre deux fois).
Sortie : rapport textuel indiquant si tu as le droit de le recommander.
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
        parts = [p.strip() for p in input_str.split("|")]
        
        if len(parts) >= 3:
            title_fr = parts[0]
            title_orig = parts[1]
            author = parts[2]
        elif len(parts) == 2:
            title_fr = parts[0]
            title_orig = parts[0]
            author = parts[1]
        else:
            title_fr = input_str.strip()
            title_orig = title_fr
            author = ""

        # 1. Vérification dans la bibliothèque avec le titre original ET le titre FR
        if _is_book_in_library(title_orig, author, df) or _is_book_in_library(title_fr, author, df):
            logger.info("❌ Rejeté (Déjà lu) : %s / %s", title_fr, title_orig)
            return f"INTERDIT : Le livre '{title_orig}' de {author} a déjà été lu. Cherche un autre livre."

        # 2. Vérification Ebook avec le titre FR
        logger.info("🔍 Recherche Ebook : %s", title_fr)
        return str(is_available_french_ebook(title_fr, author))

    return Tool(
        name="CheckFrenchEbookAvailability",
        func=_availability_tool_func,
        description=_AVAILABILITY_TOOL_DESCRIPTION,
    )

def build_web_search_tool() -> Tool:
    def _search_web(query: str) -> str:
        try:
            from duckduckgo_search import DDGS 
            logger.info("🌐 Recherche Web : %s", query)
            # DDGS().text renvoie directement une liste de dictionnaires dans la v8+
            results = DDGS().text(query, max_results=4)
            if not results:
                return "Aucun résultat trouvé sur le web."
            
            formatted_results = []
            for r in results:
                formatted_results.append(f"Titre : {r.get('title')}\nExtrait : {r.get('body')}")
            return "\n\n".join(formatted_results)
        except Exception as e:
            logger.error("Erreur de recherche Web : %s", e)
            return f"Erreur de recherche : {e}"

    return Tool(
        name="WebSearchNouveautes",
        func=_search_web,
        description="Moteur de recherche Internet. UTILISE-LE OBLIGATOIREMENT pour chercher des recommandations de livres très récents (sortis ces deux dernières années) en tapant des requêtes comme 'meilleurs romans [Tag] récents' ou 'new sci-fi books [Tag]'.",
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

_SYSTEM_PROMPT = """
Tu es un agent bibliothécaire expert.
Tu as accès à un DataFrame Pandas nommé `df` qui contient le PROFIL DE GOÛTS de l'utilisateur.
Colonnes : `Micro_genre` et `bias_corrected_score`.

INSTRUCTIONS DE TRAVAIL OBLIGATOIRES (À SUIVRE DANS L'ORDRE) :
1. UTILISE L'OUTIL PYTHON : Tu DOIS exécuter `df.head(30)` via tes outils python pour lire le profil.
2. RÉFLÉCHIS : Trouve un livre qui croise un maximum de ces tags (optimise la correspondance globale). Pour les recommandations de livres ultra-récents (postérieurs à ta date d'entrainement), tu DEVRAS utiliser publiquement ton outil duckduckgo_search pour obtenir des listes de récompenses ou des parutions récentes pertinentes.
3. UTILISE L'OUTIL CheckFrenchEbookAvailability : Passe-lui EXACTEMENT la chaîne "Titre Français | Titre Original | Nom de l'auteur" (Exemple: "La Stratégie Ender | Ender's Game | Orson Scott Card").
4. GÈRE LES ERREURS : Si l'outil te répond "INTERDIT" ou "Non disponible", recommence silencieusement à l'étape 2.
5. RÉPONSE FINALE : Génère une réponse texte finale listant les tags qui ont motivé ton choix et ajoute le lien de l'ebook.
"""

def build_agent(df: pd.DataFrame) -> Any:
    llm = ChatGoogleGenerativeAI(
        model=AGENT_LLM_MODEL, temperature=AGENT_LLM_TEMPERATURE, google_api_key=GOOGLE_API_KEY
    )
    
    # On génère le profil ultra-simplifié (Top 30)
    df_profile = _build_profile_df(df)
    

    return create_pandas_dataframe_agent(
        llm=llm, 
        df=df_profile, 
        extra_tools=[build_availability_tool(df), build_web_search_tool()], 
        agent_type="tool-calling", 
        prefix=_SYSTEM_PROMPT, 
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