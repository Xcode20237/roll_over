"""
engine_geometrique.py
---------------------
Engine d'inspection pour les algorithmes profil_canny et derive_centre.
Couvre : D1.4, D4.2 (profil_canny) et D1.5 (derive_centre)

profil_canny  → triple critère : médiane, écart-type, % lignes NG
               + barrière scale si pct_ng ≥ 90% ET profil régulier
derive_centre → dérive du centre x_c(y) sur la hauteur du col
"""

from __future__ import annotations
from typing import Optional
import cv2
import numpy as np

from shared.core.models import DefautConfig, ROIConfig
from shared.engines.engine_base import EngineBase, ROIResult
from shared.algorithms.canny_utils import (
    preprocess, measure_widths,
    analyse_profil_normalise,
    draw_profil_color, compute_derive_centre,
)


class EngineGeometrique(EngineBase):

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

        if algo == "profil_canny":
            return self._inspect_profil(roi_img, roi_cfg, scale)
        elif algo == "derive_centre":
            return self._inspect_derive(roi_img, roi_cfg, scale)
        else:
            raise ValueError(f"Algorithme inconnu : '{algo}'")

    # ------------------------------------------------------------------
    # PROFIL CANNY — triple critère + barrière scale
    # ------------------------------------------------------------------
    def _inspect_profil(
        self,
        roi_img : np.ndarray,
        roi_cfg : ROIConfig,
        scale   : float = 1.0,
    ) -> ROIResult:

        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY) \
               if len(roi_img.shape) == 3 else roi_img.copy()

        canny_low  = roi_cfg.canny_low  or 50
        canny_high = roi_cfg.canny_high or 150

        blurred, edges = preprocess(gray, canny_low, canny_high)
        widths, lp, rp = measure_widths(edges)

        min_l = roi_cfg.min_largeur_px       or 0.0
        max_l = roi_cfg.max_largeur_px       or 9999.0
        max_s = roi_cfg.max_ecart_type_px    or 9999.0
        max_p = roi_cfg.max_pct_lignes_ng    or 100.0
        ref_l = roi_cfg.largeur_reference_px or 0.0

        # --- Analyse normalisée ---
        result = analyse_profil_normalise(
            widths, min_l, max_l, max_s, max_p,
            largeur_reference=ref_l,
        )
        status = result["status"]

        # --- Visualisations ---
        edges_vis  = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        profil_vis = draw_profil_color(gray, lp, rp, widths)

        result_vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        for pt in lp:
            cv2.circle(result_vis, pt, 1, (255, 100, 0), -1)
        for pt in rp:
            cv2.circle(result_vis, pt, 1, (0, 100, 255), -1)

        color = (0, 220, 0) if status == "OK" else (0, 0, 220)
        if lp and rp:
            mid = len(lp) // 2
            cv2.line(result_vis, lp[mid], rp[mid], color, 2)

        h_vis = result_vis.shape[0]
        y0    = max(h_vis - 80, 10)
        c_ok, c_ng = (0, 200, 0), (0, 0, 200)

        def _st_color(st): return c_ok if st == "OK" else c_ng

        cv2.putText(result_vis,
            f"Scale={result['scale']:.3f} | "
            f"Med.brute={result['mediane_brute_px']:.0f}px | "
            f"Ref={ref_l:.0f}px",
            (5, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.35,
            (180, 180, 180), 1)
        cv2.putText(result_vis,
            f"Sig:{result['ecart_type_px']:.1f}px "
            f"[{result['status_ecart_type']}]",
            (5, y0 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
            _st_color(result["status_ecart_type"]), 1)
        cv2.putText(result_vis,
            f"NG:{result['pct_lignes_ng']:.1f}% "
            f"[{result['status_pct_ng']}]",
            (5, y0 + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
            _st_color(result["status_pct_ng"]), 1)

        steps = {
            "1. Original"        : roi_img.copy(),
            "2. Niveaux de gris" : cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR),
            "3. Contours Canny"  : edges_vis,
            "4. Profil largeurs" : profil_vis,
            "5. Résultat"        : result_vis,
        }

        return ROIResult(
            roi_name  = roi_cfg.name,
            roi_type  = roi_cfg.type,
            status    = status,
            mesure    = result["mediane_brute_px"],
            reference = float(ref_l),
            tolerance = (float(min_l), float(max_l)),
            ecart     = round(result["mediane_brute_px"] - float(ref_l), 2),
            details   = result,
            steps     = steps,
        )

    # ------------------------------------------------------------------
    # DÉRIVE CENTRE — col tordu
    # ------------------------------------------------------------------
    def _inspect_derive(
        self,
        roi_img : np.ndarray,
        roi_cfg : ROIConfig,
        scale   : float = 1.0,
    ) -> ROIResult:

        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY) \
               if len(roi_img.shape) == 3 else roi_img.copy()

        canny_low  = roi_cfg.canny_low  or 50
        canny_high = roi_cfg.canny_high or 150
        derive_max = roi_cfg.derive_max_px or 5.0

        blurred, edges = preprocess(gray, canny_low, canny_high)
        widths, lp, rp = measure_widths(edges)

        derive_px_brute, centres = compute_derive_centre(lp, rp)
        # Correction echelle MSTM : derive corrigee = derive_brute / scale
        # Si la bouteille est plus petite (scale<1), la derive brute est sous-estimee
        derive_px = derive_px_brute / scale if scale > 0 else derive_px_brute
        status = "OK" if derive_px <= derive_max else "NG"

        details : dict = {
            "derive_px"       : round(derive_px, 2),
            "derive_px_brute" : round(derive_px_brute, 2),
            "derive_max"      : derive_max,
            "scale_applique"  : round(scale, 4),
            "nb_lignes"       : len(lp),
        }
        if status == "NG":
            details["defect"] = "COL_TORDU"

        # --- Visualisations ---
        edges_vis   = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        centre_vis  = cv2.cvtColor(gray,  cv2.COLOR_GRAY2BGR)

        for pt in lp:
            cv2.circle(centre_vis, pt, 1, (255, 100, 0), -1)
        for pt in rp:
            cv2.circle(centre_vis, pt, 1, (0, 100, 255), -1)
        for i, c in enumerate(centres):
            row = lp[i][1] if i < len(lp) else i
            cv2.circle(centre_vis, (int(c), row), 1, (0, 220, 0), -1)

        color = (0, 220, 0) if status == "OK" else (0, 0, 220)
        if len(centres) >= 2:
            cv2.line(centre_vis,
                     (int(centres[0]),  lp[0][1]),
                     (int(centres[-1]), lp[-1][1]),
                     (0, 255, 255), 2)

        cv2.putText(centre_vis,
                    f"Derive={derive_px:.1f}px  {status}",
                    (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1)
        cv2.putText(centre_vis,
                    f"Max={derive_max:.1f}px",
                    (5, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (200, 200, 200), 1)

        steps = {
            "1. Original"       : roi_img.copy(),
            "2. Niveaux de gris": cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR),
            "3. Contours Canny" : edges_vis,
            "4. Centre x_c(y)"  : centre_vis,
        }

        return ROIResult(
            roi_name  = roi_cfg.name,
            roi_type  = roi_cfg.type,
            status    = status,
            mesure    = float(derive_px),
            reference = 0.0,
            tolerance = (0.0, float(derive_max)),
            ecart     = float(derive_px),
            details   = details,
            steps     = steps,
        )