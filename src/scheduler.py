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

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scheduler")

_last_csv_mtime = 0.0

def check_and_update_profile():
    """Vérifie si le CSV a été modifié, et lance update-profile si c'est le cas."""
    global _last_csv_mtime
    try:
        if config.CSV_PATH.exists():
            current_mtime = config.CSV_PATH.stat().st_mtime
            # Si le fichier est plus récent que la dernière vérification
            if current_mtime > _last_csv_mtime:
                # On évite de lancer au tout premier démarrage si le profil est déjà à jour
                if _last_csv_mtime == 0.0:
                    _last_csv_mtime = current_mtime
                    # On lance quand même une fois au démarrage (le MD5 bloquera si déjà à jour)
                else:
                    logger.info("Nouveau fichier CSV détecté ! Lancement de la mise à jour du profil...")
                    _last_csv_mtime = current_mtime
                
                subprocess.run(
                    [sys.executable, "src/main.py", "update-profile"],
                    check=True
                )
    except subprocess.CalledProcessError as exc:
        logger.error("Erreur lors de l'exécution de update-profile : %s", exc)
    except Exception as exc:
        logger.error("Erreur lors de la vérification du CSV : %s", exc)

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
    
    # Vérification toutes les 5 minutes pour un nouveau CSV
    schedule.every(5).minutes.do(check_and_update_profile)
    
    # Lancement immédiat au démarrage pour vérifier l'état
    check_and_update_profile()
    
    # Boucle infinie
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
