# ── Build stage ───────────────────────────────────────────────────────────────
# python:3.11-slim a des wheels ARM64 natifs pour toutes nos dépendances.
FROM python:3.11-slim

LABEL maintainer="BiblioIA"
LABEL description="Recommandateur SFF personnalisé — ebook français"

# Variables d'environnement Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# ── Dépendances système minimales ─────────────────────────────────────────────
# gcc n'est pas nécessaire : toutes nos dépendances ont des wheels précompilés.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Dépendances Python ────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Code source ───────────────────────────────────────────────────────────────
COPY src/ ./src/

# ── Répertoire de données (monté en volume depuis l'hôte) ─────────────────────
# Le volume /app/data contient :
#   - goodreads_library_export.csv  (fourni par l'utilisateur)
#   - catalogue.db                  (généré par build-catalogue)
#   - profile.db                    (généré par update-profile)
RUN mkdir -p /app/data

# ── Commande par défaut ───────────────────────────────────────────────────────
# Lance le scheduler interne pour garder le conteneur actif et lancer les tâches cron.
CMD ["python", "src/scheduler.py"]
