"""
popup_check_position.py
-----------------------
Popup de calibration pour l'algorithme symmetry_canny (CP1.1).
Permet de configurer la vérification du positionnement de la bouteille.

Affiche : Original | Contours Canny | Axe de symétrie annoté

Sliders :
  Canny low, Canny high
  Tolérance écart axe/centre (pixels)

Affichage live :
  Axe de symétrie détecté
  Écart mesuré vs centre image
  Verdict OK/NG
"""

from __future__ import annotations
from typing import Any, Dict, Optional
import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np

from ui.popups.popup_base import PopupBase
from shared.algorithms.symmetry_utils import (
    detect_symmetry_axis, compute_ecart_centre,
    check_position_verdict, draw_position_result,
    auto_canny_params,
)


class PopupCheckPosition(PopupBase):

    def __init__(
        self,
        parent,
        roi_image     : np.ndarray,
        canny_low     : int   = 50,
        canny_high    : int   = 150,
        tolerance_px  : float = 15.0,
    ):
        gray = cv2.cvtColor(roi_image, cv2.COLOR_BGR2GRAY) \
               if len(roi_image.shape) == 3 else roi_image.copy()
        self._gray = gray

        # Auto-init Canny si valeurs par défaut
        if canny_low == 50 and canny_high == 150:
            canny_low, canny_high = auto_canny_params(gray)

        self._canny_low   = tk.IntVar(value=canny_low)
        self._canny_high  = tk.IntVar(value=canny_high)
        self._tolerance   = tk.DoubleVar(value=tolerance_px)

        self._lbl_ecart   : Optional[tk.Label] = None
        self._lbl_verdict : Optional[tk.Label] = None
        self._lbl_lignes  : Optional[tk.Label] = None

        super().__init__(parent, roi_image,
                         title="Calibration Check Position — Axe de symétrie (CP1.1)",
                         width=900, height=620)

    # ------------------------------------------------------------------
    def build_controls(self, frame: ttk.LabelFrame):
        frame.columnconfigure(1, weight=1)

        def refresh(_=None):
            if self._canny_low.get() >= self._canny_high.get():
                self._canny_high.set(self._canny_low.get() + 1)
            self.schedule_preview_update()

        self._add_slider(frame, "Canny low",
                         self._canny_low, 0, 254,
                         row=0, on_change=refresh)
        self._add_slider(frame, "Canny high",
                         self._canny_high, 1, 255,
                         row=1, on_change=refresh)

        ttk.Separator(frame, orient="horizontal").grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=6
        )

        # Résultats live
        res_frame = tk.Frame(frame, bg="#f4f4f4", relief="groove", bd=1)
        res_frame.grid(row=3, column=0, columnspan=4,
                       sticky="ew", padx=6, pady=4)

        self._lbl_ecart = tk.Label(res_frame,
                                   text="Écart axe/centre : — px",
                                   font=("Arial", 10, "bold"),
                                   bg="#f4f4f4")
        self._lbl_ecart.pack(side="left", padx=12, pady=4)

        self._lbl_lignes = tk.Label(res_frame,
                                    text="",
                                    font=("Arial", 9, "italic"),
                                    fg="#555555", bg="#f4f4f4")
        self._lbl_lignes.pack(side="left", padx=8)

        self._lbl_verdict = tk.Label(res_frame,
                                     text="—",
                                     font=("Arial", 11, "bold"),
                                     bg="#f4f4f4")
        self._lbl_verdict.pack(side="right", padx=12)

        ttk.Separator(frame, orient="horizontal").grid(
            row=4, column=0, columnspan=4, sticky="ew", pady=4
        )

        self._add_slider(frame, "Tolérance écart (px)",
                         self._tolerance, 1, 100,
                         row=5, on_change=refresh, decimals=1)

        tk.Label(frame,
                 text="ℹ  L'axe de symétrie est calculé comme la médiane des centres gauche/droite\n"
                      "   détectés par Canny ligne par ligne. Écart = axe − centre image.",
                 font=("Arial", 8, "italic"), fg="#555555",
                 wraplength=500, justify="left"
                 ).grid(row=6, column=0, columnspan=4,
                        sticky="w", padx=6, pady=4)

    # ------------------------------------------------------------------
    def update_preview(self):
        low  = self._canny_low.get()
        high = self._canny_high.get()
        tol  = self._tolerance.get()

        axe_x, edges, vis_axe, centres = detect_symmetry_axis(
            self._gray, low, high
        )

        _, w = self._gray.shape
        ecart_px = compute_ecart_centre(axe_x, w)
        result   = check_position_verdict(ecart_px, tol)
        status   = result["status"]

        # Mise à jour labels
        color = "green" if status == "OK" else "red"
        if self._lbl_ecart:
            self._lbl_ecart.config(
                text=f"Écart axe/centre : {ecart_px:+.1f} px",
                fg=color
            )
        if self._lbl_lignes:
            self._lbl_lignes.config(
                text=f"{len(centres)} lignes valides"
            )
        if self._lbl_verdict:
            self._lbl_verdict.config(
                text="✅ OK" if status == "OK" else "❌ NG",
                fg=color
            )

        # Visualisation résultat annoté
        result_vis = draw_position_result(
            self._gray, axe_x, ecart_px, tol, status
        )

        self._show_images_in_preview([
            ("Original",            self.roi_image),
            ("Contours Canny",      cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)),
            ("Axe de symétrie",     vis_axe),
            ("Résultat",            result_vis),
        ])

    # ------------------------------------------------------------------
    def get_result(self) -> Optional[Dict[str, Any]]:
        if not self._validated:
            return None
        return {
            "canny_low"         : self._canny_low.get(),
            "canny_high"        : self._canny_high.get(),
            "tolerance_ecart_px": self._tolerance.get(),
        }
