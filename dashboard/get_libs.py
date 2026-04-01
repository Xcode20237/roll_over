"""
get_libs.py
-----------
Télécharge Chart.js, Socket.IO et Lucide Icons en local pour le mode hors-internet.
Lancer UNE SEULE FOIS sur un poste connecté :

    python get_libs.py

Les fichiers sont ensuite disponibles dans static/js/ pour tous les postes.
"""
import urllib.request
import os

LIBS = [
    (
        "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js",
        "static/js/chart.min.js",
        "Chart.js 4.4.0",
    ),
    (
        "https://cdn.socket.io/4.6.1/socket.io.min.js",
        "static/js/socket.io.min.js",
        "Socket.IO 4.6.1",
    ),
    (
        "https://unpkg.com/lucide@0.441.0/dist/umd/lucide.js",
        "static/js/lucide.js",
        "Lucide Icons 0.441.0",
    ),
]

for url, dest, name in LIBS:
    print(f"Téléchargement : {name} ...", end=" ", flush=True)
    try:
        urllib.request.urlretrieve(url, dest)
        size = os.path.getsize(dest)
        print(f"OK ({size//1024} Ko) → {dest}")
    except Exception as e:
        print(f"ERREUR : {e}")
        print(f"  Télécharger manuellement : {url}")
        print(f"  Sauvegarder dans         : {dest}")

print("\nTerminé. Relancer main_dashboard.py.")
