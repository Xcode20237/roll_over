"""
popup_presence_hsv.py
---------------------
Popup de calibration pour l'algorithme presence_hsv.
Affiche : Original | Masque binaire | Objet isolé
Sliders : H_min, H_max, S_min, S_max, V_min, V_max
          Tolérance min%, Tolérance max%
Indicateur : ROUGE CIRC. ACTIF si H_min > H_max
"""

from __future__ import annotations
from typing import Any, Dict, Optional
import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np

from ui.popups.popup_base import PopupBase
from shared.algorithms.hsv_utils import (
    apply_hsv_mask, clean_mask, auto_hsv_params,
    is_rouge_circulaire, inspect_presence_hsv
)


class PopupPresenceHSV(PopupBase):

    def __init__(
        self,
        parent,
        roi_image  : np.ndarray,
        hsv_params : Optional[Dict] = None,
        tol_min_pct: float = 80.0,
        tol_max_pct: float = 120.0,
    ):
        # Paramètres initiaux
        init = hsv_params or auto_hsv_params(roi_image)
        self._p = {k: tk.IntVar(value=v) for k, v in init.items()}
        self._tol_min = tk.DoubleVar(value=tol_min_pct)
        self._tol_max = tk.DoubleVar(value=tol_max_pct)

        # Aire de référence calculée après init
        self._area_ref   : int   = 0
        self._rouge_label: Optional[tk.Label] = None

        super().__init__(parent, roi_image,
                         title="Calibration HSV — Présence",
                         width=960, height=680)

    # ------------------------------------------------------------------
    def build_controls(self, frame: ttk.LabelFrame):
        frame.columnconfigure(1, weight=1)

        def refresh(_=None):
            self.schedule_preview_update()

        rows = [
            ("H_min (0-179)", self._p["h_min"], 0,   179),
            ("H_max (0-179)", self._p["h_max"], 0,   179),
            ("S_min (0-255)", self._p["s_min"], 0,   255),
            ("S_max (0-255)", self._p["s_max"], 0,   255),
            ("V_min (0-255)", self._p["v_min"], 0,   255),
            ("V_max (0-255)", self._p["v_max"], 0,   255),
        ]
        for i, (lbl, var, lo, hi) in enumerate(rows):
            self._add_slider(frame, lbl, var, lo, hi, row=i,
                             on_change=refresh)

        # Indicateur rouge circulaire
        self._rouge_label = tk.Label(
            frame, text="", font=("Arial", 9, "bold"),
            fg="orange",
        )
        self._rouge_label.grid(row=0, column=3, rowspan=2, padx=10)

        # Séparateur
        ttk.Separator(frame, orient="horizontal").grid(
            row=6, column=0, columnspan=4, sticky="ew", pady=6)

        # Aire de référence
        self._lbl_area = tk.Label(frame, text="Aire référence : — px",
                                  font=("Arial", 10, "bold"))
        self._lbl_area.grid(row=7, column=0, columnspan=2,
                            sticky="w", padx=6)

        # Tolérances
        self._add_slider(frame, "Tolérance min (%)",
                         self._tol_min, 10, 100, row=8,
                         on_change=refresh, decimals=1)
        self._add_slider(frame, "Tolérance max (%)",
                         self._tol_max, 100, 300, row=9,
                         on_change=refresh, decimals=1)

        # Labels min/max calculés
        self._lbl_minmax = tk.Label(frame, text="",
                                    font=("Arial", 9, "italic"),
                                    fg="#555555")
        self._lbl_minmax.grid(row=10, column=0, columnspan=4,
                               sticky="w", padx=6, pady=2)

    # ------------------------------------------------------------------
    def update_preview(self):
        params = {k: v.get() for k, v in self._p.items()}

        mask_brut, mask_clean, isolated, area = inspect_presence_hsv(
            self.roi_image, params
        )

        self._area_ref = area
        self._lbl_area.config(text=f"Aire référence : {area} px")

        min_a = int(area * self._tol_min.get() / 100)
        max_a = int(area * self._tol_max.get() / 100)
        self._lbl_minmax.config(
            text=f"  → min_area = {min_a} px  |  max_area = {max_a} px"
        )

        # Indicateur rouge circulaire
        if is_rouge_circulaire(params):
            self._rouge_label.config(text="⚠ ROUGE\nCIRC. ACTIF")
        else:
            self._rouge_label.config(text="")

        # Visualisation masque brut en couleur (rouge)
        mask_brut_vis = cv2.cvtColor(mask_brut, cv2.COLOR_GRAY2BGR)
        mask_brut_vis[mask_brut == 255] = [0, 0, 200]

        self._show_images_in_preview([
            ("Original",       self.roi_image),
            ("Masque HSV brut", mask_brut_vis),
            ("Masque nettoyé",  cv2.cvtColor(mask_clean, cv2.COLOR_GRAY2BGR)),
            ("Objet isolé",     isolated),
        ])

    # ------------------------------------------------------------------
    def get_result(self) -> Optional[Dict[str, Any]]:
        if not self._validated:
            return None
        params   = {k: v.get() for k, v in self._p.items()}
        area_ref = self._area_ref
        min_a    = int(area_ref * self._tol_min.get() / 100)
        max_a    = int(area_ref * self._tol_max.get() / 100)
        return {
            "hsv_params"   : params,
            "expected_area": area_ref,
            "min_area"     : min_a,
            "max_area"     : max_a,
        }
