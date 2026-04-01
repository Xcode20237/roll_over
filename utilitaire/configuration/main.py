"""
main.py
-------
Point d'entrée du programme de configuration des recettes.

Workflow :
  1. ScreenSelection  → choisir type de bouteille + service
  2. ScreenConfiguration → configurer les défauts

Variable d'environnement :
  QC_DATA_DIR  → répertoire de stockage des recettes et images
  Exemple :
    Windows : set QC_DATA_DIR=C:/QualityControl/data
    Linux   : export QC_DATA_DIR=/opt/qc/data
    Dev     : QC_DATA_DIR=./data python main.py
  Si non défini : dossier 'data/' dans le répertoire parent de configuration/
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

# Ajouter le dossier configuration/ au path pour les imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Recharger BASE_DIR maintenant que QC_DATA_DIR est potentiellement défini
from shared.core.recipe_manager import reload_base_dir, get_data_dir
reload_base_dir()

from ui.screen_selection     import ScreenSelection
from ui.screen_configuration import ScreenConfiguration


def main():
    data_dir = get_data_dir()

    print("=" * 55)
    print("  Roll-over QC — Programme de Configuration")
    print(f"  Répertoire données : {data_dir}")
    print("=" * 55)

    # Créer le répertoire de données s'il n'existe pas
    data_dir.mkdir(parents=True, exist_ok=True)

    # ---- Écran 1 : Sélection ----
    sel = ScreenSelection()
    sel.mainloop()

    type_btl, service, description = sel.get_selection()

    if type_btl is None or service is None:
        print("Programme fermé sans sélection.")
        return

    print(f"→ Type : {type_btl}  |  Service : {service}")

    # ---- Écran 2 : Configuration ----
    cfg = ScreenConfiguration(type_btl, service, description)
    cfg.mainloop()

    print("Programme de configuration terminé.")


if __name__ == "__main__":
    main()