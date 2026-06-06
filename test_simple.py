#!/usr/bin/env python3
"""
Test simple des différents modes.
"""

import time
import sys
sys.path.append('src')

from src.catalogue.sources.openlibrary import fetch_all_sff_works

# Test rapide
print("Test des différents modes (10 livres max)...")
print("=" * 50)

modes = [
    ("line_by_line", {"read_mode": "line_by_line"}),
    ("buffered", {"read_mode": "buffered", "buffer_size": 512}),
    ("hybrid", {"read_mode": "hybrid", "buffer_size": 512, "num_threads": 2}),
]

for mode, params in modes:
    print(f"\n--- Test du mode: {mode} ---")
    
    start_time = time.time()
    count = 0
    
    try:
        for i, book in enumerate(fetch_all_sff_works(max_per_subject=10, **params)):
            count += 1
            if count >= 10:
                break
        
        end_time = time.time()
        duration = end_time - start_time
        speed = count / duration if duration > 0 else 0
        
        print(f"  OK {count} livres en {duration:.2f}s ({speed:.1f} livres/s)")
        
    except Exception as e:
        print(f"  ERREUR: {e}")

print("\nTest terminé !")