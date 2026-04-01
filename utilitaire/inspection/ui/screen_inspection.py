"""
screen_inspection.py
--------------------
Écran principal du programme d'inspection UI.

Workflow :
  1. Choisir le type de bouteille
  2. Choisir le défaut à tester (tous services confondus)
  3. Charger une image
  4. Lancer l'inspection → Dashboard
"""

from __future__ import annotations
from typing import Dict, List, Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import cv2
import numpy as np
from PIL import Image, ImageTk
from pathlib import Path

from shared.core.models import (
    SERVICES, DEFAUTS_PAR_SERVICE, DefautConfig, RecetteConfig
)
from shared.core.recipe_manager import (
    load_active, list_types, get_ref_image_path, get_data_dir
)
from shared.engines.engine_base import create_engine, InspectionReport
from ui.dashboard import Dashboard


# Couleurs services
SERVICE_COLORS = {
    "colorimetrique": "#3a7bd5",
    "gradient"      : "#00b09b",
    "geometrique"   : "#f7971e",
}


class ScreenInspection(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Roll-over QC — Inspection UI")
        self.geometry("1280x800")
        self.resizable(True, True)
        self.configure(bg="#f0f2f5")

        # État courant
        self._type_btl     : Optional[str]         = None
        self._recettes     : Dict[str, RecetteConfig] = {}  # service → recette
        self._defaut_sel   : Optional[DefautConfig] = None
        self._image        : Optional[np.ndarray]   = None
        self._image_path   : str                    = ""
        self._last_report  : Optional[InspectionReport] = None

        self._tk_preview   : Optional[ImageTk.PhotoImage] = None

        self._build_ui()

    # ------------------------------------------------------------------
    # Construction UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ---- En-tête ----
        header = tk.Frame(self, bg="#2c3e50", height=60)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header,
                 text="🔍   Inspection UI — Validation des recettes",
                 font=("Arial", 14, "bold"),
                 fg="white", bg="#2c3e50"
                 ).pack(side="left", padx=20, pady=12)

        tk.Label(header,
                 text=f"📁  {get_data_dir()}",
                 font=("Arial", 8, "italic"),
                 fg="#aaaaaa", bg="#2c3e50"
                 ).pack(side="right", padx=20)

        # ---- Corps principal ----
        body = tk.Frame(self, bg="#f0f2f5")
        body.pack(fill="both", expand=True, padx=12, pady=10)

        body.columnconfigure(0, weight=1)   # panneau gauche
        body.columnconfigure(1, weight=2)   # aperçu image
        body.rowconfigure(0, weight=1)

        # ---- Panneau gauche ----
        left = tk.Frame(body, bg="#f0f2f5")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # -- Sélection type bouteille --
        type_frame = ttk.LabelFrame(left, text="Type de bouteille")
        type_frame.pack(fill="x", pady=(0, 8))

        self._type_var = tk.StringVar()
        self._type_combo = ttk.Combobox(
            type_frame, textvariable=self._type_var,
            state="readonly", font=("Arial", 11)
        )
        self._type_combo.pack(fill="x", padx=8, pady=6)
        self._type_combo.bind("<<ComboboxSelected>>", self._on_type_changed)

        ttk.Button(type_frame, text="🔄  Rafraîchir",
                   command=self._refresh_types
                   ).pack(padx=8, pady=(0, 6))

        # -- Sélection défaut --
        defaut_frame = ttk.LabelFrame(left, text="Défaut à inspecter")
        defaut_frame.pack(fill="both", expand=True, pady=(0, 8))

        # Liste des défauts avec scrollbar
        list_container = tk.Frame(defaut_frame)
        list_container.pack(fill="both", expand=True, padx=6, pady=6)

        scrollbar = ttk.Scrollbar(list_container)
        scrollbar.pack(side="right", fill="y")

        self._defaut_listbox = tk.Listbox(
            list_container,
            yscrollcommand=scrollbar.set,
            font=("Arial", 10),
            selectmode="single",
            activestyle="none",
            height=12,
        )
        self._defaut_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self._defaut_listbox.yview)
        self._defaut_listbox.bind("<<ListboxSelect>>", self._on_defaut_selected)

        # Info défaut sélectionné
        self._lbl_defaut_info = tk.Label(
            defaut_frame,
            text="Aucun défaut sélectionné",
            font=("Arial", 9, "italic"),
            fg="#666666", bg="#f0f2f5",
            wraplength=280, justify="left",
        )
        self._lbl_defaut_info.pack(padx=8, pady=4, anchor="w")

        # -- Image --
        img_frame = ttk.LabelFrame(left, text="Image à inspecter")
        img_frame.pack(fill="x", pady=(0, 8))

        ttk.Button(img_frame, text="📂  Charger une image",
                   command=self._load_image
                   ).pack(fill="x", padx=8, pady=4)

        self._lbl_img_name = tk.Label(
            img_frame,
            text="Aucune image chargée",
            font=("Arial", 9, "italic"),
            fg="#888888", bg="#f0f2f5",
        )
        self._lbl_img_name.pack(padx=8, pady=(0, 6))

        # -- Bouton Inspecter --
        self._btn_inspect = ttk.Button(
            left,
            text="▶️   Lancer l'inspection",
            command=self._run_inspection,
            state="disabled",
        )
        self._btn_inspect.pack(fill="x", pady=4)

        # -- Statut --
        self._lbl_status = tk.Label(
            left, text="",
            font=("Arial", 10, "bold"),
            bg="#f0f2f5",
        )
        self._lbl_status.pack(pady=4)

        # -- Derniers résultats --
        self._btn_dashboard = ttk.Button(
            left,
            text="📊  Revoir le Dashboard",
            command=self._show_last_dashboard,
            state="disabled",
        )
        self._btn_dashboard.pack(fill="x", pady=2)

        # ---- Aperçu image (droite) ----
        right = tk.Frame(body, bg="#1a1a2e",
                         relief="solid", bd=1)
        right.grid(row=0, column=1, sticky="nsew")

        self._canvas_preview = tk.Canvas(
            right, bg="#1a1a2e",
            highlightthickness=0,
        )
        self._canvas_preview.pack(fill="both", expand=True)
        self._canvas_preview.bind("<Configure>", self._refresh_preview)

        # ---- Pied de page ----
        footer = tk.Frame(self, bg="#e8eaf0", height=30)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        self._lbl_footer = tk.Label(
            footer, text="Prêt",
            font=("Arial", 8, "italic"),
            bg="#e8eaf0", fg="#666666",
        )
        self._lbl_footer.pack(side="left", padx=12, pady=5)

        # Chargement initial
        self._refresh_types()

    # ------------------------------------------------------------------
    # Types de bouteilles
    # ------------------------------------------------------------------

    def _refresh_types(self):
        """Recharge la liste de tous les types disponibles (tous services)."""
        all_types = set()
        for svc in SERVICES:
            all_types.update(list_types(svc))

        types = sorted(all_types)
        self._type_combo["values"] = types

        if types:
            self._type_combo.set(types[0])
            self._on_type_changed()
        else:
            self._type_combo.set("")
            self._set_footer("Aucun type de bouteille configuré.")

    def _on_type_changed(self, *_):
        self._type_btl  = self._type_var.get()
        self._recettes  = {}
        self._defaut_sel = None

        # Charger les recettes disponibles pour ce type
        for svc in SERVICES:
            r = load_active(svc, self._type_btl)
            if r is not None:
                self._recettes[svc] = r

        self._refresh_defaut_list()
        self._set_footer(f"Type : {self._type_btl}  "
                         f"({len(self._recettes)} service(s) chargé(s))")

    # ------------------------------------------------------------------
    # Liste des défauts
    # ------------------------------------------------------------------

    def _refresh_defaut_list(self):
        self._defaut_listbox.delete(0, tk.END)
        self._defaut_items : List[DefautConfig] = []

        for svc, recette in self._recettes.items():
            for defaut in recette.defauts:
                if not defaut.actif:
                    continue
                label = f"[{svc[:3].upper()}]  {defaut.id_defaut}  —  {defaut.label}"
                self._defaut_listbox.insert(tk.END, label)

                # Coloration par service
                idx = self._defaut_listbox.size() - 1
                color = SERVICE_COLORS.get(svc, "#000000")
                # Tkinter Listbox ne supporte pas les couleurs par item nativement
                # on utilise le tag via itemconfig
                self._defaut_listbox.itemconfig(idx, fg=color)

                self._defaut_items.append(defaut)

        if not self._defaut_items:
            self._defaut_listbox.insert(tk.END,
                "  Aucun défaut configuré pour ce type")

    def _on_defaut_selected(self, *_):
        sel = self._defaut_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._defaut_items):
            return

        self._defaut_sel = self._defaut_items[idx]

        # Info
        d = self._defaut_sel
        self._lbl_defaut_info.config(
            text=f"{d.id_defaut} — {d.label}\n"
                 f"Algo : {d.algorithme}  |  "
                 f"Étage : {d.acquisition.etage}  |  "
                 f"ROIs : {len(d.rois)}"
        )

        self._update_inspect_button()

    # ------------------------------------------------------------------
    # Image
    # ------------------------------------------------------------------

    def _load_image(self):
        path = filedialog.askopenfilename(
            title="Charger une image à inspecter",
            filetypes=[
                ("Images", "*.bmp *.jpg *.jpeg *.png *.tif *.tiff"),
                ("Tous", "*.*"),
            ],
        )
        if not path:
            return

        img = cv2.imdecode(
            np.fromfile(path, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        if img is None:
            messagebox.showerror("Erreur",
                                 "Impossible de lire l'image.",
                                 parent=self)
            return

        self._image      = img
        self._image_path = path
        name = Path(path).name
        self._lbl_img_name.config(text=name)
        self._refresh_preview()
        self._update_inspect_button()
        self._set_footer(f"Image chargée : {name}  "
                         f"({img.shape[1]}×{img.shape[0]})")

    def _refresh_preview(self, *_):
        if self._image is None:
            self._canvas_preview.delete("all")
            self._canvas_preview.create_text(
                self._canvas_preview.winfo_width() // 2,
                self._canvas_preview.winfo_height() // 2,
                text="Aucune image chargée\nCliquer sur 'Charger une image'",
                fill="#666688", font=("Arial", 13), justify="center",
            )
            return

        cw = max(10, self._canvas_preview.winfo_width())
        ch = max(10, self._canvas_preview.winfo_height())
        h, w = self._image.shape[:2]
        scale = min(cw / w, ch / h, 1.0)
        nw, nh = int(w * scale), int(h * scale)

        img_resized = cv2.resize(self._image, (nw, nh),
                                 interpolation=cv2.INTER_AREA)
        img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        self._tk_preview = ImageTk.PhotoImage(Image.fromarray(img_rgb))

        ox = (cw - nw) // 2
        oy = (ch - nh) // 2
        self._canvas_preview.delete("all")
        self._canvas_preview.create_image(ox, oy, anchor="nw",
                                          image=self._tk_preview)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def _update_inspect_button(self):
        ready = (self._defaut_sel is not None and
                 self._image is not None and
                 len(self._defaut_sel.rois) > 0)
        self._btn_inspect.config(state="normal" if ready else "disabled")

    def _run_inspection(self):
        if self._defaut_sel is None or self._image is None:
            return

        defaut = self._defaut_sel

        # Charger l'image de référence pour le recalage
        ref_img  = None
        img_path = get_ref_image_path(
            self._get_service_for_defaut(defaut),
            self._type_btl,
            defaut.id_defaut,
        )
        if img_path and img_path.exists():
            ref_img = cv2.imdecode(
                np.fromfile(str(img_path), dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )

        self._set_footer("⏳ Inspection en cours...")
        self.update()

        try:
            engine = create_engine(defaut, ref_img)
            report = engine.inspect(self._image)
            self._last_report = report

            # Mise à jour statut
            color  = "green" if report.is_ok else "red"
            symbol = "✅ OK" if report.is_ok else "❌ NG"
            self._lbl_status.config(text=symbol, fg=color)
            self._btn_dashboard.config(state="normal")

            self._set_footer(
                f"Inspection terminée — {defaut.id_defaut}  →  {report.status_global}  |  "
                f"{sum(1 for r in report.roi_results if r.status=='OK')}/"
                f"{len(report.roi_results)} ROI(s) OK"
            )

            # Ouvrir le Dashboard
            Dashboard(self, report)

        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("Erreur d'inspection", str(e), parent=self)
            self._set_footer(f"❌ Erreur : {e}")

    def _show_last_dashboard(self):
        if self._last_report:
            Dashboard(self, self._last_report)

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    def _get_service_for_defaut(self, defaut: DefautConfig) -> str:
        """Retrouve le service d'un défaut à partir des recettes chargées."""
        for svc, recette in self._recettes.items():
            if any(d.id_defaut == defaut.id_defaut for d in recette.defauts):
                return svc
        return SERVICES[0]

    def _set_footer(self, msg: str):
        self._lbl_footer.config(text=msg)
