"""
engine_colorimetrique.py
------------------------
Engine d'inspection pour les algorithmes colorimetriques.

Algorithmes couverts :
  presence_hsv     → D3.1, D3.3, D2.4, D4.1, D4.4
                     Pipeline : HSV → masque → aire → verdict
  orientation_masque → D3.2 (Bouchon de travers)
                     Pipeline : HSV → masque → orientation + décentrage → verdict

Chantier 4 — image fusionnée :
  Si roi_cfg.use_fused_image is True, l'image reçue est l'image fusionnée
  (panorama) au lieu d'une image d'angle. Cela est transparent pour les
  algorithmes — la logique d'acquisition de l'image fusionnée est gérée
  en amont dans service_colorimetrique.py.
"""

from __future__ import annotations
from typing import Optional
import cv2
import numpy as np

from shared.core.models import DefautConfig, ROIConfig
from shared.engines.engine_base import EngineBase, ROIResult
from shared.algorithms.hsv_utils import (
    apply_hsv_mask, clean_mask,
    inspect_presence_hsv, is_rouge_circulaire,
)
from shared.algorithms.orientation_utils import analyse_orientation, draw_orientation_result


class EngineColorimetrique(EngineBase):

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

        algo = self._defaut.algorithme

        if algo == "presence_hsv":
            return self._inspect_presence(roi_img, roi_cfg)
        elif algo == "orientation_masque":
            return self._inspect_orientation(roi_img, roi_cfg)
        else:
            raise ValueError(f"Algorithme colorimétrique inconnu : '{algo}'")

    # ------------------------------------------------------------------
    # PRESENCE HSV — comptage de pixels (D3.1, D3.3, D2.4, D4.1, D4.4)
    # ------------------------------------------------------------------
    def _inspect_presence(
        self,
        roi_img : np.ndarray,
        roi_cfg : ROIConfig,
    ) -> ROIResult:

        hsv_params = roi_cfg.hsv_params or {
            "h_min": 0, "h_max": 179,
            "s_min": 0, "s_max": 255,
            "v_min": 0, "v_max": 255,
        }

        # --- Pipeline HSV ---
        hsv_img                     = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
        mask_brut                   = apply_hsv_mask(roi_img, hsv_params)
        mask_clean                  = clean_mask(mask_brut)
        isolated                    = np.zeros_like(roi_img)
        isolated[mask_clean == 255] = roi_img[mask_clean == 255]
        area_measured               = int(cv2.countNonZero(mask_clean))

        # --- Verdict ---
        min_area = roi_cfg.min_area  or 0
        max_area = roi_cfg.max_area  or 999999
        expected = roi_cfg.expected_area or 0
        status   = "OK" if min_area <= area_measured <= max_area else "NG"

        roi_area   = roi_cfg.width * roi_cfg.height
        fill_ratio = round(area_measured / roi_area, 3) if roi_area > 0 else 0.0

        details: dict = {
            "fill_ratio" : fill_ratio,
            "rouge_circ" : is_rouge_circulaire(hsv_params),
        }

        if expected > 0:
            if area_measured < expected * 0.3:
                details["alert"] = "OBJET_ABSENT"
            elif area_measured > expected * 1.5:
                details["alert"] = "OBJET_SURDIMENSIONNE"

        if status == "NG" and "alert" not in details:
            details["defect"] = "AIRE_INSUFFISANTE" if area_measured < min_area \
                                                     else "AIRE_EXCESSIVE"

        # --- Visualisations ---
        mask_vis = cv2.cvtColor(mask_brut, cv2.COLOR_GRAY2BGR)
        mask_vis[mask_brut == 255] = [0, 0, 200]

        mask_clean_vis = cv2.cvtColor(mask_clean, cv2.COLOR_GRAY2BGR)
        mask_clean_vis[mask_clean == 255] = [0, 180, 0]

        result_vis = isolated.copy()
        color = (0, 220, 0) if status == "OK" else (0, 0, 220)
        cv2.putText(result_vis,
                    f"Aire={area_measured}px  {status}",
                    (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        cv2.putText(result_vis,
                    f"Tol:[{min_area}-{max_area}]",
                    (5, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (200, 200, 200), 1)

        steps = {
            "1. Original"        : roi_img.copy(),
            "2. Image HSV"       : hsv_img.copy(),
            "3. Masque HSV brut" : mask_vis,
            "4. Masque nettoyé"  : mask_clean_vis,
            "5. Objet isolé"     : result_vis,
        }

        return ROIResult(
            roi_name  = roi_cfg.name,
            roi_type  = roi_cfg.type,
            status    = status,
            mesure    = float(area_measured),
            reference = float(expected),
            tolerance = (float(min_area), float(max_area)),
            ecart     = float(area_measured - expected),
            details   = details,
            steps     = steps,
        )

    # ------------------------------------------------------------------
    # ORIENTATION MASQUE — inclinaison + décentrage (D3.2)
    # ------------------------------------------------------------------
    def _inspect_orientation(
        self,
        roi_img : np.ndarray,
        roi_cfg : ROIConfig,
    ) -> ROIResult:

        hsv_params = roi_cfg.hsv_params or {
            "h_min": 0, "h_max": 179,
            "s_min": 0, "s_max": 255,
            "v_min": 0, "v_max": 255,
        }

        tol_angle      = roi_cfg.tolerance_angle_deg    or 5.0
        tol_decentrage = roi_cfg.tolerance_decentrage_px or 10.0

        # --- Pipeline HSV → masque propre ---
        hsv_img    = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
        mask_brut  = apply_hsv_mask(roi_img, hsv_params)
        mask_clean = clean_mask(mask_brut)

        isolated = np.zeros_like(roi_img)
        isolated[mask_clean == 255] = roi_img[mask_clean == 255]

        # --- Analyse orientation sur le masque ---
        result  = analyse_orientation(mask_clean, tol_angle, tol_decentrage)
        status  = result["status"]

        # --- Visualisation résultat ---
        result_vis = draw_orientation_result(roi_img, mask_clean, result)

        # Visualisation masque brut
        mask_vis = cv2.cvtColor(mask_brut, cv2.COLOR_GRAY2BGR)
        mask_vis[mask_brut == 255] = [0, 0, 200]

        mask_clean_vis = cv2.cvtColor(mask_clean, cv2.COLOR_GRAY2BGR)
        mask_clean_vis[mask_clean == 255] = [0, 180, 0]

        steps = {
            "1. Original"        : roi_img.copy(),
            "2. Image HSV"       : hsv_img.copy(),
            "3. Masque HSV brut" : mask_vis,
            "4. Masque nettoyé"  : mask_clean_vis,
            "5. Objet isolé"     : isolated,
            "6. Orientation"     : result_vis,
        }

        # Mesure principale = angle (décentrage dans details)
        return ROIResult(
            roi_name  = roi_cfg.name,
            roi_type  = roi_cfg.type,
            status    = status,
            mesure    = abs(result.get("angle_deg", 0.0)),
            reference = 0.0,
            tolerance = (0.0, float(tol_angle)),
            ecart     = result.get("angle_deg", 0.0),
            details   = result,
            steps     = steps,
        )
