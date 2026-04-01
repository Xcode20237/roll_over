"""
height_utils.py
---------------
Fonctions de mesure de hauteur par profil d'intensité.
Partagées entre configuration et inspection.
"""

from __future__ import annotations
from typing import Tuple, Dict
import cv2
import numpy as np


def detect_top(
    gray        : np.ndarray,
    y_ref_rel   : int,
    margin_top  : int = 5,
) -> int:
    """
    Détecte le sommet de l'objet par profil d'intensité du tiers central.

    Pipeline :
      1. Moyenne horizontale sur le tiers central
      2. Gradient discret np.gradient
      3. argmax dans la zone de recherche [margin_top : 2/3 * y_ref_rel]

    Retourne y_measured_top (entier, coordonnée locale dans le ROI).
    """
    h, w = gray.shape

    center_zone = gray[:, w // 3: 2 * w // 3]
    profile     = np.mean(center_zone, axis=1)
    gradient    = np.abs(np.gradient(profile.astype(float)))

    search_limit = int(y_ref_rel * 2 / 3)
    if search_limit < 10:
        search_limit = int(y_ref_rel)

    search_zone = gradient[margin_top:search_limit]
    if len(search_zone) > 0:
        y_top = margin_top + int(np.argmax(search_zone))
    else:
        y_top = 0

    return y_top


def measure_height(
    gray      : np.ndarray,
    y_ref_rel : int,
) -> Tuple[int, int, Dict]:
    """
    Mesure complète de hauteur.

    Retourne (y_top_detected, height_measured, details).
    """
    y_top           = detect_top(gray, y_ref_rel)
    height_measured = y_ref_rel - y_top

    details = {
        "y_top_detected": y_top,
        "y_reference"   : y_ref_rel,
        "height_measured": height_measured,
    }
    return y_top, height_measured, details


def draw_height_result(
    gray        : np.ndarray,
    y_top       : int,
    y_ref       : int,
    status      : str,
) -> np.ndarray:
    """
    Dessine les deux lignes de mesure sur l'image :
    - Ligne rouge  : sommet détecté
    - Ligne bleue  : ligne de référence (col)
    """
    vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    w   = vis.shape[1]

    color = (0, 255, 0) if status == "OK" else (0, 0, 255)
    cv2.line(vis, (0, y_top), (w, y_top), color,        2)
    cv2.line(vis, (0, y_ref), (w, y_ref), (255, 100, 0), 2)

    h_px = y_ref - y_top
    cv2.putText(vis, f"h={h_px}px  {status}",
                (5, max(15, y_top - 5)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return vis
