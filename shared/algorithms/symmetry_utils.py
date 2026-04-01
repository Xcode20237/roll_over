"""
symmetry_utils.py
-----------------
Détection de l'axe de symétrie d'un objet cylindrique dans un ROI.

Algorithme :
  1. Prétraitement : flou gaussien + Canny
  2. Extraction des points de bord gauche et droit ligne par ligne
  3. Calcul de l'axe de symétrie = nuage équidistant des deux bords
  4. Mesure de l'écart entre l'axe de symétrie et le centre de l'image

Générique — aucune notion de bouteille ou d'objet spécifique.
Aucune dépendance Tkinter.
"""

from __future__ import annotations
from typing import Tuple, List, Dict
import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def detect_symmetry_axis(
    roi_gray  : np.ndarray,
    canny_low : int = 50,
    canny_high: int = 150,
) -> Tuple[float, np.ndarray, np.ndarray, List[float]]:
    """
    Détecte l'axe de symétrie vertical de l'objet dans le ROI.

    Pipeline :
      1. GaussianBlur — suppression du bruit
      2. Canny — extraction des contours
      3. Pour chaque ligne : premier pixel non-nul (bord gauche)
         et dernier pixel non-nul (bord droit)
      4. Centre ligne par ligne : x_c(y) = (x_gauche + x_droite) / 2
      5. Axe de symétrie = médiane de tous les x_c(y)
         → robuste aux lignes parasites

    Retourne :
      axe_x        : position X de l'axe de symétrie (pixels, dans le ROI)
      edges        : image Canny (pour visualisation)
      vis          : image BGR annotée avec l'axe et les bords
      centres      : liste des x_c(y) ligne par ligne
    """
    h, w = roi_gray.shape

    # 1. Flou + Canny
    blurred = cv2.GaussianBlur(roi_gray, (5, 5), 0)
    edges   = cv2.Canny(blurred, canny_low, canny_high)

    # 2. Extraction bords gauche/droit + centres ligne par ligne
    left_pts  : List[Tuple[int, int]] = []
    right_pts : List[Tuple[int, int]] = []
    centres   : List[float]           = []

    for row_idx in range(h):
        row     = edges[row_idx, :]
        nonzero = np.where(row > 0)[0]
        if len(nonzero) >= 2:
            x_left  = int(nonzero[0])
            x_right = int(nonzero[-1])
            x_c     = (x_left + x_right) / 2.0
            left_pts.append((x_left,  row_idx))
            right_pts.append((x_right, row_idx))
            centres.append(x_c)

    # 3. Axe de symétrie = médiane des centres (robuste aux outliers)
    if centres:
        axe_x = float(np.median(centres))
    else:
        axe_x = float(w / 2)   # fallback : centre image

    # 4. Visualisation
    vis = cv2.cvtColor(roi_gray, cv2.COLOR_GRAY2BGR)

    # Bords gauche (bleu) et droit (rouge)
    for pt in left_pts:
        cv2.circle(vis, pt, 1, (255, 100, 0), -1)
    for pt in right_pts:
        cv2.circle(vis, pt, 1, (0, 100, 255), -1)

    # Axe de symétrie détecté (vert)
    axe_x_int = int(round(axe_x))
    cv2.line(vis, (axe_x_int, 0), (axe_x_int, h), (0, 220, 0), 2)

    # Centre image (blanc pointillé)
    cx = w // 2
    for y in range(0, h, 8):
        cv2.line(vis, (cx, y), (cx, min(y + 4, h)), (200, 200, 200), 1)

    return axe_x, edges, vis, centres


# ---------------------------------------------------------------------------
# Calcul de l'écart
# ---------------------------------------------------------------------------

def compute_ecart_centre(axe_x: float, image_width: int) -> float:
    """
    Calcule l'écart entre l'axe de symétrie détecté et le centre de l'image.

        ecart_px = axe_x - (image_width / 2)

    Positif → objet décalé à droite du centre
    Négatif → objet décalé à gauche du centre
    """
    return round(axe_x - image_width / 2.0, 2)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def check_position_verdict(
    ecart_px      : float,
    tolerance_px  : float,
) -> Dict:
    """
    Évalue si l'écart est dans la tolérance configurée.

    Retourne un dict de résultat compatible avec le format des engines :
      status       : "OK" | "NG"
      ecart_px     : écart mesuré (signé)
      ecart_abs_px : valeur absolue de l'écart
      tolerance_px : tolérance configurée
    """
    ecart_abs = abs(ecart_px)
    status    = "OK" if ecart_abs <= tolerance_px else "NG"

    result: Dict = {
        "status"      : status,
        "ecart_px"    : ecart_px,
        "ecart_abs_px": round(ecart_abs, 2),
        "tolerance_px": tolerance_px,
    }

    if status == "NG":
        result["defect"] = "MAUVAIS_POSITIONNEMENT"
        result["direction"] = "DROITE" if ecart_px > 0 else "GAUCHE"

    return result


# ---------------------------------------------------------------------------
# Visualisation résultat annoté
# ---------------------------------------------------------------------------

def draw_position_result(
    gray        : np.ndarray,
    axe_x       : float,
    ecart_px    : float,
    tolerance_px: float,
    status      : str,
) -> np.ndarray:
    """
    Dessine le résultat complet sur l'image :
      - Axe de symétrie détecté (vert si OK, rouge si NG)
      - Centre de l'image (blanc)
      - Flèche d'écart
      - Texte annoté
    """
    vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    h, w = vis.shape[:2]

    color  = (0, 220, 0) if status == "OK" else (0, 0, 220)
    cx     = w // 2
    axe_xi = int(round(axe_x))

    # Centre image (blanc)
    cv2.line(vis, (cx, 0), (cx, h), (180, 180, 180), 1)

    # Axe symétrie
    cv2.line(vis, (axe_xi, 0), (axe_xi, h), color, 2)

    # Flèche écart (milieu de l'image)
    mid_y = h // 2
    if abs(ecart_px) > 1:
        cv2.arrowedLine(vis, (cx, mid_y), (axe_xi, mid_y),
                        color, 2, tipLength=0.3)

    # Texte
    cv2.putText(vis,
                f"ecart={ecart_px:+.1f}px  {status}",
                (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    cv2.putText(vis,
                f"tol=+/-{tolerance_px:.0f}px",
                (5, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                (180, 180, 180), 1)

    return vis


# ---------------------------------------------------------------------------
# Paramètres Canny automatiques (réutilisé depuis canny_utils)
# ---------------------------------------------------------------------------

def auto_canny_params(roi_gray: np.ndarray) -> Tuple[int, int]:
    """
    Calcule des seuils Canny initiaux via la méthode de la médiane.
    Retourne (canny_low, canny_high).
    """
    blurred = cv2.GaussianBlur(roi_gray, (5, 5), 0)
    median  = float(np.median(blurred))
    sigma   = 0.33
    low     = int(max(0,   (1.0 - sigma) * median))
    high    = int(min(255, (1.0 + sigma) * median))
    return low, high
