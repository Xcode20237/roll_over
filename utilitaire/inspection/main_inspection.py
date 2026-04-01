"""
main_inspection.py
------------------
Point d'entrée du programme d'inspection UI.

Usage :
  python main_inspection.py

Variable d'environnement :
  QC_DATA_DIR → répertoire de données (même que le programme de configuration)
"""

import sys
import os
# Charger le .env depuis la racine du projet
from dotenv import load_dotenv
from pathlib import Path

# Remonte jusqu'à trouver le .env
_here = Path(__file__).resolve()
for _parent in [_here.parent, _here.parent.parent, _here.parent.parent.parent]:
    _env = _parent / ".env"
    if _env.exists():
        load_dotenv(_env)
        print(f"📄 .env chargé depuis : {_env}")
        break

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.core.recipe_manager import reload_base_dir, get_data_dir
reload_base_dir()

from ui.screen_inspection import ScreenInspection


def main():
    data_dir = get_data_dir()

    print("=" * 55)
    print("  Roll-over QC — Inspection UI")
    print(f"  Répertoire données : {data_dir}")
    print("=" * 55)

    app = ScreenInspection()
    app.mainloop()

    print("Programme d'inspection terminé.")


if __name__ == "__main__":
    main()
