"""
popup_niveau_sobel.py
---------------------
Popup de calibration pour l'algorithme niveau_sobel.

Affiche : ROI avec ligne de surface (verte) + contours Canny + ancre (orange)

Sliders :
  y_surface       : position locale de la surface dans le ROI
  Canny low/high  : pour la détection des bords bouteille
  Tolérance ratio : min%, max% autour du ratio de référence

Affichage live :
  distance_px     : ancre → surface (trace uniquement)
  largeur_px      : largeur bouteille au niveau (trace uniquement)
  ratio_ref       : distance / largeur → valeur calibrée = verdict
"""

from __future__ import annotations
from typing import Any, Dict, Optional
import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np

from ui.popups.popup_base import PopupBase
from shared.algorithms.sobel_utils import make_clahe, auto_detect_surface


def _auto_canny(gray: np.ndarray):
    """Calcule seuils Canny via méthode médiane."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    median  = float(np.median(blurred))
    sigma   = 0.33
    return int(max(0, (1.0 - sigma) * median)), \
           int(min(255, (1.0 + sigma) * median))


def _mesure_largeur_au_niveau(
    roi_gray   : np.ndarray,
    y_surface  : float,
    canny_low  : int = 50,
    canny_high : int = 150,
    marge_py   : int = 3,
) -> float:
    """Mesure la largeur de la bouteille à y_surface via Canny."""
    h, w    = roi_gray.shape
    blurred = cv2.GaussianBlur(roi_gray, (5, 5), 0)
    edges   = cv2.Canny(blurred, canny_low, canny_high)
    y_int   = int(round(y_surface))
    y_start = max(0, y_int - marge_py)
    y_end   = min(h, y_int + marge_py + 1)
    largeurs = []
    for row_idx in range(y_start, y_end):
        row     = edges[row_idx, :]
        nonzero = np.where(row > 0)[0]
        if len(nonzero) >= 2:
            largeurs.append(float(nonzero[-1] - nonzero[0]))
    return round(float(np.median(largeurs)), 2) if largeurs else 0.0


class PopupNiveauSobel(PopupBase):

    def __init__(
        self,
        parent,
        roi_image     : np.ndarray,
        roi_y_global  : int,
        anchor_cy     : float,
        y_surface_init: Optional[int]  = None,
        canny_low     : int            = 50,
        canny_high    : int            = 150,
        tol_moins_pct : float          = 5.0,
        tol_plus_pct  : float          = 5.0,
    ):
        self._clahe        = make_clahe()
        self._roi_y_global = roi_y_global
        self._anchor_cy    = anchor_cy

        gray = cv2.cvtColor(roi_image, cv2.COLOR_BGR2GRAY) \
               if len(roi_image.shape) == 3 else roi_image.copy()
        self._gray = gray
        h, _       = gray.shape

        y_init = y_surface_init if y_surface_init is not None \
                 else auto_detect_surface(gray, self._clahe)

        # Auto-init Canny si valeurs par défaut
        if canny_low == 50 and canny_high == 150:
            canny_low, canny_high = _auto_canny(gray)

        self._y_surface  = tk.IntVar(value=y_init)
        self._canny_low  = tk.IntVar(value=canny_low)
        self._canny_high = tk.IntVar(value=canny_high)
        self._tol_moins  = tk.DoubleVar(value=tol_moins_pct)
        self._tol_plus   = tk.DoubleVar(value=tol_plus_pct)
        self._h          = h

        # Valeurs live calculées
        self._ratio_ref  : float = 0.0

        self._lbl_dist   : Optional[tk.Label] = None
        self._lbl_larg   : Optional[tk.Label] = None
        self._lbl_ratio  : Optional[tk.Label] = None
        self._lbl_tol    : Optional[tk.Label] = None

        super().__init__(parent, roi_image,
                         title="Calibration Niveau — Ratio Distance/Largeur",
                         width=820, height=660)

    # ------------------------------------------------------------------
    def build_controls(self, frame: ttk.LabelFrame):
        frame.columnconfigure(1, weight=1)

        def refresh(_=None):
            if self._canny_low.get() >= self._canny_high.get():
                self._canny_high.set(self._canny_low.get() + 1)
            self.schedule_preview_update()

        # Info ancre
        tk.Label(frame,
                 text=f"Centre ancre (y global) : {self._anchor_cy:.1f} px",
                 font=("Arial", 9, "italic"), fg="#555555"
                 ).grid(row=0, column=0, columnspan=3,
                        sticky="w", padx=6, pady=(4, 0))

        self._add_slider(frame, "Surface liquide (y local)",
                         self._y_surface, 0, self._h - 1,
                         row=1, on_change=refresh)

        ttk.Separator(frame, orient="horizontal").grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=4)

        # Canny pour mesure largeur
        tk.Label(frame, text="── Contours bouteille (Canny) ──",
                 font=("Arial", 9, "bold"), fg="#2c3e50"
                 ).grid(row=3, column=0, columnspan=3,
                        sticky="w", padx=6, pady=(2, 0))

        self._add_slider(frame, "Canny low",
                         self._canny_low, 0, 254,
                         row=4, on_change=refresh)
        self._add_slider(frame, "Canny high",
                         self._canny_high, 1, 255,
                         row=5, on_change=refresh)

        ttk.Separator(frame, orient="horizontal").grid(
            row=6, column=0, columnspan=4, sticky="ew", pady=4)

        # Résultats live
        res_frame = tk.Frame(frame, bg="#f4f4f4", relief="groove", bd=1)
        res_frame.grid(row=7, column=0, columnspan=4,
                       sticky="ew", padx=6, pady=4)

        self._lbl_dist = tk.Label(res_frame,
                                  text="Distance : — px",
                                  font=("Arial", 9), bg="#f4f4f4",
                                  fg="#555555")
        self._lbl_dist.pack(side="left", padx=10, pady=4)

        self._lbl_larg = tk.Label(res_frame,
                                  text="Largeur : — px",
                                  font=("Arial", 9), bg="#f4f4f4",
                                  fg="#555555")
        self._lbl_larg.pack(side="left", padx=10)

        self._lbl_ratio = tk.Label(res_frame,
                                   text="Ratio : —",
                                   font=("Arial", 11, "bold"),
                                   bg="#f4f4f4", fg="#1a5c2a")
        self._lbl_ratio.pack(side="right", padx=14)

        ttk.Separator(frame, orient="horizontal").grid(
            row=8, column=0, columnspan=4, sticky="ew", pady=4)

        # Tolérances ratio
        tk.Label(frame, text="── Tolérance ratio ──",
                 font=("Arial", 9, "bold"), fg="#2c3e50"
                 ).grid(row=9, column=0, columnspan=3,
                        sticky="w", padx=6, pady=(2, 0))

        self._add_slider(frame, "Tolérance − (%)",
                         self._tol_moins, 0, 30,
                         row=10, on_change=refresh, decimals=1)
        self._add_slider(frame, "Tolérance + (%)",
                         self._tol_plus, 0, 30,
                         row=11, on_change=refresh, decimals=1)

        self._lbl_tol = tk.Label(frame, text="",
                                 font=("Arial", 9, "italic"),
                                 fg="#555555")
        self._lbl_tol.grid(row=12, column=0, columnspan=4,
                            sticky="w", padx=6, pady=2)

        tk.Label(frame,
                 text="ℹ  Le ratio distance/largeur est indépendant du scale caméra.\n"
                      "   Un même niveau de remplissage donne le même ratio quelle que\n"
                      "   soit la distance bouteille/caméra.",
                 font=("Arial", 8, "italic"), fg="#555555",
                 justify="left", wraplength=500,
                 ).grid(row=13, column=0, columnspan=4,
                        sticky="w", padx=6, pady=4)

    # ------------------------------------------------------------------
    def update_preview(self):
        y_l       = self._y_surface.get()
        y_global  = self._roi_y_global + y_l
        distance  = y_global - self._anchor_cy

        canny_low  = self._canny_low.get()
        canny_high = self._canny_high.get()

        largeur = _mesure_largeur_au_niveau(
            self._gray, float(y_l), canny_low, canny_high
        )

        # Calcul ratio
        if largeur > 0:
            ratio = round(distance / largeur, 4)
        else:
            ratio = None
        self._ratio_ref = ratio if ratio is not None else 0.0

        # Mise à jour labels
        if self._lbl_dist:
            self._lbl_dist.config(
                text=f"Distance : {distance:.1f} px"
            )
        if self._lbl_larg:
            color_l = "green" if largeur > 0 else "red"
            self._lbl_larg.config(
                text=f"Largeur : {largeur:.1f} px",
                fg=color_l
            )
        if self._lbl_ratio:
            if ratio is not None:
                self._lbl_ratio.config(
                    text=f"Ratio ref = {ratio:.4f}",
                    fg="#1a5c2a"
                )
            else:
                self._lbl_ratio.config(
                    text="Ratio : N/A (contours non détectés)",
                    fg="red"
                )

        if self._lbl_tol and ratio is not None:
            r_min = round(ratio * (1 - self._tol_moins.get() / 100), 4)
            r_max = round(ratio * (1 + self._tol_plus.get()  / 100), 4)
            self._lbl_tol.config(
                text=f"  → tolerance_ratio_min = {r_min}  |  "
                     f"tolerance_ratio_max = {r_max}"
            )

        # Visualisation
        vis     = cv2.cvtColor(self._gray, cv2.COLOR_GRAY2BGR)
        w_img   = vis.shape[1]

        # Contours Canny
        blurred = cv2.GaussianBlur(self._gray, (5, 5), 0)
        edges   = cv2.Canny(blurred, canny_low, canny_high)
        edges_bgr = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

        # Ligne surface (verte)
        cv2.line(vis, (0, y_l), (w_img, y_l), (0, 220, 0), 2)

        # Segment largeur au niveau (cyan)
        row_edges = edges[y_l, :]
        nonzero   = np.where(row_edges > 0)[0]
        if len(nonzero) >= 2:
            x_left  = int(nonzero[0])
            x_right = int(nonzero[-1])
            cv2.line(vis, (x_left, y_l), (x_right, y_l), (255, 220, 0), 3)
            cv2.circle(vis, (x_left,  y_l), 4, (255, 220, 0), -1)
            cv2.circle(vis, (x_right, y_l), 4, (255, 220, 0), -1)

        # Ancre (orange)
        anchor_y_in_roi = int(self._anchor_cy - self._roi_y_global)
        if 0 <= anchor_y_in_roi < self._h:
            for x in range(0, w_img, 8):
                cv2.line(vis, (x, anchor_y_in_roi),
                         (min(x + 4, w_img), anchor_y_in_roi),
                         (0, 165, 255), 1)
            cv2.putText(vis, "ancre",
                        (5, max(12, anchor_y_in_roi - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 165, 255), 1)

        # Ratio annoté
        ratio_str = f"ratio={ratio:.4f}" if ratio is not None else "ratio=N/A"
        cv2.putText(vis, ratio_str,
                    (5, max(16, y_l - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 0), 1)

        self._show_images_in_preview([
            ("ROI — Surface + Largeur", vis),
            ("Contours Canny",          edges_bgr),
        ])

    # ------------------------------------------------------------------
    def get_result(self) -> Optional[Dict[str, Any]]:
        if not self._validated:
            return None

        y_l    = self._y_surface.get()
        y_glob = self._roi_y_global + y_l
        ratio  = self._ratio_ref

        if ratio <= 0:
            return None   # Pas de ratio valide → refuser la validation

        r_min = round(ratio * (1 - self._tol_moins.get() / 100), 4)
        r_max = round(ratio * (1 + self._tol_plus.get()  / 100), 4)

        return {
            "y_ligne_local_ref"  : y_l,
            "y_ligne_global_ref" : y_glob,
            "distance_ref_px"    : round(y_glob - self._anchor_cy, 2),
            "ratio_ref"          : ratio,
            "tolerance_ratio_min": r_min,
            "tolerance_ratio_max": r_max,
            "canny_low"          : self._canny_low.get(),
            "canny_high"         : self._canny_high.get(),
            "detection_method"   : "sobel_ratio",
        }