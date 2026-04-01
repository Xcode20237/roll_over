"""
recipe_manager.py
-----------------
Gestion complète des fichiers recette JSON :
  - Recherche de la version active (la plus récente)
  - Chargement / sauvegarde avec versioning
  - Listage des types de bouteilles disponibles
  - Jamais d'écrasement sans confirmation explicite
"""

from __future__ import annotations
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from shared.core.models import RecetteConfig


# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------

def _get_base_dir() -> Path:
    """
    Retourne le répertoire racine des données (recettes + images).

    Priorité :
      1. Variable d'environnement QC_DATA_DIR  (chemin absolu ou relatif)
      2. Fallback : dossier 'data/' à côté de main.py (parent du dossier configuration/)

    Exemples :
      Windows : QC_DATA_DIR=C:/QualityControl/data
      Linux   : QC_DATA_DIR=/opt/qc/data
      Dev     : QC_DATA_DIR=./data   (relatif au répertoire courant)
    """
    env_dir = os.getenv("QC_DATA_DIR", "")
    if env_dir:
        p = Path(env_dir)
        # Si chemin relatif → on le considère relatif à la RACINE du projet (parent de services/)
        if not p.is_absolute():
            # Path(__file__) est services/core/recipe_manager.py
            root = Path(__file__).resolve().parent.parent.parent
            p = root / p
        return p.resolve()

    # Fallback : dossier 'data/' dans le parent du dossier configuration/
    # structure : projet/
    #               main.py  (ou configuration/main.py)
    #               data/
    #                 recettes/
    fallback = Path(__file__).resolve().parent.parent / "data"
    return fallback


BASE_DIR = _get_base_dir()


def reload_base_dir():
    """
    Recharge BASE_DIR depuis l'environnement.
    Utile si QC_DATA_DIR est défini après l'import du module.
    """
    global BASE_DIR
    BASE_DIR = _get_base_dir()
    print(f"📁 Répertoire données : {BASE_DIR}")


def get_data_dir() -> Path:
    """Retourne le répertoire de données actif (pour affichage dans l'UI)."""
    return BASE_DIR


def _recipe_dir(service: str, type_btl: str) -> Path:
    """Retourne le dossier recettes/<service>/<type_btl>/"""
    return BASE_DIR / "recettes" / service / type_btl

def _image_ref_dir(service: str, type_btl: str) -> Path:
    """Retourne le dossier des images de référence."""
    return _recipe_dir(service, type_btl)


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

def _version_files(service: str, type_btl: str) -> List[Path]:
    """
    Retourne la liste triée de tous les fichiers recette_v*.json
    pour un service et un type de bouteille donnés.
    """
    folder = _recipe_dir(service, type_btl)
    print(f"🔍 [RECETTE] Scan dossier : {folder}")
    if not folder.exists():
        print(f"   ⚠️ Dossier introuvable : {folder}")
        return []
    pattern = re.compile(r"^recette_v(\d+)\.json$")
    files = []
    for f in folder.iterdir():
        m = pattern.match(f.name)
        if m:
            files.append((int(m.group(1)), f))
    files.sort(key=lambda t: t[0])
    return [f for _, f in files]


def get_active_version(service: str, type_btl: str) -> Optional[Path]:
    """Retourne le chemin de la version active (numéro le plus élevé)."""
    files = _version_files(service, type_btl)
    return files[-1] if files else None


def get_current_version_number(service: str, type_btl: str) -> int:
    """Retourne le numéro de version actuel (0 si aucune version)."""
    folder = _recipe_dir(service, type_btl)
    print(f"🔍 [RECETTE] Scan dossier : {folder}")
    if not folder.exists():
        return 0
    files = _version_files(service, type_btl)
    if not files:
        return 0
    m = re.match(r"recette_v(\d+)\.json$", files[-1].name)
    return int(m.group(1)) if m else 0


def get_version_history(service: str, type_btl: str) -> List[Tuple[int, Path]]:
    """Retourne la liste (version, path) de toutes les versions."""
    files = _version_files(service, type_btl)
    result = []
    for f in files:
        m = re.match(r"recette_v(\d+)\.json$", f.name)
        if m:
            result.append((int(m.group(1)), f))
    return result


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------

def load_active(service: str, type_btl: str) -> Optional[RecetteConfig]:
    """
    Charge la version active de la recette.
    Retourne None si aucune recette n'existe.
    """
    path = get_active_version(service, type_btl)
    if path is None:
        return None
    return load_from_path(path)


def load_from_path(path: Path) -> RecetteConfig:
    """Charge une recette depuis un chemin absolu."""
    print(f"📖 [RECETTE] Chargement : {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return RecetteConfig.from_dict(data)


def load_version(service: str, type_btl: str, version: int) -> Optional[RecetteConfig]:
    """Charge une version spécifique."""
    folder = _recipe_dir(service, type_btl)
    path   = folder / f"recette_v{version}.json"
    if not path.exists():
        return None
    return load_from_path(path)


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------

def save_new_version(recette: RecetteConfig) -> Path:
    """
    Sauvegarde la recette en créant une NOUVELLE version.
    Recopie tous les défauts non modifiés de la version précédente
    si elle existe.
    Version n+1 créée.
    Retourne le chemin du fichier créé.
    """
    folder = _recipe_dir(recette.service, recette.type_bouteille)
    folder.mkdir(parents=True, exist_ok=True)

    new_version = get_current_version_number(recette.service,
                                             recette.type_bouteille) + 1
    recette.version    = new_version
    recette.created_at = datetime.now().isoformat()

    path = folder / f"recette_v{new_version}.json"
    _write(recette, path)
    print(f"✅ Recette sauvegardée (nouvelle version v{new_version}) : {path}")
    return path


def save_overwrite(recette: RecetteConfig) -> Path:
    """
    Écrase la version active sans incrémenter le numéro.
    À utiliser uniquement sur demande explicite de l'opérateur.
    Retourne le chemin du fichier mis à jour.
    """
    folder = _recipe_dir(recette.service, recette.type_bouteille)
    folder.mkdir(parents=True, exist_ok=True)

    current = get_current_version_number(recette.service,
                                         recette.type_bouteille)
    if current == 0:
        # Pas de version existante → crée v1
        return save_new_version(recette)

    recette.created_at = datetime.now().isoformat()
    path = folder / f"recette_v{current}.json"
    _write(recette, path)
    print(f"✅ Recette mise à jour (version v{current} écrasée) : {path}")
    return path


def _write(recette: RecetteConfig, path: Path):
    """Sérialise et écrit le JSON avec indentation."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(recette.to_dict(), f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Images de référence
# ---------------------------------------------------------------------------

def get_ref_image_path(service: str, type_btl: str,
                        id_defaut: str) -> Optional[Path]:
    """
    Retourne le chemin de l'image de référence pour un défaut donné.
    Convention : ref_<id_defaut>.bmp  (ex: ref_D3.1.bmp)
    Retourne None si le fichier n'existe pas.
    """
    folder = _image_ref_dir(service, type_btl)
    # Accepte .bmp, .jpg, .jpeg, .png
    for ext in (".bmp", ".jpg", ".jpeg", ".png"):
        p = folder / f"ref_{id_defaut}{ext}"
        if p.exists():
            return p
    return None


def save_ref_image(src_path: str, service: str,
                   type_btl: str, id_defaut: str) -> Path:
    """
    Copie l'image source dans le dossier recette sous le nom
    ref_<id_defaut>.<ext>.
    Retourne le chemin de destination.
    """
    folder = _image_ref_dir(service, type_btl)
    folder.mkdir(parents=True, exist_ok=True)

    src  = Path(src_path)
    dest = folder / f"ref_{id_defaut}{src.suffix.lower()}"
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest


def get_relative_image_path(service: str, type_btl: str,
                             id_defaut: str) -> str:
    """
    Retourne le chemin relatif de l'image de référence
    tel qu'il sera stocké dans le JSON.
    Ex : "./ref_D3.1.bmp"
    """
    p = get_ref_image_path(service, type_btl, id_defaut)
    if p is None:
        return ""
    return f"./{p.name}"


# ---------------------------------------------------------------------------
# Listage des types de bouteilles
# ---------------------------------------------------------------------------

def list_types(service: str) -> List[str]:
    """
    Retourne la liste des types de bouteilles existants
    pour un service donné.
    """
    base = BASE_DIR / "recettes" / service
    if not base.exists():
        return []
    return sorted([
        d.name for d in base.iterdir()
        if d.is_dir() and len(_version_files(service, d.name)) > 0
    ])


def list_all_types() -> dict:
    """
    Retourne un dict {service: [type_btl, ...]} pour tous les services.
    """
    from shared.core.models import SERVICES
    return {svc: list_types(svc) for svc in SERVICES}


# ---------------------------------------------------------------------------
# Fusion intelligente de versions
# ---------------------------------------------------------------------------

def merge_with_previous(new_recette: RecetteConfig) -> RecetteConfig:
    """
    Lors d'une sauvegarde nouvelle version, recopie dans new_recette
    tous les blocs défauts de la version précédente qui ne sont PAS
    présents dans new_recette (défauts non modifiés lors de cette session).

    Règle : si le défaut existe dans les deux versions, new_recette gagne.
    Si le défaut existe seulement dans l'ancienne version, il est conservé.
    """
    previous = load_active(new_recette.service, new_recette.type_bouteille)
    if previous is None:
        return new_recette

    new_ids = {d.id_defaut for d in new_recette.defauts}
    for old_defaut in previous.defauts:
        if old_defaut.id_defaut not in new_ids:
            new_recette.defauts.append(old_defaut)

    # Tri par id_defaut pour lisibilité
    new_recette.defauts.sort(key=lambda d: d.id_defaut)
    return new_recette
