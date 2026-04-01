"""
sobel_utils.py
--------------
Fonctions de détection de surface liquide par Sobel Y.
Partagées entre configuration et inspection.
Aucune dépendance Tkinter.
"""

from __future__ import annotations
from typing import Tuple
import cv2
import numpy as np


# ---------------------------------------------------------------------------
# CLAHE partagé
# ---------------------------------------------------------------------------

def make_clahe(clip_limit: float = 2.5, tile: int = 8) -> cv2.CLAHE:
    return cv2.createCLAHE(clipLimit=clip_limit,
                           tileGridSize=(tile, tile))


# ---------------------------------------------------------------------------
# Détection surface liquide
# ---------------------------------------------------------------------------

def detect_surface(
    roi_gray  : np.ndarray,
    clahe     : cv2.CLAHE,
    ksize     : int = 3,
) -> Tuple[float, np.ndarray, np.ndarray]:
    """
    Détecte la surface du liquide dans un ROI en niveaux de gris.

    Pipeline :
      1. GaussianBlur  — suppression bruit haute fréquence
      2. CLAHE         — normalisation locale du contraste
      3. Sobel Y       — gradient vertical
      4. Profil        — moyenne horizontale du gradient absolu
      5. argmax        — pic dominant = ligne de surface
      6. Sous-pixel    — interpolation parabolique

    Retourne (y_surface_subpx, sobel_vis, profil_vis).
    """
    h, w = roi_gray.shape

    # 1. Blur
    blurred = cv2.GaussianBlur(roi_gray, (5, 5), 0)

    # 2. CLAHE
    eq = clahe.apply(blurred)

    # 3. Sobel Y
    sobel_y   = cv2.Sobel(eq, cv2.CV_64F, 0, 1, ksize=ksize)
    sobel_abs = np.abs(sobel_y)

    # Visualisation Sobel normalisée
    sobel_vis = cv2.normalize(
        sobel_abs, None, 0, 255, cv2.NORM_MINMAX
    ).astype(np.uint8)

    # 4. Profil vertical
    profil = np.mean(sobel_abs, axis=1)

    # Visualisation profil (barres horizontales)
    profil_vis = np.zeros((h, 256), dtype=np.uint8)
    pmax = float(np.max(profil)) if np.max(profil) > 0 else 1.0
    for row in range(h):
        blen = int((profil[row] / pmax) * 255)
        cv2.line(profil_vis, (0, row), (blen, row), 200, 1)

    # 5. Pic principal
    y_peak = int(np.argmax(profil))

    # 6. Raffinement parabolique sous-pixel (±0.5 px max)
    if 1 <= y_peak <= h - 2:
        p_m = profil[y_peak - 1]
        p_0 = profil[y_peak]
        p_p = profil[y_peak + 1]
        den = 2.0 * (2 * p_0 - p_m - p_p)
        sub = ((p_p - p_m) / den) if abs(den) > 1e-6 else 0.0
        sub = max(-0.5, min(0.5, sub))
        y_surface = y_peak + sub
    else:
        y_surface = float(y_peak)

    # Marquer le pic sur le profil
    cv2.line(profil_vis, (0, y_peak), (255, y_peak), 255, 1)

    return y_surface, sobel_vis, profil_vis


# ---------------------------------------------------------------------------
# Calcul de distance ancre → surface
# ---------------------------------------------------------------------------

def compute_distance(
    y_surface_local : float,
    roi_y_global    : int,
    anchor_cy       : float,
) -> float:
    """
    distance_px = (roi_y_global + y_surface_local) - anchor_cy

    Positif → surface en dessous de l'ancre (cas nominal)
    Négatif → surface au-dessus de l'ancre (sur-remplissage extrême)
    """
    return (roi_y_global + y_surface_local) - anchor_cy


# ---------------------------------------------------------------------------
# Détection automatique pour la calibration
# ---------------------------------------------------------------------------

def auto_detect_surface(
    roi_gray  : np.ndarray,
    clahe     : cv2.CLAHE,
) -> int:
    """
    Détecte automatiquement la ligne liquide.
    Retourne y_local (entier) — point de départ du slider de calibration.
    """
    y_surface, _, _ = detect_surface(roi_gray, clahe)
    return int(round(y_surface))


# ---------------------------------------------------------------------------
# Mesure de la largeur de la bouteille au niveau détecté (Canny)
# ---------------------------------------------------------------------------

def mesure_largeur_au_niveau(
    roi_gray    : np.ndarray,
    y_surface   : float,
    canny_low   : int = 50,
    canny_high  : int = 150,
    marge_py    : int = 3,
) -> float:
    """
    Mesure la largeur de la bouteille à la hauteur y_surface via Canny.

    Stratégie :
      1. Applique Canny sur le ROI en niveaux de gris
      2. Sur une bande de ±marge_py lignes autour de y_surface,
         trouve le premier pixel non-nul (bord gauche) et
         le dernier (bord droit) sur chaque ligne
      3. Retourne la médiane des largeurs mesurées dans cette bande
         → robuste aux pixels parasites

    Retourne 0.0 si aucun contour détecté dans la bande.
    """
    h, w = roi_gray.shape

    blurred = cv2.GaussianBlur(roi_gray, (5, 5), 0)
    edges   = cv2.Canny(blurred, canny_low, canny_high)

    y_int    = int(round(y_surface))
    y_start  = max(0,   y_int - marge_py)
    y_end    = min(h,   y_int + marge_py + 1)

    largeurs = []
    for row_idx in range(y_start, y_end):
        row     = edges[row_idx, :]
        nonzero = np.where(row > 0)[0]
        if len(nonzero) >= 2:
            largeurs.append(float(nonzero[-1] - nonzero[0]))

    if not largeurs:
        return 0.0

    return round(float(np.median(largeurs)), 2)