# 📚 BiblioIA — Agent Bibliothécaire SFF

Un agent IA local conçu pour les passionnés de **Science-Fiction et de Fantasy (SFF)**. Il analyse ton historique de lecture Goodreads, corrige les biais de nouveauté et génère des recommandations de livres disponibles **en ebook et en français**.

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
GOOGLE_API_KEY=AIza...        # Obligatoire (clé Google AI Studio)
GOOGLE_BOOKS_API_KEY=         # Optionnel (1000 req/jour sans clé)
LLM_MODEL=gemini-2.0-flash    # Ou gemini-1.5-pro...
```

### 4. Placer ton export Goodreads

Exporte ta bibliothèque depuis [goodreads.com](https://www.goodreads.com/review/import) puis place le fichier CSV dans le dossier `data/`. Par défaut, le fichier attendu est `data/goodreads_library_export.csv`.

---

## 🚀 Utilisation

```powershell
python src/main.py
```

L'agent affiche d'abord un résumé de ton profil de lecture (basé sur tes lectures passées et leur date), puis lance une boucle interactive spécialisée en **Science-Fiction et Fantasy**.

**Exemples de questions :**
- *"Recommande-moi 3 romans de space opera que je n'ai pas encore lus."*
- *"Quels sont mes tropes préférés selon mon historique ?"*
- *"Propose-moi un livre de hard SF disponible en ebook français."*

Tape `quit` pour quitter.

---

# 📚 BiblioIA — Agent Bibliothécaire SFF

Un agent IA local conçu pour les passionnés de **Science-Fiction et de Fantasy (SFF)**. Il analyse ton historique de lecture Goodreads, corrige les biais de nouveauté et génère des recommandations de livres disponibles **en ebook et en français**.

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
GOOGLE_API_KEY=AIza...        # Obligatoire (clé Google AI Studio)
GOOGLE_BOOKS_API_KEY=         # Optionnel (1000 req/jour sans clé)
LLM_MODEL=gemini-2.0-flash    # Ou gemini-1.5-pro...
```

### 4. Placer ton export Goodreads

Exporte ta bibliothèque depuis [goodreads.com](https://www.goodreads.com/review/import) puis place le fichier CSV dans le dossier `data/`. Par défaut, le fichier attendu est `data/goodreads_library_export.csv`.

---

## 🚀 Utilisation

```powershell
python src/main.py
```

L'agent affiche d'abord un résumé de ton profil de lecture (basé sur tes lectures passées et leur date), puis lance une boucle interactive spécialisée en **Science-Fiction et Fantasy**.

**Exemples de questions :**
- *"Recommande-moi 3 romans de space opera que je n'ai pas encore lus."*
- *"Quels sont mes tropes préférés selon mon historique ?"*
- *"Propose-moi un livre de hard SF disponible en ebook français."*

Tape `quit` pour quitter.

---

## 🧪 Tests

```powershell
pytest -v
```

Les tests vérifient :
- La règle temporelle **older_books** (forçage de date pour les vieux souvenirs)
- La **correction du biais d'auteur** (poids inverse du volume)
- La **correction du biais de nouveauté** (décroissance exponentielle)
- La **stabilité du pipeline** avec des dates manquantes (NaT)

---

## 📐 Règles métier implémentées

| Règle | Description |
|-------|-------------|
| **Biais d'auteur** | Chaque livre est pondéré par `1 / nb_livres_auteur`. Un auteur avec 20 livres lus contribue 20× moins par livre pour encourager la diversité. |
| **Biais de nouveauté** | Décroissance exponentielle `exp(-λ × années_depuis_lecture)` avec λ=0.2 par défaut. Les lectures récentes comptent plus que les anciennes. |
| **Règle older_books** | Si une étagère (`Bookshelves`) contient le tag défini (ex: `"older_books"`), la `Date Read` est forcée à ≥ 10 ans pour éviter qu'un souvenir d'enfance ne sature les recommandations. |
| **Filtre ebook/français** | Chaque recommandation est validée via Google Books API pour garantir sa disponibilité en format numérique français. |

---

## 🔧 Variables d'environnement

| Variable | Requis | Défaut | Description |
|----------|--------|--------|-------------|
| `GOOGLE_API_KEY` | ✅ | — | Clé API Google AI Studio |
| `LLM_MODEL` | ❌ | `gemini-2.0-flash` | Modèle LLM à utiliser |
| `LLM_TEMPERATURE` | ❌ | `0.2` | Créativité du LLM (0–1) |
| `GOOGLE_BOOKS_API_KEY` | ❌ | — | Clé Google Books (quota augmenté) |
| `CSV_PATH` | ❌ | `data/goodreads_library_export.csv` | Chemin vers le CSV |
| `RECENCY_DECAY_LAMBDA` | ❌ | `0.2` | Coefficient de décroissance temporelle |
| `OLDER_BOOKS_TAG` | ❌ | `older_books` | Tag Goodreads pour marquer les vieux livres |
| `OLDER_BOOKS_YEARS_AGO` | ❌ | `10` | Nombre d'années forcé pour la règle older_books |
