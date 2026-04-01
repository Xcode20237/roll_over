"""
hsv_utils.py
------------
Fonctions de traitement HSV partagées entre le programme de
configuration et les services d'inspection.
Aucune dépendance Tkinter — fonctions pures OpenCV/NumPy.
"""

from __future__ import annotations
from typing import Dict, Tuple
import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Masque HSV — gestion du rouge circulaire
# ---------------------------------------------------------------------------

def apply_hsv_mask(roi_bgr: np.ndarray, hsv_params: Dict[str, int]) -> np.ndarray:
    """
    Applique un masque HSV sur un ROI BGR.

    Gère automatiquement le cas du rouge circulaire (H_min > H_max) :
      Plage 1 : [H_min → 179]
      Plage 2 : [0     → H_max]

    Retourne un masque binaire : objet cible blanc, reste noir.
    """
    hsv   = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    h_min = int(hsv_params["h_min"])
    h_max = int(hsv_params["h_max"])
    s_min = int(hsv_params["s_min"])
    s_max = int(hsv_params["s_max"])
    v_min = int(hsv_params["v_min"])
    v_max = int(hsv_params["v_max"])

    if h_min <= h_max:
        mask = cv2.inRange(
            hsv,
            np.array([h_min, s_min, v_min], dtype=np.uint8),
            np.array([h_max, s_max, v_max], dtype=np.uint8),
        )
    else:
        # Rouge circulaire : union de deux plages
        mask = cv2.bitwise_or(
            cv2.inRange(hsv,
                        np.array([h_min, s_min, v_min], dtype=np.uint8),
                        np.array([179,   s_max, v_max], dtype=np.uint8)),
            cv2.inRange(hsv,
                        np.array([0,     s_min, v_min], dtype=np.uint8),
                        np.array([h_max, s_max, v_max], dtype=np.uint8)),
        )
    return mask


def is_rouge_circulaire(hsv_params: Dict[str, int]) -> bool:
    """Retourne True si les paramètres indiquent un rouge circulaire."""
    return int(hsv_params.get("h_min", 0)) > int(hsv_params.get("h_max", 179))


# ---------------------------------------------------------------------------
# Nettoyage morphologique
# ---------------------------------------------------------------------------

def clean_mask(mask: np.ndarray, kernel_size: int = 5) -> np.ndarray:
    """
    Applique une ouverture puis une fermeture morphologique
    avec un élément structurant elliptique.

    Open  : supprime les pixels parasites isolés (faux positifs)
    Close : comble les trous dans le masque (faux négatifs)
    """
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
    )
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    return mask


# ---------------------------------------------------------------------------
# Pipeline complet présence HSV
# ---------------------------------------------------------------------------

def inspect_presence_hsv(
    roi_bgr    : np.ndarray,
    hsv_params : Dict[str, int],
    kernel_size: int = 5,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Pipeline complet :
      1. Masque HSV brut
      2. Nettoyage morphologique
      3. Isolation colorée de l'objet

    Retourne (mask_brut, mask_clean, isolated_bgr, area_measured).
    """
    mask_brut  = apply_hsv_mask(roi_bgr, hsv_params)
    mask_clean = clean_mask(mask_brut, kernel_size)

    isolated = np.zeros_like(roi_bgr)
    isolated[mask_clean == 255] = roi_bgr[mask_clean == 255]

    area = int(cv2.countNonZero(mask_clean))
    return mask_brut, mask_clean, isolated, area


# ---------------------------------------------------------------------------
# Initialisation automatique des paramètres HSV
# ---------------------------------------------------------------------------

def auto_hsv_params(roi_bgr: np.ndarray,
                    margin_h: int = 15,
                    margin_sv: int = 60) -> Dict[str, int]:
    """
    Calcule des paramètres HSV initiaux à partir de la teinte médiane
    du ROI. Point de départ pour la calibration interactive.
    """
    hsv      = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    median_h = int(np.median(hsv[:, :, 0]))
    median_s = int(np.median(hsv[:, :, 1]))
    median_v = int(np.median(hsv[:, :, 2]))

    return {
        "h_min": max(0,   median_h - margin_h),
        "h_max": min(179, median_h + margin_h),
        "s_min": max(0,   median_s - margin_sv),
        "s_max": min(255, median_s + margin_sv),
        "v_min": max(0,   median_v - margin_sv),
        "v_max": min(255, median_v + margin_sv),
    }
