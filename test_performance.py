#!/usr/bin/env python3
"""
Test des différentes approches de lecture des dumps.
"""

import time
from pathlib import Path

# Crée des dumps test plus grands
def create_large_test_dumps():
    import tempfile
    import gzip
    import json
    
    # Plus de données pour un test significatif
    authors_data = []
    works_data = []
    
    # Génère 1000 auteurs
    for i in range(1000):
        authors_data.append(
            f"/type/author	/authors/OL_AUTHOR_{i:06d}	1	2021-12-26T21:32:18.029274	{{\"type\": {{\"key\": \"/type/author\"}}, \"name\": \"Author {i}\", \"key\": \"/authors/OL_AUTHOR_{i:06d}\"}}"
        )
    
    # Génère 5000 œuvres
    for i in range(5000):
        author_id = i % 1000  # Réutilise les auteurs
        subjects = ["science_fiction"] if i % 2 == 0 else ["fantasy"]
        
        works_data.append(
            f"/type	work	/works/OL_WORK_{i:06d}	{i}	2023-01-01T00:00:00Z	{{\"title\": \"Book {i}\", \"authors\": [{{\"type\": \"/type/author_role\", \"author\": {{\"key\": \"/authors/OL_AUTHOR_{author_id:06d}\"}}}}], \"subjects\": {json.dumps(subjects)}}}"
        )
    
    # Crée et compresse les fichiers
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write('\n'.join(authors_data))
        authors_file = Path(f.name)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write('\n'.join(works_data))
        works_file = Path(f.name)
    
    # Compresse
    for txt_file in [authors_file, works_file]:
        with open(txt_file, 'rb') as f_in:
            gz_file = txt_file.with_suffix('.txt.gz')
            with gzip.open(gz_file, 'wb') as f_out:
                f_out.write(f_in.read())
    
    return authors_file.with_suffix('.txt.gz'), works_file.with_suffix('.txt.gz')

# Test des différentes approches
def test_approaches():
    print("Création des dumps de test...")
    authors_gz, works_gz = create_large_test_dumps()
    
    # Modifie DUMP_DIR pour pointer vers les fichiers test
    import sys
    sys.path.append('src')
    
    from src.catalogue.sources.openlibrary import fetch_all_sff_works
    
    # Test des différents modes
    modes = [
        ("line_by_line", {"buffer_size": 1, "parallel": False}),
        ("buffered", {"buffer_size": 1024, "parallel": False}),
        ("buffered", {"buffer_size": 8192, "parallel": False}),
        ("parallel", {"parallel": True, "num_processes": 2, "chunk_size": 1000}),
    ]
    
    results = {}
    
    for mode, params in modes:
        print(f"\n--- Test du mode: {mode} ---")
        
        start_time = time.time()
        count = 0
        
        try:
            for book in fetch_all_sff_works(read_mode=mode, **params):
                count += 1
                if count % 1000 == 0:
                    print(f"  {count} livres traités...")
            
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
    
    # Affiche les résultats comparatifs
    print("\n" + "="*50)
    print("RÉSUMÉ DES PERFORMANCES")
    print("="*50)
    
    for mode, result in results.items():
        if "error" in result:
            print(f"{mode:12}: ERREUR - {result['error']}")
        else:
            print(f"{mode:12}: {result['count']:6d} livres en {result['duration']:6.2f}s ({result['speed']:6.0f} livres/s)")
    
    # Nettoyage
    authors_gz.unlink()
    works_gz.unlink()
    print("\nNettoyage terminé.")

if __name__ == "__main__":
    test_approaches()