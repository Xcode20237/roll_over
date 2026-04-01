"""
engine_check_position.py
------------------------
Engine d'inspection pour l'algorithme symmetry_canny.
Couvre : CP1.1 — Mauvais positionnement bouteille

Pipeline :
  1. Image originale (BGR)
  2. Conversion niveaux de gris
  3. Détection axe de symétrie via Canny (symmetry_utils)
  4. Calcul de l'écart axe / centre image
  5. Verdict par comparaison à la tolérance recette

Particularité :
  Le résultat inclut "ecart_px" dans les details — ce champ est
  lu par service_fusion pour le recadrage asymétrique.
"""

from __future__ import annotations
from typing import Optional
import cv2
import numpy as np

from shared.core.models import DefautConfig, ROIConfig
from shared.engines.engine_base import EngineBase, ROIResult
from shared.algorithms.symmetry_utils import (
    detect_symmetry_axis,
    compute_ecart_centre,
    check_position_verdict,
    draw_position_result,
)


class EngineCheckPosition(EngineBase):

    def __init__(self, defaut: DefautConfig,
                 ref_image: Optional[np.ndarray]):
        super().__init__(defaut, ref_image)

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

        canny_low    = roi_cfg.canny_low    or 50
        canny_high   = roi_cfg.canny_high   or 150
        tolerance_px = roi_cfg.tolerance_ecart_px or 15.0

        # --- Détection axe de symétrie ---
        axe_x, edges, vis_axe, centres = detect_symmetry_axis(
            gray, canny_low, canny_high
        )

        # --- Calcul de l'écart ---
        _, w_roi = gray.shape
        ecart_px = compute_ecart_centre(axe_x, w_roi)

        # --- Verdict ---
        result   = check_position_verdict(ecart_px, tolerance_px)
        status   = result["status"]

        # --- Visualisation résultat ---
        result_vis = draw_position_result(
            gray, axe_x, ecart_px, tolerance_px, status
        )

        # Annotation nb lignes valides
        color = (0, 220, 0) if status == "OK" else (0, 0, 220)
        cv2.putText(result_vis,
                    f"{len(centres)} lignes valides",
                    (5, result_vis.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                    (150, 150, 150), 1)

        steps = {
            "1. Original"          : roi_img.copy(),
            "2. Niveaux de gris"   : cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR),
            "3. Contours Canny"    : cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR),
            "4. Axe symétrie"      : vis_axe,
            "5. Résultat position" : result_vis,
        }

        return ROIResult(
            roi_name  = roi_cfg.name,
            roi_type  = roi_cfg.type,
            status    = status,
            mesure    = round(abs(ecart_px), 2),
            reference = 0.0,
            tolerance = (0.0, float(tolerance_px)),
            ecart     = ecart_px,          # signé — utile pour fusion asymétrique
            details   = result,
            steps     = steps,
        )
