"""
orientation_utils.py
--------------------
Analyse d'orientation et de décentrage d'un objet à partir d'un masque binaire.

Générique — aucune notion de bouchon ou d'objet spécifique.
Fonctionne sur n'importe quel masque binaire propre (objet blanc, fond noir).
Aucune dépendance Tkinter.

Deux critères indépendants :
  1. Inclinaison  → cv2.minAreaRect sur le contour → angle en degrés
  2. Décentrage   → cv2.moments → centroïde cx vs centre du ROI

Chaque critère retourne OK ou NG séparément.
Le verdict global est NG si l'un des deux est NG.
"""

from __future__ import annotations
from typing import Tuple, Dict, Optional
import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Analyse d'orientation principale
# ---------------------------------------------------------------------------

def analyse_orientation(
    mask_clean      : np.ndarray,
    tol_angle_deg   : float,
    tol_decentrage_px: float,
) -> Dict:
    """
    Analyse l'orientation et le décentrage d'un objet depuis son masque binaire.

    Paramètres :
      mask_clean        : masque binaire propre (uint8, 0/255)
      tol_angle_deg     : tolérance d'inclinaison en degrés
      tol_decentrage_px : tolérance de décentrage en pixels

    Retourne un dict :
      status             : "OK" | "NG"
      angle_deg          : angle d'inclinaison mesuré (degrés)
      decentrage_px      : décentrage horizontal mesuré (px, signé)
      decentrage_abs_px  : valeur absolue du décentrage
      status_angle       : "OK" | "NG"
      status_decentrage  : "OK" | "NG"
      cx, cy             : coordonnées du centroïde
    """
    if mask_clean is None or mask_clean.size == 0:
        return _empty_result("MASQUE_VIDE")

    h, w = mask_clean.shape

    # --- Contours pour minAreaRect ---
    contours, _ = cv2.findContours(
        mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return _empty_result("AUCUN_CONTOUR")

    # Prendre le plus grand contour (l'objet principal)
    contour_principal = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour_principal) < 10:
        return _empty_result("CONTOUR_TROP_PETIT")

    # --- Critère 1 : Inclinaison via minAreaRect ---
    rect      = cv2.minAreaRect(contour_principal)
    angle_raw = float(rect[2])   # angle retourné par OpenCV : [-90, 0)

    # Normalisation de l'angle vers [-45, 45]
    # minAreaRect retourne un angle entre -90 et 0
    # On le ramène à une inclinaison "absolue" centrée sur 0
    rect_w, rect_h = rect[1]
    if rect_w < rect_h:
        angle_norm = angle_raw + 90.0
    else:
        angle_norm = angle_raw
    # Ramène dans [-45, 45]
    if angle_norm > 45:
        angle_norm -= 90.0

    angle_deg = round(angle_norm, 2)
    st_angle  = "OK" if abs(angle_deg) <= tol_angle_deg else "NG"

    # --- Critère 2 : Décentrage via moments ---
    M = cv2.moments(mask_clean)
    if M["m00"] == 0:
        return _empty_result("MOMENTS_NULS")

    cx = float(M["m10"] / M["m00"])
    cy = float(M["m01"] / M["m00"])

    # Décentrage = écart entre le centroïde et le centre horizontal du ROI
    decentrage_px     = round(cx - w / 2.0, 2)
    decentrage_abs_px = round(abs(decentrage_px), 2)
    st_decentrage     = "OK" if decentrage_abs_px <= tol_decentrage_px else "NG"

    # --- Verdict global ---
    status = "OK" if (st_angle == "OK" and st_decentrage == "OK") else "NG"

    result: Dict = {
        "status"            : status,
        "angle_deg"         : angle_deg,
        "tol_angle_deg"     : tol_angle_deg,
        "decentrage_px"     : decentrage_px,
        "decentrage_abs_px" : decentrage_abs_px,
        "tol_decentrage_px" : tol_decentrage_px,
        "status_angle"      : st_angle,
        "status_decentrage" : st_decentrage,
        "cx"                : round(cx, 1),
        "cy"                : round(cy, 1),
    }

    # Défauts sémantiques
    if st_angle == "NG":
        result["defect_angle"] = "INCLINE_DROITE" if angle_deg > 0 \
                                                   else "INCLINE_GAUCHE"
    if st_decentrage == "NG":
        result["defect_decentrage"] = "DECALE_DROITE" if decentrage_px > 0 \
                                                       else "DECALE_GAUCHE"

    return result


def _empty_result(raison: str) -> Dict:
    return {
        "status"           : "NG",
        "error"            : raison,
        "angle_deg"        : 0.0,
        "decentrage_px"    : 0.0,
        "decentrage_abs_px": 0.0,
        "status_angle"     : "NG",
        "status_decentrage": "NG",
        "cx"               : 0.0,
        "cy"               : 0.0,
    }


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

def draw_orientation_result(
    roi_bgr          : np.ndarray,
    mask_clean       : np.ndarray,
    result           : Dict,
) -> np.ndarray:
    """
    Dessine sur le ROI :
      - Rectangle orienté (minAreaRect) en vert/rouge selon verdict angle
      - Centroïde (cercle) + croix centre ROI selon verdict décentrage
      - Annotations texte
    """
    vis   = roi_bgr.copy()
    h, w  = vis.shape[:2]
    status = result.get("status", "NG")
    color  = (0, 220, 0) if status == "OK" else (0, 0, 220)

    c_angle = (0, 220, 0) if result.get("status_angle")     == "OK" else (0, 0, 220)
    c_decal = (0, 220, 0) if result.get("status_decentrage") == "OK" else (0, 0, 220)

    # Contour principal + rectangle orienté
    contours, _ = cv2.findContours(
        mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if contours:
        contour_principal = max(contours, key=cv2.contourArea)
        rect  = cv2.minAreaRect(contour_principal)
        box   = cv2.boxPoints(rect)
        box   = box.astype(int)
        cv2.drawContours(vis, [box], 0, c_angle, 2)

    # Centroïde
    cx = result.get("cx", w / 2)
    cy = result.get("cy", h / 2)
    cv2.circle(vis, (int(cx), int(cy)), 5, c_decal, -1)

    # Croix centre ROI
    cx_roi = w // 2
    cy_roi = h // 2
    cv2.line(vis, (cx_roi - 10, cy_roi), (cx_roi + 10, cy_roi), (180, 180, 180), 1)
    cv2.line(vis, (cx_roi, cy_roi - 10), (cx_roi, cy_roi + 10), (180, 180, 180), 1)

    # Ligne décentrage
    if abs(result.get("decentrage_px", 0)) > 1:
        cv2.arrowedLine(vis,
                        (cx_roi, int(cy)),
                        (int(cx),  int(cy)),
                        c_decal, 1, tipLength=0.3)

    # Annotations texte
    y0 = max(h - 56, 10)
    cv2.putText(vis,
                f"Angle={result.get('angle_deg', 0):.1f}° [{result.get('status_angle','?')}]",
                (5, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.38, c_angle, 1)
    cv2.putText(vis,
                f"Decal={result.get('decentrage_px', 0):+.1f}px [{result.get('status_decentrage','?')}]",
                (5, y0 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.38, c_decal, 1)
    cv2.putText(vis,
                f"→ {status}",
                (5, y0 + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1)

    return vis
