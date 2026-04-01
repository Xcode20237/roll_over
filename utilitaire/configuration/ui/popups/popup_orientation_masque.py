"""
popup_orientation_masque.py
---------------------------
Popup de calibration pour l'algorithme orientation_masque.
Utilisé pour D3.2 (Bouchon de travers).

Pipeline affiché :
  Original | Masque HSV brut | Masque nettoyé | Orientation

Sliders :
  H_min, H_max, S_min, S_max, V_min, V_max  (isolation HSV)
  Tolérance angle (degrés)
  Tolérance décentrage (pixels)

Affichage live :
  Angle mesuré + statut
  Décentrage mesuré + statut
  Rectangle orienté (minAreaRect) sur le masque
"""

from __future__ import annotations
from typing import Any, Dict, Optional
import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np

from ui.popups.popup_base import PopupBase
from shared.algorithms.hsv_utils import (
    apply_hsv_mask, clean_mask, auto_hsv_params, is_rouge_circulaire
)
from shared.algorithms.orientation_utils import analyse_orientation, draw_orientation_result


class PopupOrientationMasque(PopupBase):

    def __init__(
        self,
        parent,
        roi_image           : np.ndarray,
        hsv_params          : Optional[Dict]  = None,
        tol_angle_deg       : float           = 5.0,
        tol_decentrage_px   : float           = 10.0,
    ):
        init = hsv_params or auto_hsv_params(roi_image)
        self._p = {k: tk.IntVar(value=v) for k, v in init.items()}

        self._tol_angle      = tk.DoubleVar(value=tol_angle_deg)
        self._tol_decentrage = tk.DoubleVar(value=tol_decentrage_px)

        self._rouge_label : Optional[tk.Label] = None
        self._lbl_angle   : Optional[tk.Label] = None
        self._lbl_decal   : Optional[tk.Label] = None
        self._lbl_verdict : Optional[tk.Label] = None

        super().__init__(parent, roi_image,
                         title="Calibration Orientation — Bouchon de travers (D3.2)",
                         width=980, height=720)

    # ------------------------------------------------------------------
    def build_controls(self, frame: ttk.LabelFrame):
        frame.columnconfigure(1, weight=1)

        def refresh(_=None):
            self.schedule_preview_update()

        # Sliders HSV
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
            frame, text="", font=("Arial", 9, "bold"), fg="orange"
        )
        self._rouge_label.grid(row=0, column=3, rowspan=2, padx=10)

        ttk.Separator(frame, orient="horizontal").grid(
            row=6, column=0, columnspan=4, sticky="ew", pady=6
        )

        # Résultats live
        res_frame = tk.Frame(frame, bg="#f4f4f4", relief="groove", bd=1)
        res_frame.grid(row=7, column=0, columnspan=4,
                       sticky="ew", padx=6, pady=4)

        self._lbl_angle = tk.Label(res_frame,
                                   text="Angle : — °",
                                   font=("Arial", 10, "bold"),
                                   bg="#f4f4f4")
        self._lbl_angle.pack(side="left", padx=12, pady=4)

        self._lbl_decal = tk.Label(res_frame,
                                   text="Décentrage : — px",
                                   font=("Arial", 10, "bold"),
                                   bg="#f4f4f4")
        self._lbl_decal.pack(side="left", padx=12)

        self._lbl_verdict = tk.Label(res_frame,
                                     text="—",
                                     font=("Arial", 11, "bold"),
                                     bg="#f4f4f4")
        self._lbl_verdict.pack(side="right", padx=12)

        ttk.Separator(frame, orient="horizontal").grid(
            row=8, column=0, columnspan=4, sticky="ew", pady=4
        )

        # Tolérances
        self._add_slider(frame, "Tolérance angle (°)",
                         self._tol_angle, 0, 45,
                         row=9, on_change=refresh, decimals=1)
        self._add_slider(frame, "Tolérance décentrage (px)",
                         self._tol_decentrage, 0, 100,
                         row=10, on_change=refresh, decimals=1)

        tk.Label(frame,
                 text="ℹ  Angle : inclinaison du bouchon (0° = droit)   |   "
                      "Décentrage : écart horizontal du centroïde vs centre ROI",
                 font=("Arial", 8, "italic"), fg="#555555",
                 wraplength=500, justify="left"
                 ).grid(row=11, column=0, columnspan=4,
                        sticky="w", padx=6, pady=4)

    # ------------------------------------------------------------------
    def update_preview(self):
        params = {k: v.get() for k, v in self._p.items()}

        mask_brut  = apply_hsv_mask(self.roi_image, params)
        mask_clean = clean_mask(mask_brut)

        # Analyse orientation
        result = analyse_orientation(
            mask_clean,
            tol_angle_deg    = self._tol_angle.get(),
            tol_decentrage_px= self._tol_decentrage.get(),
        )

        # Mise à jour labels
        angle  = result.get("angle_deg", 0.0)
        decal  = result.get("decentrage_px", 0.0)
        status = result.get("status", "NG")
        st_a   = result.get("status_angle", "NG")
        st_d   = result.get("status_decentrage", "NG")

        if self._lbl_angle:
            color_a = "green" if st_a == "OK" else "red"
            self._lbl_angle.config(
                text=f"Angle : {angle:+.1f}°  [{st_a}]",
                fg=color_a
            )
        if self._lbl_decal:
            color_d = "green" if st_d == "OK" else "red"
            self._lbl_decal.config(
                text=f"Décentrage : {decal:+.1f} px  [{st_d}]",
                fg=color_d
            )
        if self._lbl_verdict:
            self._lbl_verdict.config(
                text="✅ OK" if status == "OK" else "❌ NG",
                fg="green" if status == "OK" else "red"
            )

        # Indicateur rouge circulaire
        if self._rouge_label:
            self._rouge_label.config(
                text="⚠ ROUGE\nCIRC. ACTIF" if is_rouge_circulaire(params) else ""
            )

        # Visualisations
        mask_vis = cv2.cvtColor(mask_brut, cv2.COLOR_GRAY2BGR)
        mask_vis[mask_brut == 255] = [0, 0, 200]

        mask_clean_vis = cv2.cvtColor(mask_clean, cv2.COLOR_GRAY2BGR)
        mask_clean_vis[mask_clean == 255] = [0, 180, 0]

        orientation_vis = draw_orientation_result(
            self.roi_image, mask_clean, result
        )

        self._show_images_in_preview([
            ("Original",          self.roi_image),
            ("Masque HSV brut",   mask_vis),
            ("Masque nettoyé",    mask_clean_vis),
            ("Orientation",       orientation_vis),
        ])

    # ------------------------------------------------------------------
    def get_result(self) -> Optional[Dict[str, Any]]:
        if not self._validated:
            return None
        return {
            "hsv_params"             : {k: v.get() for k, v in self._p.items()},
            "tolerance_angle_deg"    : self._tol_angle.get(),
            "tolerance_decentrage_px": self._tol_decentrage.get(),
        }
