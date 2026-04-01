"""
popup_profil_canny.py
---------------------
Popup de calibration pour l'algorithme profil_canny.
Utilisé pour D1.4 (déformation corps), D4.2 (étiquette).
Affiche : Original | Canny | Profil couleur
Sliders : Canny low, Canny high
          Tolérance largeur min/max px
          Écart-type max px
          % lignes NG max
"""

from __future__ import annotations
from typing import Any, Dict, Optional
import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np

from ui.popups.popup_base import PopupBase
from shared.algorithms.canny_utils import (
    preprocess, measure_widths,
    draw_profil_color, auto_canny_params,
)


class PopupProfilCanny(PopupBase):

    def __init__(
        self,
        parent,
        roi_image     : np.ndarray,
        canny_low     : int   = 50,
        canny_high    : int   = 150,
        tol_min_pct   : float = 95.0,
        tol_max_pct   : float = 105.0,
        max_std_px    : float = 10.0,
        max_pct_ng    : float = 10.0,
    ):
        gray = cv2.cvtColor(roi_image, cv2.COLOR_BGR2GRAY) \
               if len(roi_image.shape) == 3 else roi_image.copy()
        self._gray = gray

        # Auto seuils Canny si defaults
        if canny_low == 50 and canny_high == 150:
            canny_low, canny_high = auto_canny_params(gray)

        self._canny_low  = tk.IntVar(value=canny_low)
        self._canny_high = tk.IntVar(value=canny_high)
        self._tol_min    = tk.DoubleVar(value=tol_min_pct)
        self._tol_max    = tk.DoubleVar(value=tol_max_pct)
        self._max_std    = tk.DoubleVar(value=max_std_px)
        self._max_pct_ng = tk.DoubleVar(value=max_pct_ng)

        self._mediane_ref : float = 0.0
        self._lbl_stats   : Optional[tk.Label] = None
        self._lbl_minmax  : Optional[tk.Label] = None

        super().__init__(parent, roi_image,
                         title="Calibration Profil — Canny Triple Critère",
                         width=980, height=680)

    # ------------------------------------------------------------------
    def build_controls(self, frame: ttk.LabelFrame):
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(4, weight=1)

        def refresh(_=None):
            # Empêche low > high
            if self._canny_low.get() >= self._canny_high.get():
                self._canny_high.set(self._canny_low.get() + 1)
            self.schedule_preview_update()

        # Colonne gauche : Canny
        self._add_slider(frame, "Canny low",
                         self._canny_low, 0, 254,
                         row=0, on_change=refresh, col_offset=0)
        self._add_slider(frame, "Canny high",
                         self._canny_high, 1, 255,
                         row=1, on_change=refresh, col_offset=0)

        ttk.Separator(frame, orient="horizontal").grid(
            row=2, column=0, columnspan=6, sticky="ew", pady=6)

        # Statistiques live
        self._lbl_stats = tk.Label(
            frame, text="Médiane : — px  |  σ : — px  |  % NG : —",
            font=("Arial", 9, "bold"), fg="#222266"
        )
        self._lbl_stats.grid(row=3, column=0, columnspan=6,
                              sticky="w", padx=6, pady=2)

        # Tolérances largeur
        self._add_slider(frame, "Tolérance largeur min (%)",
                         self._tol_min, 50, 100,
                         row=4, on_change=refresh, decimals=1)
        self._add_slider(frame, "Tolérance largeur max (%)",
                         self._tol_max, 100, 200,
                         row=5, on_change=refresh, decimals=1)

        # Écart-type max
        self._add_slider(frame, "Écart-type max (px)",
                         self._max_std, 0, 50,
                         row=6, on_change=refresh, decimals=1)

        # % lignes NG max
        self._add_slider(frame, "% lignes NG max",
                         self._max_pct_ng, 0, 50,
                         row=7, on_change=refresh, decimals=1)

        self._lbl_minmax = tk.Label(frame, text="",
                                    font=("Arial", 9, "italic"),
                                    fg="#555555")
        self._lbl_minmax.grid(row=8, column=0, columnspan=6,
                               sticky="w", padx=6, pady=2)

    # ------------------------------------------------------------------
    def update_preview(self):
        low  = self._canny_low.get()
        high = self._canny_high.get()

        _, edges   = preprocess(self._gray, low, high)
        widths, lp, rp = measure_widths(edges)

        # Statistiques
        if widths:
            mediane = float(np.median(widths))
            std     = float(np.std(widths))
            self._mediane_ref = mediane

            min_l = mediane * self._tol_min.get() / 100
            max_l = mediane * self._tol_max.get() / 100
            nb_ng = sum(1 for w in widths if not (min_l <= w <= max_l))
            pct   = round(100 * nb_ng / len(widths), 1) if widths else 0

            if self._lbl_stats:
                self._lbl_stats.config(
                    text=f"Médiane : {mediane:.1f} px  |  "
                         f"σ : {std:.1f} px  |  % NG : {pct}%"
                         f"  |  {len(widths)} lignes valides"
                )
            if self._lbl_minmax:
                self._lbl_minmax.config(
                    text=f"  → min_largeur = {min_l:.0f} px  "
                         f"|  max_largeur = {max_l:.0f} px"
                )
        else:
            self._mediane_ref = 0
            if self._lbl_stats:
                self._lbl_stats.config(text="⚠ Aucun contour détecté")

        # Visualisations
        edges_vis  = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        profil_vis = draw_profil_color(self._gray, lp, rp, widths)

        self._show_images_in_preview([
            ("Original",             self.roi_image),
            ("Contours Canny",       edges_vis),
            ("Profil largeurs",      profil_vis),
        ])

    # ------------------------------------------------------------------
    def get_result(self) -> Optional[Dict[str, Any]]:
        if not self._validated:
            return None
        med   = self._mediane_ref
        min_l = med * self._tol_min.get() / 100
        max_l = med * self._tol_max.get() / 100
        return {
            "canny_low"           : self._canny_low.get(),
            "canny_high"          : self._canny_high.get(),
            "largeur_reference_px": round(med, 2),
            "min_largeur_px"      : round(min_l, 2),
            "max_largeur_px"      : round(max_l, 2),
            "max_ecart_type_px"   : self._max_std.get(),
            "max_pct_lignes_ng"   : self._max_pct_ng.get(),
        }