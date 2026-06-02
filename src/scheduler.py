"""
scheduler.py — Tâche de fond pour le conteneur Docker.

Garde le conteneur en vie et exécute build-catalogue toutes les semaines.
Remplace l'usage de cron sur l'hôte, rendant le conteneur 100% autonome.
"""

import logging
import subprocess
import time
import sys
from pathlib import Path

# Assure que le dossier src/ est dans le path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import schedule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scheduler")

def run_build_catalogue():
    """Exécute la mise à jour du catalogue en sous-processus."""
    logger.info("Démarrage de la tâche hebdomadaire : build-catalogue")
    try:
        # On appelle le script de la même manière que la CLI
        subprocess.run(
            [sys.executable, "src/main.py", "build-catalogue"],
            check=True
        )
        logger.info("Tâche hebdomadaire terminée avec succès.")
    except subprocess.CalledProcessError as exc:
        logger.error("Erreur lors de l'exécution de build-catalogue : %s", exc)

def main():
    logger.info("Scheduler autonome démarré.")
    logger.info("Le catalogue sera mis à jour chaque dimanche à 03:00.")
    
    # Programmation hebdomadaire le dimanche à 3h du matin
    schedule.every().sunday.at("03:00").do(run_build_catalogue)
    
    # Boucle infinie
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
