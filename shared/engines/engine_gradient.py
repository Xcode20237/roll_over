"""
engine_gradient.py
------------------
Engine d'inspection pour l'algorithme niveau_sobel.
Couvre : D2.1, D2.2

Pipeline :
  1. Image originale
  2. Niveaux de gris + CLAHE
  3. Sobel Y → détection surface liquide (y_surface)
  4. Canny   → largeur bouteille au niveau détecté (largeur_px)
  5. Ratio   = distance_px / largeur_px
  → Verdict par comparaison ratio mesuré / ratio_ref ± tolerance

Principe physique :
  Le ratio distance/largeur est indépendant du scale caméra/bouteille.
  Si la bouteille recule, distance ET largeur diminuent dans les mêmes
  proportions → ratio constant. Seul un vrai défaut de niveau modifie
  le ratio, pas un changement de distance de prise de vue.
"""

from __future__ import annotations
from typing import Optional
import cv2
import numpy as np

from shared.core.models import DefautConfig, ROIConfig
from shared.engines.engine_base import EngineBase, ROIResult
from shared.algorithms.sobel_utils import (
    make_clahe, detect_surface, compute_distance,
    mesure_largeur_au_niveau,
)


class EngineGradient(EngineBase):

    def __init__(self, defaut: DefautConfig,
                 ref_image: Optional[np.ndarray]):
        super().__init__(defaut, ref_image)
        self._clahe = make_clahe()

    # ------------------------------------------------------------------
    def _inspect_roi(
        self,
        roi_img      : np.ndarray,
        roi_cfg      : ROIConfig,
        anchor_cy    : float,
        roi_y_global : int,
        scale        : float = 1.0,
    ) -> ROIResult:

        # --- Prétraitement ---
        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY) \
               if len(roi_img.shape) == 3 else roi_img.copy()
        eq   = self._clahe.apply(gray)

        # --- Détection surface (Sobel Y) ---
        y_surface_local, sobel_vis, profil_vis = detect_surface(gray, self._clahe)

        # --- Distance ancre → surface ---
        distance_px = compute_distance(y_surface_local, roi_y_global, anchor_cy)

        # --- Largeur bouteille au niveau détecté (Canny) ---
        canny_low   = roi_cfg.canny_low  or 50
        canny_high  = roi_cfg.canny_high or 150
        largeur_px  = mesure_largeur_au_niveau(
            gray, y_surface_local, canny_low, canny_high
        )

        # --- Calcul du ratio ---
        if largeur_px > 0:
            ratio = round(distance_px / largeur_px, 4)
        else:
            ratio = None   # contours non détectés → erreur

        # --- Verdict par ratio ---
        ratio_ref     = roi_cfg.ratio_ref          or 0.0
        tol_ratio_min = roi_cfg.tolerance_ratio_min or 0.0
        tol_ratio_max = roi_cfg.tolerance_ratio_max or 9999.0

        if ratio is None:
            status = "NG"
            defect = "CONTOURS_NON_DETECTES"
        elif ratio_ref <= 0:
            # Pas de référence calibrée → fallback distance absolue
            dist_min = roi_cfg.distance_min_px or 0.0
            dist_max = roi_cfg.distance_max_px or 9999.0
            status   = "OK" if dist_min <= distance_px <= dist_max else "NG"
            defect   = None
        else:
            status = "OK" if tol_ratio_min <= ratio <= tol_ratio_max else "NG"
            defect = None
            if status == "NG":
                defect = "NIVEAU_HAUT" if ratio < tol_ratio_min else "NIVEAU_BAS"

        # --- Details ---
        details: dict = {
            "y_surface_local"  : round(float(y_surface_local), 2),
            "y_surface_global" : round(float(roi_y_global + y_surface_local), 2),
            "anchor_cy"        : round(float(anchor_cy), 2),
            "distance_px"      : round(float(distance_px), 2),
            "largeur_px"       : largeur_px,
            "ratio"            : ratio,
            "ratio_ref"        : ratio_ref,
            "tol_ratio_min"    : tol_ratio_min,
            "tol_ratio_max"    : tol_ratio_max,
        }
        if defect:
            details["defect"] = defect

        # --- Visualisation ---
        h, w       = gray.shape
        result_vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        y_draw     = int(round(y_surface_local))
        color      = (0, 220, 0) if status == "OK" else (0, 0, 220)

        # Ligne surface détectée
        cv2.line(result_vis, (0, y_draw), (w, y_draw), color, 2)

        # Largeur au niveau — dessiner les bords Canny détectés
        blurred_vis = cv2.GaussianBlur(gray, (5, 5), 0)
        edges_vis   = cv2.Canny(blurred_vis, canny_low, canny_high)
        edges_bgr   = cv2.cvtColor(edges_vis, cv2.COLOR_GRAY2BGR)

        # Ligne ancre
        anchor_y_in_roi = int(anchor_cy - roi_y_global)
        if 0 <= anchor_y_in_roi < h:
            for x in range(0, w, 8):
                cv2.line(result_vis, (x, anchor_y_in_roi),
                         (min(x + 4, w), anchor_y_in_roi), (0, 165, 255), 1)
            cv2.putText(result_vis, "ancre",
                        (5, max(12, anchor_y_in_roi - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 165, 255), 1)

        # Annotations
        ratio_str = f"{ratio:.4f}" if ratio is not None else "N/A"
        cv2.putText(result_vis,
                    f"ratio={ratio_str}  {status}",
                    (5, max(16, y_draw - 18)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
        cv2.putText(result_vis,
                    f"dist={distance_px:.1f}px  larg={largeur_px:.1f}px",
                    (5, max(30, y_draw - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1)
        cv2.putText(result_vis,
                    f"Tol ratio:[{tol_ratio_min:.4f} - {tol_ratio_max:.4f}]",
                    (5, max(44, y_draw + 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34, (180, 180, 180), 1)

        steps = {
            "1. Original"        : roi_img.copy(),
            "2. Niveaux de gris" : cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR),
            "3. CLAHE"           : cv2.cvtColor(eq, cv2.COLOR_GRAY2BGR),
            "4. Sobel Y"         : cv2.cvtColor(sobel_vis, cv2.COLOR_GRAY2BGR),
            "5. Profil gradient" : cv2.cvtColor(profil_vis, cv2.COLOR_GRAY2BGR),
            "6. Canny contours"  : edges_bgr,
            "7. Résultat ratio"  : result_vis,
        }

        return ROIResult(
            roi_name  = roi_cfg.name,
            roi_type  = roi_cfg.type,
            status    = status,
            mesure    = ratio if ratio is not None else 0.0,
            reference = float(ratio_ref),
            tolerance = (float(tol_ratio_min), float(tol_ratio_max)),
            ecart     = round((ratio - ratio_ref), 4) if ratio is not None else 0.0,
            details   = details,
            steps     = steps,
        )