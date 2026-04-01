"""
screen_configuration.py
------------------------
Écran 2 : Interface principale de configuration.

Un onglet par défaut configuré.
Chaque onglet contient :
  - Paramètres d'acquisition (mode, étage, angles)
  - Image de référence avec canvas interactif
  - Liste des ROIs avec boutons Calibrer / Supprimer
  - Bouton Ancre
"""

from __future__ import annotations
from typing import Dict, List, Optional
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import cv2
import numpy as np

from shared.core.models import (
    RecetteConfig, DefautConfig, ROIConfig,
    AlignmentConfig, AcquisitionConfig,
    DEFAUTS_PAR_SERVICE, ALGORITHMES_PAR_SERVICE,
    TYPES_ROI_PAR_ALGORITHME,
)
from shared.core.recipe_manager import (
    load_active, save_new_version, save_overwrite,
    save_ref_image, get_ref_image_path,
    get_relative_image_path, merge_with_previous,
    get_version_history,
)
from ui.canvas_image import ImageCanvas, ROI_COLORS_BGR
from ui.popups.popup_presence_hsv      import PopupPresenceHSV
from ui.popups.popup_niveau_sobel      import PopupNiveauSobel
from ui.popups.popup_profil_canny      import PopupProfilCanny
from ui.popups.popup_derive_centre     import PopupDeriveCentre
from ui.popups.popup_orientation_masque import PopupOrientationMasque
from ui.popups.popup_check_position    import PopupCheckPosition


# Mapping algorithme → classe popup
POPUP_MAP = {
    "presence_hsv"     : PopupPresenceHSV,
    "orientation_masque": PopupOrientationMasque,
    "niveau_sobel"     : PopupNiveauSobel,
    "profil_canny"     : PopupProfilCanny,
    "derive_centre"    : PopupDeriveCentre,
    "symmetry_canny"   : PopupCheckPosition,
}


class ScreenConfiguration(tk.Tk):

    def __init__(
        self,
        type_bouteille : str,
        service        : str,
        description    : str = "",
    ):
        super().__init__()
        self.title(
            f"Configuration — {type_bouteille}  [{service}]"
        )
        self.geometry("1280x820")
        self.resizable(True, True)
        self.configure(bg="#f0f2f5")

        self._type_btl   = type_bouteille
        self._service    = service

        # Charger ou créer la recette
        self._recette = load_active(service, type_bouteille)
        if self._recette is None:
            from shared.core.models import RecetteConfig
            self._recette = RecetteConfig.nouvelle(
                type_bouteille, description, service
            )

        # Images chargées par onglet {id_defaut: np.ndarray}
        self._images : Dict[str, Optional[np.ndarray]] = {}

        # Onglets ouverts {id_defaut: TabDefaut}
        self._tabs   : Dict[str, "_TabDefaut"] = {}

        self._build_ui()
        self._load_existing_tabs()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Construction UI principale
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ---- En-tête ----
        header = tk.Frame(self, bg="#2c3e50", height=65)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text=f"⚙️   {self._type_btl}   ·   {self._service}   "
                 f"·   v{self._recette.version}",
            font=("Arial", 14, "bold"),
            fg="white", bg="#2c3e50",
        ).pack(side="left", padx=20, pady=12)

        # Boutons header
        btn_frame = tk.Frame(header, bg="#2c3e50")
        btn_frame.pack(side="right", padx=15, pady=8)

        ttk.Button(btn_frame, text="💾  Enregistrer",
                   command=self._on_save).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="➕  Ajouter défaut",
                   command=self._add_defaut_dialog).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="📋  Versions",
                   command=self._show_versions).pack(side="right", padx=4)

        # ---- Notebook principal ----
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True,
                            padx=10, pady=(5, 0))

        # ---- Pied de page ----
        footer = tk.Frame(self, bg="#e8eaf0", height=35)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        self._lbl_status = tk.Label(
            footer, text="",
            font=("Arial", 9, "italic"),
            bg="#e8eaf0", fg="#555555",
        )
        self._lbl_status.pack(side="left", padx=15, pady=6)

    # ------------------------------------------------------------------
    # Chargement des onglets existants
    # ------------------------------------------------------------------

    def _load_existing_tabs(self):
        """Crée un onglet pour chaque défaut présent dans la recette."""
        for defaut in self._recette.defauts:
            self._open_tab(defaut)

    def _open_tab(self, defaut: DefautConfig):
        """Crée et affiche un onglet pour un défaut."""
        tab = _TabDefaut(
            self._notebook, defaut, self._service,
            self._type_btl, self._recette,
            on_modified=self._on_tab_modified,
        )
        tab_label = f"{defaut.id_defaut} — {defaut.label}"
        self._notebook.add(tab, text=tab_label)
        self._tabs[defaut.id_defaut] = tab

        # Charger l'image de référence si elle existe
        img_path = get_ref_image_path(
            self._service, self._type_btl, defaut.id_defaut
        )
        if img_path and img_path.exists():
            img = cv2.imdecode(
                np.fromfile(str(img_path), dtype=np.uint8),
                cv2.IMREAD_COLOR
            )
            if img is not None:
                tab.set_image(img)

    # ------------------------------------------------------------------
    # Ajouter un défaut
    # ------------------------------------------------------------------

    def _add_defaut_dialog(self):
        """Dialog pour choisir quel défaut ajouter."""
        available = DEFAUTS_PAR_SERVICE[self._service]
        existing  = {d.id_defaut for d in self._recette.defauts}
        choices   = {k: v for k, v in available.items() if k not in existing}

        if not choices:
            messagebox.showinfo(
                "Tous les défauts configurés",
                "Tous les défauts disponibles pour cette famille\n"
                "sont déjà présents dans la recette.",
                parent=self,
            )
            return

        dialog = _AddDefautDialog(self, choices)
        if dialog.selected:
            defaut = DefautConfig.nouveau(dialog.selected, self._service)
            self._recette.set_defaut(defaut)
            self._open_tab(defaut)
            # Aller sur le nouvel onglet
            self._notebook.select(len(self._notebook.tabs()) - 1)
            self._set_status(f"Défaut {dialog.selected} ajouté.")

    # ------------------------------------------------------------------
    # Sauvegarde
    # ------------------------------------------------------------------

    def _on_save(self):
        dialog = _SaveDialog(self, self._recette.version)
        if not dialog.confirmed:
            return

        # Fusionner avec la version précédente
        # (conserve les défauts non modifiés)
        self._recette = merge_with_previous(self._recette)

        if dialog.new_version:
            path = save_new_version(self._recette)
            msg  = f"Nouvelle version v{self._recette.version} créée."
        else:
            path = save_overwrite(self._recette)
            msg  = f"Version v{self._recette.version} mise à jour."

        self._set_status(f"✅ {msg}  →  {path.name}")
        self.title(
            f"Configuration — {self._type_btl}  [{self._service}]  "
            f"·  v{self._recette.version}"
        )

    # ------------------------------------------------------------------
    # Historique des versions
    # ------------------------------------------------------------------

    def _show_versions(self):
        history = get_version_history(self._service, self._type_btl)
        if not history:
            messagebox.showinfo("Historique", "Aucune version enregistrée.",
                                parent=self)
            return
        lines = [f"v{v}  →  {p.name}" for v, p in history]
        messagebox.showinfo(
            "Historique des versions",
            "\n".join(lines),
            parent=self,
        )

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_tab_modified(self, id_defaut: str, defaut: DefautConfig):
        """Appelé quand un onglet modifie son défaut."""
        self._recette.set_defaut(defaut)
        self._set_status(f"Modifié : {id_defaut}")

    def _set_status(self, msg: str):
        self._lbl_status.config(text=msg)

    def _on_close(self):
        if messagebox.askyesno(
            "Quitter",
            "Quitter sans enregistrer ?\nLes modifications non sauvegardées seront perdues.",
            parent=self,
        ):
            self.destroy()


# ===========================================================================
# Onglet par défaut
# ===========================================================================

class _TabDefaut(tk.Frame):
    """
    Contenu d'un onglet pour un défaut spécifique.
    Gère : image référence, ancre, ROIs, paramètres acquisition.
    """

    def __init__(
        self,
        parent,
        defaut       : DefautConfig,
        service      : str,
        type_btl     : str,
        recette      : RecetteConfig,
        on_modified  : callable,
    ):
        super().__init__(parent, bg="#f0f2f5")
        self._defaut      = defaut
        self._service     = service
        self._type_btl    = type_btl
        self._recette     = recette
        self._on_modified = on_modified
        self._image       : Optional[np.ndarray] = None

        self._build_ui()
        self._refresh_roi_list()

    # ------------------------------------------------------------------
    def _build_ui(self):
        self.columnconfigure(0, weight=2)  # canvas
        self.columnconfigure(1, weight=1)  # panneau droite
        self.rowconfigure(0, weight=1)

        # ---- Canvas image (colonne gauche) ----
        canvas_frame = tk.Frame(self, bg="#f0f2f5")
        canvas_frame.grid(row=0, column=0, sticky="nsew",
                          padx=(8, 4), pady=8)

        self._canvas = ImageCanvas(
            canvas_frame,
            on_roi_drawn    = self._on_roi_drawn,
            on_anchor_drawn = self._on_anchor_drawn,
            on_roi_selected = self._on_roi_selected,
            width=760, height=520,
            bg="#f0f2f5",
        )
        self._canvas.pack(fill="both", expand=True)
        self._canvas.set_rois(self._defaut.rois)
        self._canvas.set_alignment(self._defaut.alignment
                                   if self._defaut.alignment.use_alignment
                                   else None)

        # Toolbar canvas
        toolbar = tk.Frame(canvas_frame, bg="#e0e3ea")
        toolbar.pack(fill="x", pady=(4, 0))

        ttk.Button(toolbar, text="📂  Charger image",
                   command=self._load_image).pack(side="left", padx=4, pady=3)
        ttk.Button(toolbar, text="⚓  Définir ancre",
                   command=lambda: self._canvas.set_mode(
                       ImageCanvas.MODE_ANCHOR)
                   ).pack(side="left", padx=4)
        ttk.Button(toolbar, text="➕  Nouveau ROI",
                   command=lambda: self._canvas.set_mode(
                       ImageCanvas.MODE_ROI)
                   ).pack(side="left", padx=4)
        ttk.Button(toolbar, text="↖️  Sélection",
                   command=lambda: self._canvas.set_mode(
                       ImageCanvas.MODE_SELECT)
                   ).pack(side="left", padx=4)

        self._lbl_mode = tk.Label(toolbar, text="Mode : Sélection",
                                  font=("Arial", 9, "italic"),
                                  bg="#e0e3ea", fg="#555555")
        self._lbl_mode.pack(side="right", padx=8)

        # ---- Panneau droite ----
        right = tk.Frame(self, bg="#f0f2f5")
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)

        # -- Acquisition --
        acq_frame = ttk.LabelFrame(right, text="Acquisition")
        acq_frame.pack(fill="x", pady=(0, 8))

        self._mode_var   = tk.StringVar(
            value=self._defaut.acquisition.mode)
        self._etage_var  = tk.IntVar(
            value=self._defaut.acquisition.etage)
        self._angles_vars: Dict[int, tk.BooleanVar] = {}

        # Mode unique/multiple
        modes_f = tk.Frame(acq_frame, bg="#f0f2f5")
        modes_f.pack(fill="x", padx=8, pady=4)
        for m in ("unique", "multiple"):
            tk.Radiobutton(modes_f, text=m.capitalize(),
                           variable=self._mode_var, value=m,
                           bg="#f0f2f5",
                           command=self._on_acq_changed
                           ).pack(side="left", padx=6)

        # Étage
        etage_f = tk.Frame(acq_frame, bg="#f0f2f5")
        etage_f.pack(fill="x", padx=8, pady=2)
        tk.Label(etage_f, text="Étage :", bg="#f0f2f5",
                 font=("Arial", 9)).pack(side="left")
        tk.Spinbox(etage_f, from_=1, to=20, width=4,
                   textvariable=self._etage_var,
                   command=self._on_acq_changed
                   ).pack(side="left", padx=6)

        # Angles requis — nombre configurable
        angles_outer = tk.Frame(acq_frame, bg="#f0f2f5")
        angles_outer.pack(fill="x", padx=8, pady=4)

        # Ligne 1 : choix du nombre d'angles total
        nb_f = tk.Frame(angles_outer, bg="#f0f2f5")
        nb_f.pack(fill="x", pady=(0, 4))
        tk.Label(nb_f, text="Nb angles total :", bg="#f0f2f5",
                 font=("Arial", 9)).pack(side="left")
        self._nb_angles_var = tk.IntVar(
            value=max(8, max(self._defaut.acquisition.angles_requis or [8]))
        )
        tk.Spinbox(nb_f, from_=1, to=36, width=4,
                   textvariable=self._nb_angles_var,
                   command=self._on_nb_angles_changed
                   ).pack(side="left", padx=6)
        tk.Label(nb_f, text="(définit le nombre de cases à cocher)",
                 font=("Arial", 8, "italic"), fg="#888888",
                 bg="#f0f2f5").pack(side="left", padx=4)

        # Ligne 2 : cases à cocher (générées dynamiquement)
        self._angles_frame = tk.LabelFrame(angles_outer, text="Angles requis",
                                            bg="#f0f2f5", font=("Arial", 8))
        self._angles_frame.pack(fill="x")
        self._angles_vars: Dict[int, tk.BooleanVar] = {}
        self._refresh_angles_checkboxes()

        # -- Actif/Inactif --
        self._actif_var = tk.BooleanVar(value=self._defaut.actif)
        tk.Checkbutton(right, text="✅  Défaut actif",
                       variable=self._actif_var,
                       bg="#f0f2f5",
                       font=("Arial", 10, "bold"),
                       command=self._on_actif_changed
                       ).pack(anchor="w", padx=8, pady=4)

        # -- Image fusionnée (colorimétrique uniquement) --
        # Permet d'analyser sur le panorama déroulé plutôt que
        # sur les images d'angle individuelles
        self._use_fused_var = tk.BooleanVar(
            value=getattr(self._defaut, "use_fused_image", False)
        )
        if self._service == "colorimetrique":
            fused_frame = tk.Frame(right, bg="#fff8e1",
                                   relief="solid", bd=1)
            fused_frame.pack(fill="x", padx=8, pady=(0, 4))
            tk.Checkbutton(
                fused_frame,
                text="🖼  Utiliser l'image fusionnée (panorama)",
                variable=self._use_fused_var,
                bg="#fff8e1",
                font=("Arial", 9, "bold"),
                fg="#7d5a00",
                command=self._on_fused_changed,
            ).pack(anchor="w", padx=6, pady=4)
            tk.Label(
                fused_frame,
                text="Si coché : analyse sur le panorama déroulé\n"
                     "Si décoché : analyse sur les images d'angle",
                font=("Arial", 8, "italic"),
                fg="#888888", bg="#fff8e1",
                justify="left",
            ).pack(anchor="w", padx=20, pady=(0, 4))

        # -- Algorithme (info) --
        tk.Label(right,
                 text=f"Algorithme : {self._defaut.algorithme}",
                 font=("Arial", 9, "italic"),
                 bg="#f0f2f5", fg="#555555"
                 ).pack(anchor="w", padx=8)

        # -- Liste ROIs --
        roi_frame = ttk.LabelFrame(right, text="Zones d'intérêt (ROIs)")
        roi_frame.pack(fill="both", expand=True, pady=(8, 0))

        # Header liste
        hdr = tk.Frame(roi_frame, bg="#e0e3ea")
        hdr.pack(fill="x")
        for txt, w in [("ID", 3), ("Nom", 14), ("Type", 10), ("", 8)]:
            tk.Label(hdr, text=txt, width=w,
                     font=("Arial", 8, "bold"),
                     bg="#e0e3ea", relief="flat"
                     ).pack(side="left", padx=2, pady=2)

        # Zone scrollable
        self._roi_list_frame = tk.Frame(roi_frame, bg="white")
        self._roi_list_frame.pack(fill="both", expand=True)

        # Bouton suppr dernier
        tk.Button(roi_frame, text="🗑  Supprimer dernier ROI",
                  font=("Arial", 8),
                  command=self._delete_last_roi,
                  relief="flat", bg="#ffdddd", fg="#cc0000",
                  cursor="hand2",
                  ).pack(fill="x", padx=4, pady=4)

    # ------------------------------------------------------------------
    # Image
    # ------------------------------------------------------------------

    def set_image(self, img: np.ndarray):
        self._image = img
        self._canvas.load_image(img)

    def _load_image(self):
        path = filedialog.askopenfilename(
            title="Charger l'image de référence",
            filetypes=[
                ("Images", "*.bmp *.jpg *.jpeg *.png *.tif *.tiff"),
                ("Tous", "*.*"),
            ],
        )
        if not path:
            return

        img = cv2.imdecode(
            np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        if img is None:
            messagebox.showerror("Erreur", "Impossible de lire l'image.",
                                 parent=self)
            return

        # Sauvegarde dans le dossier recette
        dest = save_ref_image(path, self._service,
                              self._type_btl, self._defaut.id_defaut)
        self._defaut.reference_image = f"./{dest.name}"
        self.set_image(img)
        self._notify_modified()

    # ------------------------------------------------------------------
    # Ancre
    # ------------------------------------------------------------------

    def _on_anchor_drawn(self, x: int, y: int, w: int, h: int):
        acy = y + h / 2.0
        self._defaut.alignment = AlignmentConfig(
            use_alignment   = True,
            x=x, y=y, width=w, height=h,
            anchor_center_y = round(acy, 2),
        )
        self._canvas.set_alignment(self._defaut.alignment)
        self._canvas.set_mode(ImageCanvas.MODE_SELECT)
        self._notify_modified()

    # ------------------------------------------------------------------
    # ROIs
    # ------------------------------------------------------------------

    def _on_roi_drawn(self, x: int, y: int, w: int, h: int):
        """Appelé quand l'opérateur dessine un nouveau rectangle ROI."""
        if self._image is None:
            messagebox.showwarning(
                "Pas d'image",
                "Chargez d'abord une image de référence.",
                parent=self,
            )
            return

        algo  = self._defaut.algorithme
        types = TYPES_ROI_PAR_ALGORITHME.get(algo, ["presence"])
        roi_type = types[0]

        color = self._canvas.get_next_color()
        roi_id = len(self._defaut.rois)
        roi = ROIConfig(
            id=roi_id, type=roi_type,
            name=f"{roi_type.upper()}_{roi_id}",
            x=x, y=y, width=w, height=h,
            color=color,
        )

        # Ouvrir la popup de calibration immédiatement
        roi_img = self._image[y:y + h, x:x + w]
        if roi_img.size == 0:
            return

        updated = self._open_calibration_popup(roi, roi_img)
        if updated is None:
            return  # annulé

        # Fusionner les paramètres calibrés dans le ROI
        self._apply_calib_result(roi, updated)
        self._defaut.rois.append(roi)
        self._canvas.set_rois(self._defaut.rois)
        self._canvas.set_mode(ImageCanvas.MODE_SELECT)
        self._refresh_roi_list()
        self._notify_modified()

    def _on_roi_selected(self, idx: int):
        """Sélection d'un ROI dans le canvas → highlight dans la liste."""
        self._highlight_roi_row(idx)

    def _delete_last_roi(self):
        if not self._defaut.rois:
            return
        removed = self._defaut.rois.pop()
        self._canvas.set_rois(self._defaut.rois)
        self._refresh_roi_list()
        self._notify_modified()

    # ------------------------------------------------------------------
    # Calibration popup
    # ------------------------------------------------------------------

    def _open_calibration_popup(
        self, roi: ROIConfig, roi_img: np.ndarray
    ):
        """
        Ouvre la popup de calibration adaptée à l algorithme du défaut.

        Algorithmes actifs :
          presence_hsv  → D3.1, D3.3, D2.4, D4.1, D4.4
          niveau_sobel  → D2.1, D2.2, D3.2
          profil_canny  → D1.4, D4.2
          derive_centre → D1.5
        """
        algo = self._defaut.algorithme

        # ----------------------------------------------------------------
        # COLORIMETRIQUE — segmentation HSV
        # ----------------------------------------------------------------
        if algo == "presence_hsv":
            popup = PopupPresenceHSV(
                self, roi_img,
                hsv_params  = getattr(roi, 'hsv_params', None),
                tol_min_pct = 80.0,
                tol_max_pct = 120.0,
            )

        # ----------------------------------------------------------------
        # COLORIMETRIQUE — orientation masque (D3.2 bouchon de travers)
        # ----------------------------------------------------------------
        elif algo == "orientation_masque":
            popup = PopupOrientationMasque(
                self, roi_img,
                hsv_params        = getattr(roi, 'hsv_params', None),
                tol_angle_deg     = getattr(roi, 'tolerance_angle_deg',     None) or 5.0,
                tol_decentrage_px = getattr(roi, 'tolerance_decentrage_px', None) or 10.0,
            )

        # ----------------------------------------------------------------
        # CHECK POSITION — axe de symétrie (CP1.1)
        # ----------------------------------------------------------------
        elif algo == "symmetry_canny":
            popup = PopupCheckPosition(
                self, roi_img,
                canny_low      = getattr(roi, 'canny_low',          None) or 50,
                canny_high     = getattr(roi, 'canny_high',         None) or 150,
                tolerance_px   = getattr(roi, 'tolerance_ecart_px', None) or 15.0,
            )

        # ----------------------------------------------------------------
        # GRADIENT — mesure distance ancre→surface (Sobel Y)
        # Couvre : D2.1 D2.2 (niveau liquide) et D3.2 (bouchon de travers)
        # Pour D3.2 : l ancre est sur le col, la surface = bas du bouchon
        # ----------------------------------------------------------------
        elif algo == "niveau_sobel":
            if not self._defaut.alignment.use_alignment:
                messagebox.showwarning(
                    "Ancre requise",
                    "Définissez d abord la zone d ancrage (⚓ Définir ancre)\n"
                    "avant de créer un ROI niveau_sobel.",
                    parent=self,
                )
                return None
            popup = PopupNiveauSobel(
                self, roi_img,
                roi_y_global   = roi.y,
                anchor_cy      = self._defaut.alignment.anchor_center_y,
                y_surface_init = getattr(roi, 'y_ligne_local_ref', None),
            )

        # ----------------------------------------------------------------
        # GEOMETRIQUE — analyse de profil par contours Canny
        # ----------------------------------------------------------------
        elif algo == "profil_canny":
            popup = PopupProfilCanny(
                self, roi_img,
                canny_low  = getattr(roi, 'canny_low',  None) or 50,
                canny_high = getattr(roi, 'canny_high', None) or 150,
            )

        elif algo == "derive_centre":
            popup = PopupDeriveCentre(
                self, roi_img,
                canny_low  = getattr(roi, 'canny_low',  None) or 50,
                canny_high = getattr(roi, 'canny_high', None) or 150,
                derive_max = getattr(roi, 'derive_max_px', None) or 5.0,
            )

        else:
            messagebox.showwarning(
                "Algorithme inconnu",
                f"Pas de popup disponible pour l algorithme '{algo}'.",
                parent=self,
            )
            return None

        return popup.result if popup.validated else None

    def _calibrate_roi(self, idx: int):
        """Re-calibre un ROI existant."""
        if self._image is None:
            messagebox.showwarning("Pas d'image",
                                   "Chargez d'abord l'image de référence.",
                                   parent=self)
            return

        roi = self._defaut.rois[idx]
        roi_img = self._image[
            roi.y: roi.y + roi.height,
            roi.x: roi.x + roi.width,
        ]
        if roi_img.size == 0:
            return

        result = self._open_calibration_popup(roi, roi_img)
        if result is None:
            return

        self._apply_calib_result(roi, result)
        self._canvas.set_rois(self._defaut.rois)
        self._refresh_roi_list()
        self._notify_modified()

    @staticmethod
    def _apply_calib_result(roi: ROIConfig, result: dict):
        """Applique les résultats d'une popup dans un ROIConfig."""
        for key, val in result.items():
            if hasattr(roi, key):
                setattr(roi, key, val)

    # ------------------------------------------------------------------
    # Liste ROIs
    # ------------------------------------------------------------------

    def _refresh_roi_list(self):
        for w in self._roi_list_frame.winfo_children():
            w.destroy()

        if not self._defaut.rois:
            tk.Label(self._roi_list_frame,
                     text="Aucun ROI — dessinez un rectangle\nsur l'image",
                     font=("Arial", 9, "italic"),
                     fg="#aaaaaa", bg="white",
                     justify="center"
                     ).pack(pady=20)
            return

        for i, roi in enumerate(self._defaut.rois):
            self._build_roi_row(i, roi)

    def _build_roi_row(self, idx: int, roi: ROIConfig):
        bg = "#f8f8f8" if idx % 2 == 0 else "white"
        row_f = tk.Frame(self._roi_list_frame, bg=bg,
                         relief="flat", bd=0)
        row_f.pack(fill="x")

        # Indicateur couleur
        color_hex = "#{:02x}{:02x}{:02x}".format(
            roi.color[2], roi.color[1], roi.color[0]
        )
        tk.Frame(row_f, bg=color_hex, width=6).pack(side="left", fill="y")

        tk.Label(row_f, text=f"#{roi.id}", width=3,
                 font=("Arial", 8), bg=bg).pack(side="left", padx=2)
        tk.Label(row_f, text=roi.name, width=14,
                 font=("Arial", 8, "bold"), bg=bg,
                 anchor="w").pack(side="left")
        tk.Label(row_f, text=roi.type, width=10,
                 font=("Arial", 8, "italic"), bg=bg,
                 fg="#555555").pack(side="left")

        tk.Button(row_f, text="✏️", font=("Arial", 8),
                  relief="flat", bg=bg, cursor="hand2",
                  command=lambda i=idx: self._calibrate_roi(i)
                  ).pack(side="right", padx=2)

        tk.Button(row_f, text="🗑", font=("Arial", 8),
                  relief="flat", bg=bg, cursor="hand2",
                  fg="#cc0000",
                  command=lambda i=idx: self._delete_roi(i)
                  ).pack(side="right", padx=2)

    def _highlight_roi_row(self, idx: int):
        rows = self._roi_list_frame.winfo_children()
        for i, row in enumerate(rows):
            if isinstance(row, tk.Frame):
                row.config(bg="#dde8ff" if i == idx else
                           ("#f8f8f8" if i % 2 == 0 else "white"))

    def _delete_roi(self, idx: int):
        if messagebox.askyesno(
            "Supprimer",
            f"Supprimer le ROI #{self._defaut.rois[idx].id} ?",
            parent=self,
        ):
            self._defaut.rois.pop(idx)
            # Re-numéroter
            for i, r in enumerate(self._defaut.rois):
                r.id = i
            self._canvas.set_rois(self._defaut.rois)
            self._refresh_roi_list()
            self._notify_modified()

    # ------------------------------------------------------------------
    # Acquisition
    # ------------------------------------------------------------------

    def _on_nb_angles_changed(self, *_):
        """Appelé quand l'utilisateur change le nombre total d'angles."""
        self._refresh_angles_checkboxes()
        self._on_acq_changed()

    def _refresh_angles_checkboxes(self):
        """Recrée les cases à cocher selon le nombre d'angles configuré."""
        # Vider le frame existant
        for w in self._angles_frame.winfo_children():
            w.destroy()

        nb    = self._nb_angles_var.get()
        req   = set(self._defaut.acquisition.angles_requis)
        cols  = min(nb, 12)   # max 12 cases par ligne pour lisibilité
        row_i = 0

        new_vars: Dict[int, tk.BooleanVar] = {}
        for i in range(1, nb + 1):
            col_i = (i - 1) % cols
            if col_i == 0 and i > 1:
                row_i += 1
            # Conserver l'état coché si l'angle existait avant
            was_checked = self._angles_vars.get(i, tk.BooleanVar(value=(i in req))).get()
            var = tk.BooleanVar(value=was_checked or (i in req))
            new_vars[i] = var
            tk.Checkbutton(self._angles_frame, text=str(i),
                           variable=var,
                           bg="#f0f2f5", font=("Arial", 8),
                           command=self._on_acq_changed
                           ).grid(row=row_i, column=col_i, padx=2, pady=1)

        self._angles_vars = new_vars

    def _on_acq_changed(self, *_):
        angles = [i for i, v in self._angles_vars.items() if v.get()]
        self._defaut.acquisition = AcquisitionConfig(
            mode          = self._mode_var.get(),
            etage         = self._etage_var.get(),
            angles_requis = sorted(angles),
        )
        self._notify_modified()

    def _on_actif_changed(self):
        self._defaut.actif = self._actif_var.get()
        self._notify_modified()

    def _on_fused_changed(self):
        self._defaut.use_fused_image = self._use_fused_var.get()
        self._notify_modified()

    # ------------------------------------------------------------------
    # Notification parent
    # ------------------------------------------------------------------

    def _notify_modified(self):
        self._on_modified(self._defaut.id_defaut, self._defaut)


# ===========================================================================
# Dialogues auxiliaires
# ===========================================================================

class _AddDefautDialog(tk.Toplevel):
    """Dialog de sélection d'un défaut à ajouter."""

    def __init__(self, parent, choices: dict):
        super().__init__(parent)
        self.title("Ajouter un défaut")
        self.geometry("420x380")
        self.transient(parent)
        self.grab_set()
        self.selected : Optional[str] = None

        tk.Label(self, text="Choisir le défaut à configurer :",
                 font=("Arial", 11, "bold")).pack(pady=12)

        for id_def, meta in choices.items():
            frame = tk.Frame(self, relief="solid", bd=1, cursor="hand2")
            frame.pack(fill="x", padx=20, pady=4)

            tk.Label(frame, text=id_def,
                     font=("Arial", 11, "bold"),
                     fg="#2c3e50", width=8, anchor="w"
                     ).pack(side="left", padx=8, pady=6)
            tk.Label(frame, text=meta["label"],
                     font=("Arial", 10), anchor="w"
                     ).pack(side="left")
            sev_color = {"Critique": "red", "Majeur": "orange",
                         "Mineur": "gray"}.get(meta["severite"], "gray")
            tk.Label(frame, text=meta["severite"],
                     font=("Arial", 8, "italic"),
                     fg=sev_color).pack(side="right", padx=8)

            def _pick(i=id_def):
                self.selected = i
                self.destroy()

            frame.bind("<Button-1>", lambda e, f=_pick: f())
            for child in frame.winfo_children():
                child.bind("<Button-1>", lambda e, f=_pick: f())

        ttk.Button(self, text="Annuler",
                   command=self.destroy).pack(pady=8)
        self.wait_window(self)


class _SaveDialog(tk.Toplevel):
    """Dialog de choix nouvelle version vs écrasement."""

    def __init__(self, parent, current_version: int):
        super().__init__(parent)
        self.title("Enregistrer la recette")
        self.geometry("360x200")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        self.confirmed    : bool = False
        self.new_version  : bool = True

        self._var = tk.BooleanVar(value=True)

        tk.Label(self,
                 text=f"Version actuelle : v{current_version}",
                 font=("Arial", 10, "italic"),
                 fg="#555555"
                 ).pack(pady=(14, 4))

        tk.Radiobutton(
            self,
            text=f"Créer une nouvelle version  (v{current_version + 1})",
            variable=self._var, value=True,
            font=("Arial", 10),
        ).pack(anchor="w", padx=30, pady=4)

        tk.Radiobutton(
            self,
            text=f"Modifier la version actuelle  (v{current_version})",
            variable=self._var, value=False,
            font=("Arial", 10),
        ).pack(anchor="w", padx=30, pady=4)

        btn_f = tk.Frame(self)
        btn_f.pack(pady=14)
        ttk.Button(btn_f, text="Annuler",
                   command=self.destroy).pack(side="left", padx=8)
        ttk.Button(btn_f, text="✅  OK",
                   command=self._on_ok).pack(side="left", padx=8)

        self.wait_window(self)

    def _on_ok(self):
        self.confirmed   = True
        self.new_version = self._var.get()
        self.destroy()