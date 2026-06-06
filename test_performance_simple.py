#!/usr/bin/env python3
"""
Test simple des différentes approches avec les dumps existants.
"""

import time
import sys
from pathlib import Path

# Ajoute le chemin des dumps pour le test
sys.path.append('src')
sys.path.append('.')

from src.catalogue.sources.openlibrary import fetch_all_sff_works

print("Test du chargement des dumps...")
print("DUMP_DIR:", Path("/data").resolve())
print("WORKS_DUMP exists:", (Path("/data") / "ol_dump_works_2026-05-31.txt.gz").exists())
print("AUTHORS_DUMP exists:", (Path("/data") / "ol_dump_authors_2026-05-31.txt.gz").exists())

# Test des différents modes
modes = [
    ("line_by_line", {"buffer_size": 1, "parallel": False}),
    ("buffered", {"buffer_size": 1024, "parallel": False}),
]

results = {}

print("\nTest des différents modes de lecture...")
print("=" * 50)

for mode, params in modes:
    print(f"\n--- Test du mode: {mode} ---")
    
    start_time = time.time()
    count = 0
    
    try:
        # Limite à 100 livres pour le test rapide
        for i, book in enumerate(fetch_all_sff_works(read_mode=mode, max_per_subject=100, **params)):
            count += 1
            if count >= 100:  # Limite pour le test
                break
        
        end_time = time.time()
        duration = end_time - start_time
        
        results[mode] = {
            "count": count,
            "duration": duration,
            "speed": count / duration if duration > 0 else 0
        }
        
        print(f"  Terminé: {count} livres en {duration:.2f}s ({count/duration:.0f} livres/s)")
        
    except Exception as e:
        print(f"  Erreur: {e}")
        results[mode] = {"error": str(e)}

# Affiche les résultats
print("\n" + "="*50)
print("RÉSUMÉ DES PERFORMANCES")
print("="*50)

for mode, result in results.items():
    if "error" in result:
        print(f"{mode:12}: ERREUR - {result['error']}")
    else:
        print(f"{mode:12}: {result['count']:6d} livres en {result['duration']:6.2f}s ({result['speed']:6.0f} livres/s)")

print("\nTest terminé !")