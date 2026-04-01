"""
canvas_image.py
---------------
Widget Tkinter réutilisable pour afficher une image OpenCV et permettre
le dessin interactif de rectangles (ROI et zone d'ancrage).

Fonctionnalités :
  - Affichage de l'image redimensionnée au widget (fit)
  - Dessin d'un rectangle à la souris (mode ROI ou mode ancre)
  - Affichage de tous les ROIs existants avec leurs couleurs
  - Affichage de la zone d'ancrage (jaune)
  - Sélection d'un ROI par clic (callback vers le parent)
  - Suppression du dernier ROI
"""

from __future__ import annotations
from typing import Callable, List, Optional, Tuple
import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np
from PIL import Image, ImageTk

from shared.core.models import ROIConfig, AlignmentConfig


# Couleurs prédéfinies pour les ROIs (BGR → converties en RGB pour affichage)
ROI_COLORS_BGR = [
    (0, 255, 0),    # vert
    (255, 0, 0),    # bleu
    (0, 0, 255),    # rouge
    (255, 255, 0),  # cyan
    (255, 0, 255),  # magenta
    (0, 255, 255),  # jaune
    (128, 0, 255),  # violet
    (0, 165, 255),  # orange
]

ANCHOR_COLOR_BGR = (0, 220, 220)   # jaune-doré pour l'ancre


class ImageCanvas(tk.Frame):
    """
    Widget affichant une image OpenCV avec dessin interactif de ROIs.
    """

    MODE_SELECT = "select"
    MODE_ROI    = "roi"
    MODE_ANCHOR = "anchor"

    def __init__(
        self,
        parent,
        on_roi_drawn   : Optional[Callable[[int, int, int, int], None]] = None,
        on_anchor_drawn: Optional[Callable[[int, int, int, int], None]] = None,
        on_roi_selected: Optional[Callable[[int], None]]                = None,
        width          : int = 800,
        height         : int = 500,
        **kwargs,
    ):
        super().__init__(parent, **kwargs)

        self._on_roi_drawn    = on_roi_drawn
        self._on_anchor_drawn = on_anchor_drawn
        self._on_roi_selected = on_roi_selected

        self._canvas_w = width
        self._canvas_h = height

        # Image source (BGR, taille originale)
        self._image_orig : Optional[np.ndarray] = None
        # Facteur d'échelle image → canvas
        self._scale      : float = 1.0
        self._offset_x   : int   = 0
        self._offset_y   : int   = 0

        # ROIs et ancrage
        self._rois      : List[ROIConfig]          = []
        self._alignment : Optional[AlignmentConfig] = None

        # État dessin
        self._mode       = self.MODE_SELECT
        self._drawing    = False
        self._start_pt   : Optional[Tuple[int, int]] = None
        self._current_pt : Optional[Tuple[int, int]] = None

        # ROI sélectionné
        self._selected_roi_idx : int = -1

        # Référence image Tk (anti-GC)
        self._tk_image : Optional[ImageTk.PhotoImage] = None

        self._build_ui()

    # ------------------------------------------------------------------
    # Construction UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        self._canvas = tk.Canvas(
            self,
            width  = self._canvas_w,
            height = self._canvas_h,
            bg     = "#1a1a2e",
            cursor = "crosshair",
        )
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",       self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Configure>",       self._on_resize)

    # ------------------------------------------------------------------
    # Chargement image
    # ------------------------------------------------------------------

    def load_image(self, image: np.ndarray):
        """Charge une image OpenCV (BGR)."""
        self._image_orig = image.copy()
        self._selected_roi_idx = -1
        self._refresh()

    def clear_image(self):
        self._image_orig = None
        self._canvas.delete("all")

    # ------------------------------------------------------------------
    # ROIs et alignement
    # ------------------------------------------------------------------

    def set_rois(self, rois: List[ROIConfig]):
        self._rois = rois
        self._refresh()

    def set_alignment(self, alignment: Optional[AlignmentConfig]):
        self._alignment = alignment
        self._refresh()

    def set_selected_roi(self, idx: int):
        self._selected_roi_idx = idx
        self._refresh()

    # ------------------------------------------------------------------
    # Mode dessin
    # ------------------------------------------------------------------

    def set_mode(self, mode: str):
        """MODE_SELECT | MODE_ROI | MODE_ANCHOR"""
        self._mode = mode
        cursors = {
            self.MODE_SELECT: "arrow",
            self.MODE_ROI   : "crosshair",
            self.MODE_ANCHOR: "crosshair",
        }
        self._canvas.config(cursor=cursors.get(mode, "arrow"))

    # ------------------------------------------------------------------
    # Événements souris
    # ------------------------------------------------------------------

    def _on_press(self, event):
        if self._image_orig is None:
            return
        if self._mode == self.MODE_SELECT:
            self._try_select_roi(event.x, event.y)
            return
        self._drawing   = True
        self._start_pt  = (event.x, event.y)
        self._current_pt = (event.x, event.y)

    def _on_drag(self, event):
        if not self._drawing:
            return
        self._current_pt = (event.x, event.y)
        self._refresh(draw_temp=True)

    def _on_release(self, event):
        if not self._drawing:
            return
        self._drawing    = False
        self._current_pt = (event.x, event.y)

        x1c = min(self._start_pt[0], self._current_pt[0])
        y1c = min(self._start_pt[1], self._current_pt[1])
        x2c = max(self._start_pt[0], self._current_pt[0])
        y2c = max(self._start_pt[1], self._current_pt[1])

        if x2c - x1c < 5 or y2c - y1c < 5:
            return

        # Convertir coords canvas → coords image originale
        x1i, y1i = self._canvas_to_image(x1c, y1c)
        x2i, y2i = self._canvas_to_image(x2c, y2c)
        w_i       = x2i - x1i
        h_i       = y2i - y1i

        if self._mode == self.MODE_ROI and self._on_roi_drawn:
            self._on_roi_drawn(x1i, y1i, w_i, h_i)
        elif self._mode == self.MODE_ANCHOR and self._on_anchor_drawn:
            self._on_anchor_drawn(x1i, y1i, w_i, h_i)

        self._start_pt   = None
        self._current_pt = None
        self._refresh()

    def _try_select_roi(self, cx: int, cy: int):
        """Sélectionne le ROI sous le curseur."""
        ix, iy = self._canvas_to_image(cx, cy)
        for i, roi in enumerate(self._rois):
            if (roi.x <= ix <= roi.x + roi.width and
                    roi.y <= iy <= roi.y + roi.height):
                self._selected_roi_idx = i
                self._refresh()
                if self._on_roi_selected:
                    self._on_roi_selected(i)
                return
        self._selected_roi_idx = -1
        self._refresh()

    # ------------------------------------------------------------------
    # Rendu
    # ------------------------------------------------------------------

    def _on_resize(self, event):
        self._canvas_w = event.width
        self._canvas_h = event.height
        self._refresh()

    def _refresh(self, draw_temp: bool = False):
        """Redessine le canvas complet."""
        self._canvas.delete("all")
        if self._image_orig is None:
            self._draw_placeholder()
            return

        display = self._build_display_image()
        self._tk_image = self._to_tk(display)
        self._canvas.create_image(
            self._offset_x, self._offset_y,
            anchor="nw", image=self._tk_image
        )

        # Rectangle en cours de dessin
        if draw_temp and self._drawing and self._start_pt and self._current_pt:
            color = "#ffff00" if self._mode == self.MODE_ANCHOR else "#00ffff"
            self._canvas.create_rectangle(
                self._start_pt[0], self._start_pt[1],
                self._current_pt[0], self._current_pt[1],
                outline=color, width=2, dash=(4, 4),
            )

    def _build_display_image(self) -> np.ndarray:
        """Construit l'image d'affichage avec tous les overlays."""
        img = self._image_orig.copy()
        h_orig, w_orig = img.shape[:2]

        # Calcul échelle fit
        scale_w = self._canvas_w / w_orig
        scale_h = self._canvas_h / h_orig
        self._scale = min(scale_w, scale_h, 1.0)

        new_w = int(w_orig * self._scale)
        new_h = int(h_orig * self._scale)
        self._offset_x = (self._canvas_w - new_w) // 2
        self._offset_y = (self._canvas_h - new_h) // 2

        # --- Ancre ---
        if self._alignment and self._alignment.use_alignment:
            a = self._alignment
            cv2.rectangle(img, (a.x, a.y),
                          (a.x + a.width, a.y + a.height),
                          ANCHOR_COLOR_BGR, 2)
            acy = int(a.anchor_center_y)
            cv2.line(img, (a.x, acy), (a.x + a.width, acy),
                     ANCHOR_COLOR_BGR, 1)
            cv2.putText(img, "ANCRE",
                        (a.x, max(12, a.y - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        ANCHOR_COLOR_BGR, 1)

        # --- ROIs ---
        for i, roi in enumerate(self._rois):
            color   = tuple(roi.color)
            thick   = 3 if i == self._selected_roi_idx else 2
            cv2.rectangle(img, (roi.x, roi.y),
                          (roi.x + roi.width, roi.y + roi.height),
                          color, thick)
            cv2.putText(img, roi.name,
                        (roi.x, max(12, roi.y - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

            # Highlight sélection
            if i == self._selected_roi_idx:
                overlay = img.copy()
                cv2.rectangle(overlay,
                              (roi.x, roi.y),
                              (roi.x + roi.width, roi.y + roi.height),
                              color, -1)
                cv2.addWeighted(overlay, 0.15, img, 0.85, 0, img)

        # Redimensionnement
        resized = cv2.resize(img, (new_w, new_h),
                             interpolation=cv2.INTER_AREA)
        return resized

    def _draw_placeholder(self):
        self._canvas.create_text(
            self._canvas_w // 2, self._canvas_h // 2,
            text="Aucune image chargée\nCliquer sur 'Charger image'",
            fill="#666688", font=("Arial", 14), justify="center",
        )

    @staticmethod
    def _to_tk(img_bgr: np.ndarray) -> ImageTk.PhotoImage:
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        return ImageTk.PhotoImage(Image.fromarray(img_rgb))

    # ------------------------------------------------------------------
    # Conversion de coordonnées
    # ------------------------------------------------------------------

    def _canvas_to_image(self, cx: int, cy: int) -> Tuple[int, int]:
        """Convertit des coordonnées canvas en coordonnées image originale."""
        if self._image_orig is None or self._scale == 0:
            return cx, cy
        ix = int((cx - self._offset_x) / self._scale)
        iy = int((cy - self._offset_y) / self._scale)
        h, w = self._image_orig.shape[:2]
        return max(0, min(ix, w - 1)), max(0, min(iy, h - 1))

    # ------------------------------------------------------------------
    # Accesseurs utilitaires
    # ------------------------------------------------------------------

    def get_next_color(self) -> List[int]:
        """Retourne la prochaine couleur BGR disponible pour un ROI."""
        return list(ROI_COLORS_BGR[len(self._rois) % len(ROI_COLORS_BGR)])
