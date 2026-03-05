# 📚 BiblioIA — Agent Bibliothécaire Local

Un agent IA local qui analyse ton historique de lecture Goodreads, corrige les biais statistiques et génère des recommandations de livres disponibles **en ebook et en français**.

---

## 🗂 Arborescence du projet

```
biblioIA/
├── .env.example              ← Template de configuration
├── .gitignore
├── pyproject.toml            ← Config Pytest
├── requirements.txt          ← Dépendances Python
├── README.md
├── data/
│   └── goodreads_library_export.csv   ← Ton export Goodreads (à placer ici)
├── src/
│   ├── config.py             ← Chargement var. d'environnement
│   ├── preprocessing.py      ← Pipeline Pandas + règles métier
│   ├── api_client.py         ← Vérification disponibilité ebook français
│   ├── agent.py              ← Agent LangChain bibliothécaire
│   └── main.py               ← Point d'entrée
└── tests/
    └── test_preprocessing.py ← Tests unitaires Pytest
```

---

## ⚙️ Installation

### 1. Créer et activer l'environnement virtuel (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> **Linux / macOS :** `source .venv/bin/activate`

### 2. Installer les dépendances

```powershell
pip install -r requirements.txt
```

### 3. Configurer l'environnement

```powershell
copy .env.example .env
```

Ouvre `.env` et remplis les valeurs :

```dotenv
OPENAI_API_KEY=sk-...         # Obligatoire
GOOGLE_BOOKS_API_KEY=         # Optionnel (1000 req/jour sans clé)
LLM_MODEL=gpt-4o-mini         # Ou gpt-4o, gpt-3.5-turbo...
```

### 4. Placer ton export Goodreads

Exporte ta bibliothèque depuis [goodreads.com](https://www.goodreads.com/review/import) puis place le fichier CSV dans :

```
data/goodreads_library_export.csv
```

---

## 🚀 Utilisation

```powershell
python src/main.py
```

L'agent affiche d'abord un résumé de ton profil de lecture pondéré, puis lance une boucle interactive.

**Exemples de questions :**
- *"Recommande-moi 3 romans de fantasy que je n'ai pas encore lus."*
- *"Quels sont mes auteurs préférés selon mon historique ?"*
- *"Propose-moi un thriller disponible en ebook français."*

Tape `quit` pour quitter.

---

## 🧪 Tests

```powershell
pytest -v
```

Les tests vérifient :
- La règle temporelle **arsac** (forçage de date ≥ 10 ans)
- La **correction du biais auteur** (poids inverse du volume)
- La **correction du biais de nouveauté** (décroissance exponentielle)
- La **stabilité du pipeline** avec des dates manquantes (NaT)

---

## 📐 Règles métier implémentées

| Règle | Description |
|-------|-------------|
| **Biais de série** | Chaque livre est pondéré par `1 / nb_livres_auteur`. Un auteur avec 20 livres lus contribue 20× moins par livre. |
| **Biais de nouveauté** | Décroissance exponentielle `exp(-λ × années_depuis_lecture)` avec λ=0.2 par défaut. |
| **Règle arsac** | Si `Bookshelves` contient `"arsac"`, `Date Read` est forcée à ≥ 10 ans. |
| **Filtre ebook/français** | Chaque recommandation est validée via Google Books API avant présentation. |

---

## 🔧 Variables d'environnement

| Variable | Requis | Défaut | Description |
|----------|--------|--------|-------------|
| `OPENAI_API_KEY` | ✅ | — | Clé API OpenAI |
| `LLM_MODEL` | ❌ | `gpt-4o-mini` | Modèle LLM à utiliser |
| `LLM_TEMPERATURE` | ❌ | `0.2` | Créativité du LLM (0–1) |
| `GOOGLE_BOOKS_API_KEY` | ❌ | — | Clé Google Books (quota augmenté) |
| `CSV_PATH` | ❌ | `data/goodreads_library_export.csv` | Chemin vers le CSV |
| `RECENCY_DECAY_LAMBDA` | ❌ | `0.2` | Coefficient de décroissance temporelle |
| `ARSAC_YEARS_AGO` | ❌ | `10` | Nombre d'années forcé pour la règle arsac |
