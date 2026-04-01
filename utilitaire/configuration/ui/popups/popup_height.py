"""
popup_height.py
---------------
Popup de calibration pour l'algorithme height.
Affiche : ROI avec lignes annotées (sommet rouge, référence bleue)
Sliders : y_top (sommet), y_ref (référence col)
          Tolérance min%, Tolérance max%
"""

from __future__ import annotations
from typing import Any, Dict, Optional
import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np

from ui.popups.popup_base import PopupBase
from shared.algorithms.height_utils import detect_top, draw_height_result


class PopupHeight(PopupBase):

    def __init__(
        self,
        parent,
        roi_image    : np.ndarray,
        y_top_init   : Optional[int]   = None,
        y_ref_init   : Optional[int]   = None,
        tol_min_pct  : float           = 90.0,
        tol_max_pct  : float           = 110.0,
    ):
        gray = cv2.cvtColor(roi_image, cv2.COLOR_BGR2GRAY) \
               if len(roi_image.shape) == 3 else roi_image.copy()
        self._gray  = gray
        h, _        = gray.shape

        # Valeurs initiales auto si non fournies
        y_ref  = y_ref_init  if y_ref_init  is not None else int(h * 0.85)
        y_top  = y_top_init  if y_top_init  is not None else detect_top(gray, y_ref)

        self._y_top = tk.IntVar(value=y_top)
        self._y_ref = tk.IntVar(value=y_ref)
        self._tol_min = tk.DoubleVar(value=tol_min_pct)
        self._tol_max = tk.DoubleVar(value=tol_max_pct)
        self._h       = h

        self._lbl_height  : Optional[tk.Label] = None
        self._lbl_minmax  : Optional[tk.Label] = None

        super().__init__(parent, roi_image,
                         title="Calibration Height — Sommet",
                         width=700, height=580)

    # ------------------------------------------------------------------
    def build_controls(self, frame: ttk.LabelFrame):
        frame.columnconfigure(1, weight=1)

        def refresh(_=None):
            # Empêche y_top > y_ref
            if self._y_top.get() >= self._y_ref.get():
                self._y_top.set(self._y_ref.get() - 1)
            self.update_preview()

        self._add_slider(frame, "Sommet bouchon (y_top)",
                         self._y_top, 0, self._h - 2,
                         row=0, on_change=refresh)

        self._add_slider(frame, "Référence col (y_ref)",
                         self._y_ref, 1, self._h - 1,
                         row=1, on_change=refresh)

        ttk.Separator(frame, orient="horizontal").grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=6)

        self._lbl_height = tk.Label(frame, text="Hauteur : — px",
                                    font=("Arial", 10, "bold"))
        self._lbl_height.grid(row=3, column=0, columnspan=2,
                               sticky="w", padx=6)

        self._add_slider(frame, "Tolérance min (%)",
                         self._tol_min, 50, 100,
                         row=4, on_change=refresh, decimals=1)
        self._add_slider(frame, "Tolérance max (%)",
                         self._tol_max, 100, 200,
                         row=5, on_change=refresh, decimals=1)

        self._lbl_minmax = tk.Label(frame, text="",
                                    font=("Arial", 9, "italic"),
                                    fg="#555555")
        self._lbl_minmax.grid(row=6, column=0, columnspan=4,
                               sticky="w", padx=6, pady=2)

    # ------------------------------------------------------------------
    def update_preview(self):
        y_top = self._y_top.get()
        y_ref = self._y_ref.get()
        h_px  = max(0, y_ref - y_top)

        if self._lbl_height:
            self._lbl_height.config(text=f"Hauteur : {h_px} px")

        min_h = int(h_px * self._tol_min.get() / 100)
        max_h = int(h_px * self._tol_max.get() / 100)
        if self._lbl_minmax:
            self._lbl_minmax.config(
                text=f"  → min_height = {min_h} px  |  max_height = {max_h} px"
            )

        vis = draw_height_result(self._gray, y_top, y_ref, "OK")

        self._show_images_in_preview([
            ("ROI — Mesure de hauteur", vis),
        ])

    # ------------------------------------------------------------------
    def get_result(self) -> Optional[Dict[str, Any]]:
        if not self._validated:
            return None
        y_top = self._y_top.get()
        y_ref = self._y_ref.get()
        h_px  = max(0, y_ref - y_top)
        min_h = int(h_px * self._tol_min.get() / 100)
        max_h = int(h_px * self._tol_max.get() / 100)
        return {
            "y_top_relative" : y_top,
            "y_ref_relative" : y_ref,
            "expected_height": h_px,
            "min_height"     : min_h,
            "max_height"     : max_h,
            "detection_method": "profile",
        }
