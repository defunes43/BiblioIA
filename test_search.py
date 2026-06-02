import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent import build_web_search_recommendations_tool

def test_search():
    queries = [
        "best obscure space opera novels 2023 site:goodreads.com",
        "meilleurs romans science fiction recents 2025",
        "livres science fiction recommandation pépite"
    ]
    out_data = {}
    tool = build_web_search_recommendations_tool()
    
    for query in queries:
        print(f"\n--- RECHERCHE : {query} ---")
        try:
            # Appelle la même fonction que l'agent de recommandation.
            out_data[query] = tool.func(query)
        except Exception as e:
            out_data[query] = {"error": str(e)}

    with open("test_search_output.json", "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    test_search()

