"""
popup_presence_seuil.py
-----------------------
Popup de calibration pour l'algorithme presence_seuillage.
Utilisé pour D2.4 (mousse), D4.1 (fuites), D4.4 (marquage).
Affiche : Original | Masque binaire
Slider  : Seuil (0-255), option inversion
          Tolérance min%, Tolérance max%
"""

from __future__ import annotations
from typing import Any, Dict, Optional
import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np

from ui.popups.popup_base import PopupBase


class PopupPresenceSeuil(PopupBase):

    def __init__(
        self,
        parent,
        roi_image  : np.ndarray,
        threshold  : int   = 128,
        invert     : bool  = False,
        tol_min_pct: float = 80.0,
        tol_max_pct: float = 120.0,
    ):
        gray = cv2.cvtColor(roi_image, cv2.COLOR_BGR2GRAY) \
               if len(roi_image.shape) == 3 else roi_image.copy()
        self._gray = gray

        # Seuil initial par Otsu
        otsu, _ = cv2.threshold(gray, 0, 255,
                                 cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        init_thresh = threshold if threshold != 128 else int(otsu)

        self._threshold = tk.IntVar(value=init_thresh)
        self._invert    = tk.BooleanVar(value=invert)
        self._tol_min   = tk.DoubleVar(value=tol_min_pct)
        self._tol_max   = tk.DoubleVar(value=tol_max_pct)

        self._area_ref   : int   = 0
        self._lbl_area   : Optional[tk.Label] = None
        self._lbl_minmax : Optional[tk.Label] = None

        super().__init__(parent, roi_image,
                         title="Calibration Présence — Seuillage",
                         width=720, height=560)

    # ------------------------------------------------------------------
    def build_controls(self, frame: ttk.LabelFrame):
        frame.columnconfigure(1, weight=1)

        def refresh(_=None):
            self.update_preview()

        self._add_slider(frame, "Seuil (0-255)",
                         self._threshold, 0, 255,
                         row=0, on_change=refresh)

        tk.Checkbutton(frame, text="Inverser le masque",
                       variable=self._invert,
                       command=refresh,
                       font=("Arial", 9)
                       ).grid(row=1, column=0, columnspan=2,
                              sticky="w", padx=6, pady=2)

        ttk.Separator(frame, orient="horizontal").grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=6)

        self._lbl_area = tk.Label(frame, text="Aire référence : — px",
                                  font=("Arial", 10, "bold"))
        self._lbl_area.grid(row=3, column=0, columnspan=2,
                             sticky="w", padx=6)

        self._add_slider(frame, "Tolérance min (%)",
                         self._tol_min, 10, 100,
                         row=4, on_change=refresh, decimals=1)
        self._add_slider(frame, "Tolérance max (%)",
                         self._tol_max, 100, 300,
                         row=5, on_change=refresh, decimals=1)

        self._lbl_minmax = tk.Label(frame, text="",
                                    font=("Arial", 9, "italic"),
                                    fg="#555555")
        self._lbl_minmax.grid(row=6, column=0, columnspan=4,
                               sticky="w", padx=6, pady=2)

    # ------------------------------------------------------------------
    def update_preview(self):
        thresh = self._threshold.get()
        _, binary = cv2.threshold(self._gray, thresh, 255, cv2.THRESH_BINARY)
        if self._invert.get():
            binary = cv2.bitwise_not(binary)

        area = int(cv2.countNonZero(binary))
        self._area_ref = area

        if self._lbl_area:
            self._lbl_area.config(text=f"Aire référence : {area} px")

        min_a = int(area * self._tol_min.get() / 100)
        max_a = int(area * self._tol_max.get() / 100)
        if self._lbl_minmax:
            self._lbl_minmax.config(
                text=f"  → min_area = {min_a} px  |  max_area = {max_a} px"
            )

        # Visualisation masque en couleur (vert)
        vis_mask = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        vis_mask[binary == 255] = [0, 180, 0]

        self._show_images_in_preview([
            ("Original",        self.roi_image),
            ("Masque binaire",  vis_mask),
        ])

    # ------------------------------------------------------------------
    def get_result(self) -> Optional[Dict[str, Any]]:
        if not self._validated:
            return None
        area = self._area_ref
        return {
            "threshold"    : self._threshold.get(),
            "invert"       : self._invert.get(),
            "expected_area": area,
            "min_area"     : int(area * self._tol_min.get() / 100),
            "max_area"     : int(area * self._tol_max.get() / 100),
        }
