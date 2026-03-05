"""
agent.py — Agent LangChain bibliothécaire pour BiblioIA.

L'agent combine :
- Un ``create_pandas_dataframe_agent`` pour analyser l'historique de lecture.
- Un outil personnalisé ``CheckFrenchEbookAvailability`` pour valider que chaque
  recommandation est disponible en ebook et en français avant de la proposer.
"""

from __future__ import annotations

import logging

import pandas as pd
from langchain.agents import AgentExecutor, Tool
from langchain_experimental.agents import create_pandas_dataframe_agent
from langchain_openai import ChatOpenAI

from api_client import is_available_french_ebook
from config import LLM_MODEL, LLM_TEMPERATURE, OPENAI_API_KEY

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Outil de vérification de disponibilité
# ─────────────────────────────────────────────────────────────────────────────

_AVAILABILITY_TOOL_DESCRIPTION = """
Vérifie si un livre est disponible en ebook ET en traduction française via l'API Google Books.
UTILISATION OBLIGATOIRE avant de recommander un livre.
Entrée : chaîne au format "Titre | Auteur" (ex: "Le Nom du Vent | Patrick Rothfuss").
Sortie : rapport textuel indiquant disponibilité, langue et lien Google Books.
"""


def _availability_tool_func(input_str: str) -> str:
    """Wrapper de l'outil LangChain vers ``is_available_french_ebook``.

    Args:
        input_str: Chaîne ``"Titre | Auteur"`` fournie par l'agent.

    Returns:
        Représentation textuelle du :class:`BookAvailability`.
    """
    parts = [p.strip() for p in input_str.split("|")]
    title = parts[0] if len(parts) > 0 else input_str.strip()
    author = parts[1] if len(parts) > 1 else ""
    result = is_available_french_ebook(title, author)
    return str(result)


def build_availability_tool() -> Tool:
    """Crée l'outil LangChain de vérification de disponibilité ebook français.

    Returns:
        :class:`langchain.agents.Tool` prêt à être injecté dans l'agent.
    """
    return Tool(
        name="CheckFrenchEbookAvailability",
        func=_availability_tool_func,
        description=_AVAILABILITY_TOOL_DESCRIPTION,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Prompt système
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """
Tu es un agent bibliothécaire expert et bienveillant. Tu analyses l'historique de lecture
d'un utilisateur contenu dans un DataFrame Pandas et tu fournis des recommandations
personnalisées en respectant TOUTES ces règles :

# RÈGLES DE RECOMMANDATION

1. **Score de pertinence** : Base tes recommandations sur la colonne `bias_corrected_score`
   (entre 0 et 1). Les livres à haut score reflètent les préférences réelles de l'utilisateur
   après correction des biais de série et de nouveauté.

2. **Validation obligatoire** : Pour CHAQUE livre que tu envisages de recommander, tu DOIS
   utiliser l'outil `CheckFrenchEbookAvailability` pour vérifier sa disponibilité.
   Ne recommande JAMAIS un livre sans avoir effectué cette vérification au préalable.

3. **Filtre strict** : Ne présente à l'utilisateur QUE les livres pour lesquels l'outil
   a retourné `available=True`. Si un livre n'est pas disponible, cherche une alternative.

4. **Format de réponse** : Pour chaque recommandation validée, indique :
   - Le titre et l'auteur
   - Pourquoi ce livre correspond au profil de l'utilisateur
   - Le lien Google Books fourni par l'outil

5. **Langue** : Réponds toujours en français, de manière chaleureuse et naturelle.

6. **Diversité** : Évite de recommander plusieurs œuvres du même auteur ou de la même série.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Construction de l'agent
# ─────────────────────────────────────────────────────────────────────────────


def build_agent(df: pd.DataFrame) -> AgentExecutor:
    """Instancie l'agent LangChain bibliothécaire sur le DataFrame nettoyé.

    Args:
        df: DataFrame préparé par le pipeline de ``preprocessing.py``.

    Returns:
        :class:`langchain.agents.AgentExecutor` prêt à répondre aux questions.

    Raises:
        ValueError: Si ``OPENAI_API_KEY`` est vide.
    """
    if not OPENAI_API_KEY:
        raise ValueError(
            "OPENAI_API_KEY n'est pas défini. Configure ton fichier .env."
        )

    llm = ChatOpenAI(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        api_key=OPENAI_API_KEY,
    )

    availability_tool = build_availability_tool()

    agent: AgentExecutor = create_pandas_dataframe_agent(
        llm=llm,
        df=df,
        extra_tools=[availability_tool],
        agent_type="tool-calling",
        prefix=_SYSTEM_PROMPT,
        verbose=True,
        allow_dangerous_code=True,  # requis pour l'exécution Pandas
        handle_parsing_errors=True,
    )

    logger.info(
        "Agent bibliothécaire initialisé (modèle=%s, temp=%.1f, %d livres dans le DF).",
        LLM_MODEL,
        LLM_TEMPERATURE,
        len(df),
    )
    return agent


# ─────────────────────────────────────────────────────────────────────────────
# Boucle interactive
# ─────────────────────────────────────────────────────────────────────────────


def run_interactive_loop(agent: AgentExecutor) -> None:
    """Lance une boucle REPL permettant de dialoguer avec l'agent.

    Tape ``quit`` ou ``exit`` pour terminer la session.

    Args:
        agent: Agent LangChain déjà initialisé.
    """
    print("\n" + "=" * 60)
    print("  📚 BiblioIA — Agent Bibliothécaire")
    print("  Tape 'quit' ou 'exit' pour quitter.")
    print("=" * 60 + "\n")

    while True:
        try:
            user_input = input("Toi : ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAu revoir ! 📖")
            break

        if not user_input:
            continue

        if user_input.lower() in {"quit", "exit", "quitter"}:
            print("Au revoir ! Bonne lecture ! 📖")
            break

        try:
            response = agent.invoke({"input": user_input})
            print(f"\nAgent : {response.get('output', response)}\n")
        except Exception as exc:  # noqa: BLE001
            logger.error("Erreur de l'agent : %s", exc)
            print(f"\n[Erreur] L'agent a rencontré un problème : {exc}\n")
