"""
scheduler.py — Tâche de fond pour le conteneur Docker.

Garde le conteneur en vie et exécute:
- build-catalogue chaque dimanche
- noosfere-process-month le 10 de chaque mois (mois précédent)
Remplace l'usage de cron sur l'hôte, rendant le conteneur 100% autonome.
"""

import logging
import subprocess
import time
import sys
from datetime import date
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
            if current_mtime > _last_csv_mtime:
                if _last_csv_mtime == 0.0:
                    _last_csv_mtime = current_mtime
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
        subprocess.run(
            [sys.executable, "src/main.py", "build-catalogue"],
            check=True
        )
        logger.info("Tâche hebdomadaire terminée avec succès.")
    except subprocess.CalledProcessError as exc:
        logger.error("Erreur lors de l'exécution de build-catalogue : %s", exc)


def run_noosfere_month_scraping():
    """Scrape les livres du mois précédent sur Noosfere le 10 de chaque mois."""
    today = date.today()
    if today.day != 10:
        return
    
    year = today.year
    month = today.month - 1 if today.month > 1 else 12
    if today.month == 1:
        year = today.year - 1
    
    logger.info("Démarrage du scraping Noosfere pour %d/%d", month, year)
    try:
        subprocess.run(
            [sys.executable, "src/main.py", "noosfere-process-month", "--year", str(year), "--month", str(month)],
            check=True
        )
        logger.info("Scraping Noosfere terminé avec succès.")
        
        subprocess.run(
            [sys.executable, "src/main.py", "noosfere-process-queue"],
            check=True
        )
        logger.info("Traitement file d'attente Noosfere terminé.")
    except subprocess.CalledProcessError as exc:
        logger.error("Erreur lors du scraping Noosfere : %s", exc)


def main():
    logger.info("Scheduler autonome démarré.")
    logger.info("Le catalogue sera mis à jour chaque dimanche à 03:00.")
    logger.info("Le scraping Noosfere aura lieu chaque 10, traitant le mois précédent.")
    
    schedule.every().sunday.at("03:00").do(run_build_catalogue)
    schedule.every().day.at("10:00").do(run_noosfere_month_scraping)
    schedule.every(5).minutes.do(check_and_update_profile)
    
    check_and_update_profile()
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
