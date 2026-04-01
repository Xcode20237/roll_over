"""
canny_utils.py
--------------
Fonctions de traitement géométrique par Canny.
Partagées entre configuration et inspection.
Aucune dépendance Tkinter.
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Optional
import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Prétraitement commun
# ---------------------------------------------------------------------------

def preprocess(roi_gray: np.ndarray,
               canny_low: int = 50,
               canny_high: int = 150) -> Tuple[np.ndarray, np.ndarray]:
    blurred = cv2.GaussianBlur(roi_gray, (5, 5), 0)
    edges   = cv2.Canny(blurred, canny_low, canny_high)
    return blurred, edges


# ---------------------------------------------------------------------------
# Profil largeur ligne par ligne
# ---------------------------------------------------------------------------

def measure_widths(
    edges: np.ndarray,
) -> Tuple[List[int], List[Tuple[int, int]], List[Tuple[int, int]]]:
    widths    : List[int]              = []
    left_pts  : List[Tuple[int, int]]  = []
    right_pts : List[Tuple[int, int]]  = []

    for row_idx in range(edges.shape[0]):
        row     = edges[row_idx, :]
        nonzero = np.where(row > 0)[0]
        if len(nonzero) >= 2:
            left_pts.append((int(nonzero[0]),   row_idx))
            right_pts.append((int(nonzero[-1]), row_idx))
            widths.append(int(nonzero[-1] - nonzero[0]))

    return widths, left_pts, right_pts


# ---------------------------------------------------------------------------
# Analyse profil avec normalisation scale systématique
# ---------------------------------------------------------------------------

def analyse_profil_normalise(
    widths            : List[int],
    min_largeur       : float,
    max_largeur       : float,
    max_ecart_type    : float,
    max_pct_ng        : float,
    largeur_reference : float,
) -> Dict:
    """
    Analyse du profil avec normalisation d échelle systématique.

    Pipeline :
      1. Calcule la médiane des largeurs brutes mesurées
      2. Si largeur_reference > 0 :
           scale = mediane_mesuree / largeur_reference
           widths_norm = [w / scale for w in widths]
         Sinon : scale = 1.0, widths_norm = widths
      3. Evalue sur widths_norm :
           - ecart-type      -> profil irregulier
           - % lignes NG     -> defaut localise
      4. Verdict : NG si ecart-type > max_ecart_type
                      OU % lignes NG > max_pct_ng

    La mediane de reference sert UNIQUEMENT au calcul du scale.
    Le verdict est independant de l echelle de prise de vue.
    """
    if not widths:
        return {
            "status"           : "NG",
            "error"            : "Aucun contour detecte",
            "scale"            : 1.0,
            "mediane_brute_px" : 0.0,
            "mediane_norm_px"  : 0.0,
            "ecart_type_px"    : 0.0,
            "pct_lignes_ng"    : 100.0,
            "nb_lignes_valides": 0,
            "nb_lignes_ng"     : 0,
            "status_ecart_type": "NG",
            "status_pct_ng"    : "NG",
        }

    # Etape 1 : mediane brute
    mediane_brute = float(np.median(widths))

    # Etape 2 : scale et normalisation
    if largeur_reference > 0 and mediane_brute > 0:
        scale = mediane_brute / largeur_reference
    else:
        scale = 1.0

    widths_norm = [w / scale for w in widths]

    # Etape 3 : metriques sur widths normalises
    mediane_norm  = float(np.median(widths_norm))
    ecart_type_px = round(float(np.std(widths_norm)), 2)
    nb_ng         = sum(1 for w in widths_norm
                        if not (min_largeur <= w <= max_largeur))
    pct_lignes_ng = round(100.0 * nb_ng / len(widths_norm), 2)

    # Etape 4 : verdict
    st_ecart = "OK" if ecart_type_px <= max_ecart_type else "NG"
    st_pct   = "OK" if pct_lignes_ng <= max_pct_ng     else "NG"
    status   = "OK" if (st_ecart == "OK" and st_pct == "OK") else "NG"

    result: Dict = {
        "status"            : status,
        "scale"             : round(scale, 4),
        "mediane_brute_px"  : round(mediane_brute, 2),
        "mediane_norm_px"   : round(mediane_norm, 2),
        "largeur_reference" : largeur_reference,
        "ecart_type_px"     : ecart_type_px,
        "pct_lignes_ng"     : pct_lignes_ng,
        "nb_lignes_valides" : len(widths_norm),
        "nb_lignes_ng"      : nb_ng,
        "status_ecart_type" : st_ecart,
        "status_pct_ng"     : st_pct,
    }

    if st_ecart == "NG":
        result["defect_ecart"] = "PROFIL_IRREGULIER"
    if st_pct == "NG":
        result["defect_pct"] = "DEFAUT_LOCALISE"

    return result


# ---------------------------------------------------------------------------
# Derive du centre (col tordu)
# ---------------------------------------------------------------------------

def compute_derive_centre(
    left_pts : List[Tuple[int, int]],
    right_pts: List[Tuple[int, int]],
) -> Tuple[float, List[float]]:
    if len(left_pts) < 2:
        return 0.0, []
    centres = [
        (lp[0] + rp[0]) / 2.0
        for lp, rp in zip(left_pts, right_pts)
    ]
    derive_px = abs(centres[-1] - centres[0])
    return round(derive_px, 2), centres


# ---------------------------------------------------------------------------
# Visualisation profil couleur
# ---------------------------------------------------------------------------

def draw_profil_color(
    gray      : np.ndarray,
    left_pts  : List[Tuple[int, int]],
    right_pts : List[Tuple[int, int]],
    widths    : List[int],
) -> np.ndarray:
    vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    if not widths:
        return vis
    w_min = min(widths)
    span  = max(max(widths) - w_min, 1)
    for lp, rp, wi in zip(left_pts, right_pts, widths):
        norm  = (wi - w_min) / span
        color = (0, int(255 * (1 - norm)), int(255 * norm))
        cv2.line(vis, lp, rp, color, 1)
    return vis


# ---------------------------------------------------------------------------
# Initialisation automatique seuils Canny
# ---------------------------------------------------------------------------

def auto_canny_params(roi_gray: np.ndarray) -> Tuple[int, int]:
    blurred = cv2.GaussianBlur(roi_gray, (5, 5), 0)
    median  = float(np.median(blurred))
    sigma   = 0.33
    low     = int(max(0,   (1.0 - sigma) * median))
    high    = int(min(255, (1.0 + sigma) * median))
    return low, high