"""
dashboard.py
------------
Dashboard d'inspection — affiche le résultat complet d'une inspection.

Structure :
  ┌─────────────────────────────────────┐
  │  Onglet "Vue Globale"               │
  │  Onglet par ROI (étapes intermé.)   │
  └─────────────────────────────────────┘
"""

from __future__ import annotations
from typing import Dict, List, Optional
import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np
from PIL import Image, ImageTk

from shared.engines.engine_base import InspectionReport, ROIResult


class Dashboard(tk.Toplevel):
    """
    Fenêtre d'affichage des résultats d'inspection.
    S'ouvre en non-modal — l'opérateur peut tester une autre image
    pendant que le dashboard est visible.
    """

    def __init__(self, parent, report: InspectionReport):
        super().__init__(parent)
        self.title(
            f"Dashboard — {report.label}  [{report.id_defaut}]  "
            f"→  {'✅ OK' if report.is_ok else '❌ NG'}"
        )
        self.geometry("1280x820")
        self.resizable(True, True)

        self._report   = report
        self._tk_imgs  : list = []

        bg_color = "#eaffea" if report.is_ok else "#ffeeee"
        self.configure(bg=bg_color)

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        # ---- Bandeau statut ----
        color   = "#1a7a1a" if self._report.is_ok else "#aa1111"
        bg_band = "#c8f5c8" if self._report.is_ok else "#f5c8c8"

        band = tk.Frame(self, bg=bg_band, height=50)
        band.pack(fill="x")
        band.pack_propagate(False)

        status_txt = "✅  OK" if self._report.is_ok else "❌  NG"
        tk.Label(band,
                 text=f"{status_txt}   —   {self._report.label}  "
                      f"({self._report.id_defaut})   |   "
                      f"Algo : {self._report.algorithme}",
                 font=("Arial", 14, "bold"),
                 fg=color, bg=bg_band,
                 ).pack(side="left", padx=20, pady=10)

        # Infos recalage
        if self._report.match_info:
            mi = self._report.match_info
            info = (f"Recalage [{mi.get('method','?')}]  "
                    f"score={mi.get('score',0):.2f}  "
                    f"dx={mi.get('dx',0):+.1f}  "
                    f"dy={mi.get('dy',0):+.1f}")
            tk.Label(band, text=info,
                     font=("Arial", 9, "italic"),
                     fg="#555555", bg=bg_band,
                     ).pack(side="right", padx=20)

        # ---- Notebook ----
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        # Onglet Vue Globale
        tab_global = ttk.Frame(nb)
        nb.add(tab_global, text="🖼  Vue Globale")
        self._build_global_tab(tab_global)

        # Un onglet par ROI
        for roi_res in self._report.roi_results:
            sym = "✅" if roi_res.status == "OK" else "❌"
            tab = ttk.Frame(nb)
            nb.add(tab, text=f"{sym}  {roi_res.roi_name}")
            self._build_roi_tab(tab, roi_res)

    # ------------------------------------------------------------------
    # Vue Globale
    # ------------------------------------------------------------------

    def _build_global_tab(self, parent: ttk.Frame):
        img = self._report.image_originale.copy()

        # Ancre de recalage
        mi = self._report.match_info
        if mi and mi.get("method") != "NONE" and mi.get("loc"):
            mx, my = mi["loc"]
            aw = int(mi.get("scale", 1.0) * 30)
            ah = int(mi.get("scale", 1.0) * 15)
            cv2.rectangle(img, (mx, my), (mx+aw, my+ah), (0, 220, 220), 2)
            cv2.putText(img,
                        f"ANCRE [{mi['method']}] {mi['score']:.2f}",
                        (mx, max(15, my-4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 220), 1)

        # ROIs
        for roi_res in self._report.roi_results:
            x, y, w, h = roi_res.roi_rect
            color = (0, 200, 0) if roi_res.status == "OK" else (0, 0, 200)
            cv2.rectangle(img, (x, y), (x+w, y+h), color, 2)
            label = f"{roi_res.roi_name}: {roi_res.status}"
            cv2.putText(img, label,
                        (x, max(14, y-4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 1)

        # Verdict global
        g_color = (0, 180, 0) if self._report.is_ok else (0, 0, 200)
        cv2.putText(img,
                    f"STATUT: {self._report.status_global}",
                    (15, 45),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, g_color, 3)

        self._show_img(parent, img, max_size=(1200, 720))

    # ------------------------------------------------------------------
    # Onglet ROI
    # ------------------------------------------------------------------

    def _build_roi_tab(self, parent: ttk.Frame, roi_res: ROIResult):
        # Panneau stats
        info = tk.Frame(parent, bg="#f4f4f4", bd=1, relief="groove")
        info.pack(fill="x", padx=8, pady=6)

        color = "green" if roi_res.status == "OK" else "red"
        tk.Label(info,
                 text=f"Statut : {roi_res.status}",
                 fg=color, font=("Arial", 15, "bold"),
                 bg="#f4f4f4").pack(side="left", padx=16)

        stats = (f"Mesuré : {roi_res.mesure:.2f}   |   "
                 f"Référence : {roi_res.reference:.2f}   |   "
                 f"Tolérance : [{roi_res.tolerance[0]:.2f}  →  {roi_res.tolerance[1]:.2f}]   |   "
                 f"Écart : {roi_res.ecart:+.2f}")
        tk.Label(info, text=stats,
                 font=("Arial", 10, "bold"),
                 bg="#f4f4f4").pack(side="left", padx=12)

        # Détails
        detail_items = [
            f"{k}: {v}" for k, v in roi_res.details.items()
            if isinstance(v, (int, float, str, bool))
        ]
        if detail_items:
            tk.Label(info,
                     text="  |  ".join(detail_items),
                     font=("Arial", 9, "italic"),
                     fg="#555555", bg="#f4f4f4"
                     ).pack(side="left", padx=8)

        # Grille d'images intermédiaires
        imgs_frame = tk.Frame(parent)
        imgs_frame.pack(fill="both", expand=True, padx=8, pady=4)

        COLS = 3
        for idx, (step_name, step_img) in enumerate(roi_res.steps.items()):
            row_idx = idx // COLS
            col_idx = idx % COLS

            cell = tk.Frame(imgs_frame, bd=1, relief="ridge")
            cell.grid(row=row_idx, column=col_idx,
                      padx=6, pady=6, sticky="nsew")

            tk.Label(cell, text=step_name,
                     font=("Arial", 10, "bold")).pack(pady=3)

            self._show_img(cell, step_img, max_size=(370, 300))

        for c in range(COLS):
            imgs_frame.columnconfigure(c, weight=1)

    # ------------------------------------------------------------------
    # Utilitaire affichage
    # ------------------------------------------------------------------

    def _show_img(self, parent, img_cv2: np.ndarray,
                  max_size=(400, 400)):
        h, w = img_cv2.shape[:2]
        scale = min(max_size[0]/w, max_size[1]/h)
        if scale != 1.0:
            nw, nh = int(w*scale), int(h*scale)
            interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
            img_cv2 = cv2.resize(img_cv2, (nw, nh), interpolation=interp)

        if len(img_cv2.shape) == 2:
            img_rgb = cv2.cvtColor(img_cv2, cv2.COLOR_GRAY2RGB)
        else:
            img_rgb = cv2.cvtColor(img_cv2, cv2.COLOR_BGR2RGB)

        tk_img = ImageTk.PhotoImage(Image.fromarray(img_rgb))
        self._tk_imgs.append(tk_img)
        lbl = tk.Label(parent, image=tk_img)
        lbl.image = tk_img
        lbl.pack(expand=True)
