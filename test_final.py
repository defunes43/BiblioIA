#!/usr/bin/env python3
"""
Test des différents modes de lecture avec les vrais dumps.
"""

import time
import sys
sys.path.append('src')

from src.catalogue.sources.openlibrary import fetch_all_sff_works

# Test des différents modes
modes = [
    ("line_by_line", {"read_mode": "line_by_line"}),
    ("buffered", {"read_mode": "buffered", "buffer_size": 1024}),
    ("hybrid", {"read_mode": "hybrid", "buffer_size": 8192, "num_threads": 2}),
]

print("Test des différents modes de lecture...")
print("=" * 60)

results = {}

for mode, params in modes:
    print(f"\n--- Test du mode: {mode} ---")
    
    start_time = time.time()
    count = 0
    
    try:
        # Limite à 50 livres pour le test rapide
        for i, book in enumerate(fetch_all_sff_works(max_per_subject=50, **params)):
            count += 1
            if count >= 50:  # Limite pour le test
                break
        
        end_time = time.time()
        duration = end_time - start_time
        
        results[mode] = {
            "count": count,
            "duration": duration,
            "speed": count / duration if duration > 0 else 0
        }
        
        print(f"  Terminé: {count} livres en {duration:.2f}s ({count/duration:.1f} livres/s)")
        
    except Exception as e:
        print(f"  Erreur: {e}")
        results[mode] = {"error": str(e)}

# Affiche les résultats
print("\n" + "="*60)
print("RÉSUMÉ DES PERFORMANCES")
print("="*60)

for mode, result in results.items():
    if "error" in result:
        print(f"{mode:12}: ERREUR - {result['error']}")
    else:
        print(f"{mode:12}: {result['count']:6d} livres en {result['duration']:6.2f}s ({result['speed']:6.1f} livres/s)")

print("\nTest terminé !")