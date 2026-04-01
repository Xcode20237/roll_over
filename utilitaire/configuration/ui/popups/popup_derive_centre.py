"""
popup_derive_centre.py
----------------------
Popup de calibration pour l'algorithme derive_centre (D1.5 col tordu).
Affiche : Original | Canny | Centre x_c(y) tracé
Sliders : Canny low, Canny high
          Dérive max Δx_c (px)
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
    compute_derive_centre, auto_canny_params
)


class PopupDeriveCentre(PopupBase):

    def __init__(
        self,
        parent,
        roi_image   : np.ndarray,
        canny_low   : int   = 50,
        canny_high  : int   = 150,
        derive_max  : float = 5.0,
    ):
        gray = cv2.cvtColor(roi_image, cv2.COLOR_BGR2GRAY) \
               if len(roi_image.shape) == 3 else roi_image.copy()
        self._gray = gray

        if canny_low == 50 and canny_high == 150:
            canny_low, canny_high = auto_canny_params(gray)

        self._canny_low  = tk.IntVar(value=canny_low)
        self._canny_high = tk.IntVar(value=canny_high)
        self._derive_max = tk.DoubleVar(value=derive_max)

        self._lbl_derive : Optional[tk.Label] = None

        super().__init__(parent, roi_image,
                         title="Calibration Col — Dérive du Centre",
                         width=820, height=580)

    # ------------------------------------------------------------------
    def build_controls(self, frame: ttk.LabelFrame):
        frame.columnconfigure(1, weight=1)

        def refresh(_=None):
            if self._canny_low.get() >= self._canny_high.get():
                self._canny_high.set(self._canny_low.get() + 1)
            self.update_preview()

        self._add_slider(frame, "Canny low",
                         self._canny_low, 0, 254,
                         row=0, on_change=refresh)
        self._add_slider(frame, "Canny high",
                         self._canny_high, 1, 255,
                         row=1, on_change=refresh)

        ttk.Separator(frame, orient="horizontal").grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=6)

        self._lbl_derive = tk.Label(
            frame, text="Dérive Δx_c : — px",
            font=("Arial", 10, "bold")
        )
        self._lbl_derive.grid(row=3, column=0, columnspan=2,
                               sticky="w", padx=6)

        self._add_slider(frame, "Dérive max Δx_c (px)",
                         self._derive_max, 0, 50,
                         row=4, on_change=refresh, decimals=1)

        tk.Label(frame,
                 text="Un col droit donne Δx_c ≈ 0. "
                      "Régler le seuil au-dessus du bruit de la bouteille OK.",
                 font=("Arial", 8, "italic"), fg="#555555",
                 wraplength=400, justify="left"
                 ).grid(row=5, column=0, columnspan=4,
                        sticky="w", padx=6, pady=4)

    # ------------------------------------------------------------------
    def update_preview(self):
        low  = self._canny_low.get()
        high = self._canny_high.get()

        _, edges    = preprocess(self._gray, low, high)
        widths, lp, rp = measure_widths(edges)

        derive_px, centres = compute_derive_centre(lp, rp)

        if self._lbl_derive:
            self._lbl_derive.config(
                text=f"Dérive Δx_c : {derive_px:.1f} px  "
                     f"({'OK' if derive_px <= self._derive_max.get() else 'NG'})"
            )

        # Visualisation
        vis = cv2.cvtColor(self._gray, cv2.COLOR_GRAY2BGR)

        # Contours
        edges_bgr = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

        # Tracé du centre x_c(y)
        centre_vis = cv2.cvtColor(self._gray, cv2.COLOR_GRAY2BGR)
        for i, (lpt, rpt) in enumerate(zip(lp, rp)):
            cv2.circle(centre_vis, lpt, 1, (255, 100, 0), -1)
            cv2.circle(centre_vis, rpt, 1, (0, 100, 255), -1)

        for i, c in enumerate(centres):
            row = lp[i][1] if i < len(lp) else i
            cv2.circle(centre_vis, (int(c), row), 1, (0, 255, 0), -1)

        # Ligne de dérive
        if len(centres) >= 2:
            cv2.line(centre_vis,
                     (int(centres[0]),  lp[0][1]),
                     (int(centres[-1]), lp[-1][1]),
                     (0, 255, 255), 2)

        self._show_images_in_preview([
            ("Original",         self.roi_image),
            ("Contours Canny",   edges_bgr),
            ("Centre x_c(y)",    centre_vis),
        ])

    # ------------------------------------------------------------------
    def get_result(self) -> Optional[Dict[str, Any]]:
        if not self._validated:
            return None
        return {
            "canny_low"   : self._canny_low.get(),
            "canny_high"  : self._canny_high.get(),
            "derive_max_px": self._derive_max.get(),
        }
