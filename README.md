# 📚 BiblioIA v2 — Moteur de Recommandation SFF

Un système autonome de recommandation de livres spécialisé en **Science-Fiction et Fantasy (SFF)**. 

Conçu pour tourner en tâche de fond sur un Raspberry Pi via Docker, BiblioIA génère son propre catalogue de milliers de livres disponibles en **ebook français**, l'enrichit par IA, et le croise instantanément avec votre profil de lecture Goodreads. Fini l'agent conversationnel lent : les recommandations sont maintenant déterministes et s'affichent en moins d'une seconde.

---

## 🗂 Architecture

```
biblioIA/
├── docker-compose.yml        ← Déploiement avec volume persistant
├── docker/
│   └── Dockerfile            ← Image Python 3.11-slim (compatible ARM64)
├── data/                     ← Volume Docker persistant
│   ├── goodreads_library_export.csv  ← Votre historique (à fournir)
│   ├── catalogue.db              ← Base SQLite du catalogue SFF générée automatiquement
│   └── profile.db                ← Base SQLite de votre profil (tags pondérés)
├── src/
│   ├── main.py                   ← CLI principale (rich)
│   ├── scheduler.py              ← Tâche de fond autonome (cron interne)
│   ├── config.py                 ← Configuration via .env
│   ├── db/                       ← Couche d'accès SQLite
│   ├── catalogue/                ← Scrapers (Open Library) & validation (Google Books)
│   └── recommender/              ← Moteur de calcul vectoriel (dot product)
└── .env.example
```

---

## ⚙️ Installation & Déploiement (Docker / Raspberry Pi)

### 1. Préparer l'environnement

Clonez le dépôt, puis préparez vos variables d'environnement :

```bash
cp .env.example .env
```

Ouvrez `.env` et renseignez :
- `GOOGLE_API_KEY` : Votre clé Gemini pour le tagging en tâche de fond.
- *(Optionnel)* `GOOGLE_BOOKS_API_KEY` : Si vous dépassez le quota gratuit de Google Books.

### 2. Ajouter vos lectures Goodreads

Exportez votre bibliothèque depuis [goodreads.com](https://www.goodreads.com/review/import) et placez le fichier dans le dossier `data/` :
`data/goodreads_library_export.csv`

### 3. Lancer le conteneur

BiblioIA est conçu pour être 100% autonome. Lancez-le en tâche de fond :

```bash
docker compose up -d
```

Le conteneur reste actif grâce à un *scheduler* interne en Python pur. Il mettra à jour le catalogue automatiquement **chaque dimanche à 3h00 du matin**.

---

## 🚀 Utilisation via CLI

Vous interagissez avec BiblioIA en exécutant des commandes dans le conteneur en cours de fonctionnement :

### 1. Mettre à jour votre profil
À faire après avoir ajouté/modifié le CSV Goodreads. Lit votre historique, pondère vos tropes/sous-genres et sauvegarde le profil en SQLite.
```bash
docker exec -it biblio python src/main.py update-profile
```

### 2. Construire le catalogue manuellement (la première fois)
*Attention : Cette étape est longue. Elle interroge Open Library, valide les ebooks français via Google Books, et utilise le LLM pour tagger les livres trouvés.*
```bash
docker exec -it biblio python src/main.py build-catalogue
```
> **Note :** Vous pouvez suivre l'avancement via les logs Docker : `docker logs -f biblio`

### 3. Obtenir des recommandations
Affiche instantanément votre Top 15 personnalisé, basé sur le croisement vectoriel de vos goûts et du catalogue.
```bash
docker exec -it biblio python src/main.py recommend
```

**Avec des filtres :**
```bash
# Limiter à 5 résultats et filtrer par genre
docker exec -it biblio python src/main.py recommend --n 5 --genre "Cyberpunk"
```

### 4. Vérifier l'état du système
```bash
docker exec -it biblio python src/main.py status
```

---

## 📐 Règles métier

| Règle | Description |
|-------|-------------|
| **Dot Product Scoring** | Les recommandations sont déterministes. Chaque tag de votre profil a un poids. Le score d'un livre = Somme des poids des tags en commun. |
| **Biais d'auteur** | Lors de la construction du profil, chaque livre est pondéré par `1 / nb_livres_auteur` pour encourager la diversité. |
| **Biais de nouveauté** | Décroissance temporelle : les livres lus récemment ont plus d'impact sur vos goûts actuels. |
| **Optimisation LLM** | Seuls les livres *confirmés* comme disponibles en Ebook FR passent par l'API Gemini, divisant par 5 le coût et le temps de traitement. |
