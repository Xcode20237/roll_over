"""
popup_base.py
-------------
Classe de base commune à toutes les popups de calibration.

Chaque popup spécialisée hérite de PopupBase et implémente :
  - build_controls(frame)  → construit les widgets de paramètres
  - update_preview()       → recalcule et affiche l'aperçu
  - get_result()           → retourne les paramètres validés

Anti-flash : debounce 80ms sur les sliders + mise à jour des images
en place (remplacement de l'image dans le Label existant, sans
détruire/recréer les widgets à chaque frame).
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np
from PIL import Image, ImageTk


# Délai debounce en ms — assez court pour paraître réactif,
# assez long pour ne pas recalculer à chaque pixel de déplacement
_DEBOUNCE_MS = 80


class PopupBase(tk.Toplevel, ABC):
    """
    Fenêtre modale de calibration.

    Paramètres
    ----------
    parent      : widget Tkinter parent
    roi_image   : image BGR du ROI à calibrer
    title       : titre de la fenêtre
    width/height: dimensions de la popup
    """

    def __init__(
        self,
        parent,
        roi_image : np.ndarray,
        title     : str  = "Calibration",
        width     : int  = 900,
        height    : int  = 620,
    ):
        super().__init__(parent)
        self.title(title)
        self.geometry(f"{width}x{height}")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self.roi_image  = roi_image.copy()
        self._validated = False
        self._result    : Optional[Dict[str, Any]] = None
        self._tk_images : List[ImageTk.PhotoImage] = []  # anti-GC

        # --- Debounce ---
        # Identifiant du job after() en attente (None = pas de job)
        self._debounce_job : Optional[str] = None

        # --- Cache aperçu ---
        # Labels existants dans la zone preview — réutilisés à chaque refresh
        # pour éviter de détruire/recréer les widgets (cause du flash)
        self._preview_labels : List[ttk.Label] = []
        self._preview_cols   : int = 0

        self._build_layout()
        self.build_controls(self._frame_controls)
        self.update_preview()

        # Centrage sur le parent
        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - width)  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        self.geometry(f"{width}x{height}+{px}+{py}")

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.wait_window(self)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=3)
        self.rowconfigure(1, weight=2)
        self.rowconfigure(2, weight=0)

        self._frame_preview = ttk.LabelFrame(self, text="Aperçu")
        self._frame_preview.grid(row=0, column=0,
                                 sticky="nsew", padx=8, pady=(8, 4))

        self._frame_controls = ttk.LabelFrame(self, text="Paramètres")
        self._frame_controls.grid(row=1, column=0,
                                  sticky="nsew", padx=8, pady=4)

        frame_btns = ttk.Frame(self)
        frame_btns.grid(row=2, column=0,
                        sticky="ew", padx=8, pady=(4, 8))

        ttk.Button(frame_btns, text="Annuler",
                   command=self._on_cancel).pack(side="left",  padx=8)
        ttk.Button(frame_btns, text="✅  Valider",
                   command=self._on_validate).pack(side="right", padx=8)

    # ------------------------------------------------------------------
    # Méthodes abstraites
    # ------------------------------------------------------------------

    @abstractmethod
    def build_controls(self, frame: ttk.LabelFrame):
        ...

    @abstractmethod
    def update_preview(self):
        ...

    @abstractmethod
    def get_result(self) -> Optional[Dict[str, Any]]:
        ...

    # ------------------------------------------------------------------
    # Debounce — à appeler depuis les callbacks des sliders
    # ------------------------------------------------------------------

    def schedule_preview_update(self):
        """
        Planifie un appel à update_preview() dans _DEBOUNCE_MS ms.
        Si un appel est déjà planifié, il est annulé et remplacé.
        Résultat : update_preview() n'est appelé qu'une seule fois
        après la fin du déplacement, éliminant les flashs.
        """
        if self._debounce_job is not None:
            self.after_cancel(self._debounce_job)
        self._debounce_job = self.after(_DEBOUNCE_MS, self._do_update)

    def _do_update(self):
        self._debounce_job = None
        self.update_preview()

    # ------------------------------------------------------------------
    # Affichage aperçu — SANS destruction de widgets
    # ------------------------------------------------------------------

    def _show_images_in_preview(
        self,
        images: List[Tuple[str, np.ndarray]],
    ):
        """
        Affiche une liste de (label, image_bgr_ou_gray) en colonnes.

        Premier appel  : crée les frames, labels texte et labels image.
        Appels suivants: met à jour UNIQUEMENT l'image dans les labels
                         existants — aucun widget n'est détruit/recréé
                         → pas de flash.
        """
        n = len(images)
        if n == 0:
            return

        target_h = max(160, self._frame_preview.winfo_height() - 40)
        target_w = max(160, (self._frame_preview.winfo_width() - 20) // n)

        # ---- Premier appel ou changement du nombre de colonnes ----
        if n != self._preview_cols:
            # Vider complètement (rare — seulement si le nb d'images change)
            for w in self._frame_preview.winfo_children():
                w.destroy()
            self._preview_labels.clear()
            self._tk_images.clear()
            self._preview_cols = n

            for col, (lbl_text, img) in enumerate(images):
                frame = ttk.Frame(self._frame_preview)
                frame.grid(row=0, column=col,
                           padx=4, pady=4, sticky="nsew")
                self._frame_preview.columnconfigure(col, weight=1)

                ttk.Label(frame, text=lbl_text,
                          font=("Arial", 10, "bold")).pack(pady=2)

                tk_img = self._cv_to_tk(img, target_w, target_h)
                self._tk_images.append(tk_img)

                img_lbl = ttk.Label(frame, image=tk_img)
                img_lbl.pack(expand=True)
                self._preview_labels.append(img_lbl)

            return

        # ---- Appels suivants : mise à jour en place ----
        # On remplace uniquement l'image dans chaque Label
        # Pas de destroy(), pas de pack() → aucun flash
        self._tk_images.clear()
        for i, (_, img) in enumerate(images):
            tk_img = self._cv_to_tk(img, target_w, target_h)
            self._tk_images.append(tk_img)
            if i < len(self._preview_labels):
                self._preview_labels[i].configure(image=tk_img)
                # Garder la référence sur le label pour éviter le GC
                self._preview_labels[i].image = tk_img  # type: ignore

    # ------------------------------------------------------------------
    # Conversion OpenCV → Tkinter
    # ------------------------------------------------------------------

    @staticmethod
    def _cv_to_tk(
        img   : np.ndarray,
        max_w : int,
        max_h : int,
    ) -> ImageTk.PhotoImage:
        h, w = img.shape[:2]
        scale = min(max_w / w, max_h / h, 1.0)
        if scale < 1.0:
            nw, nh = int(w * scale), int(h * scale)
            img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        else:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        return ImageTk.PhotoImage(Image.fromarray(img))

    # ------------------------------------------------------------------
    # Helper sliders — avec debounce intégré
    # ------------------------------------------------------------------

    def _add_slider(
        self,
        parent    : tk.Widget,
        label     : str,
        var       : tk.Variable,
        from_     : float,
        to        : float,
        row       : int,
        on_change : Optional[callable] = None,
        decimals  : int  = 0,
        col_offset: int  = 0,
    ):
        """
        Ajoute un slider avec label et valeur affichée.

        Le callback on_change est appelé via schedule_preview_update()
        (debounce 80ms) pour éviter les flashs pendant le glissement.
        """
        tk.Label(parent, text=label, anchor="w",
                 font=("Arial", 9)).grid(
            row=row, column=col_offset,
            sticky="w", padx=6, pady=2)

        tk.Label(parent, textvariable=var,
                 width=6, font=("Arial", 9, "bold"),
                 anchor="e").grid(
            row=row, column=col_offset + 2, padx=4)

        def _on_slide(v):
            # 1. Mettre à jour la variable (valeur affichée instantanée)
            if decimals == 0:
                var.set(int(float(v)))
            else:
                var.set(round(float(v), decimals))
            # 2. Appeler le callback métier via debounce
            if on_change:
                self.schedule_preview_update()

        slider = ttk.Scale(
            parent, from_=from_, to=to,
            orient="horizontal",
            variable=var, command=_on_slide,
        )
        slider.grid(row=row, column=col_offset + 1,
                    sticky="ew", padx=6, pady=2)
        parent.columnconfigure(col_offset + 1, weight=1)
        return slider

    # ------------------------------------------------------------------
    # Boutons
    # ------------------------------------------------------------------

    def _on_validate(self):
        self._validated = True
        self._result    = self.get_result()
        self.destroy()

    def _on_cancel(self):
        self._validated = False
        self._result    = None
        self.destroy()

    # ------------------------------------------------------------------
    # Propriétés
    # ------------------------------------------------------------------

    @property
    def validated(self) -> bool:
        return self._validated

    @property
    def result(self) -> Optional[Dict[str, Any]]:
        return self._result
