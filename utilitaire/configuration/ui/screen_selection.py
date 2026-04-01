"""
screen_selection.py
-------------------
Écran 1 : Sélection ou création d'un type de bouteille.

Affiche les types existants sous forme de cartes cliquables.
Permet d'en créer un nouveau.
Retourne (type_bouteille, service) au programme principal.
"""

from __future__ import annotations
from typing import Optional, Tuple
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from shared.core.models import SERVICES, DEFAUTS_PAR_SERVICE
from shared.core.recipe_manager import list_types, get_current_version_number, get_data_dir


# Palette de couleurs par service
SERVICE_COLORS = {
    "colorimetrique": "#3a7bd5",
    "gradient"      : "#00b09b",
    "geometrique"   : "#f7971e",
    "check_position": "#e74c3c",
}

SERVICE_LABELS = {
    "colorimetrique": "🎨  Colorimétrique\n(Bouchon, Bague, Mousse, Fuites, Marquage)",
    "gradient"      : "🌊  Gradient\n(Niveau liquide)",
    "geometrique"   : "📐  Géométrique\n(Déformation, Col tordu, Étiquette)",
    "check_position": "🎯  Check Position\n(Positionnement bouteille)",
}


class ScreenSelection(tk.Tk):
    """
    Fenêtre principale de sélection.
    Bloque jusqu'à ce que l'utilisateur choisisse un type et un service.
    """

    def __init__(self):
        super().__init__()
        self.title("Roll-over QC — Configuration Recettes")
        self.geometry("1000x680")
        self.resizable(True, True)
        self.configure(bg="#f0f2f5")

        self._selected_type    : Optional[str] = None
        self._selected_service : Optional[str] = None
        self._confirmed        : bool           = False

        self._service_var = tk.StringVar(value="colorimetrique")

        self._build_ui()
        self._refresh_types()

    # ------------------------------------------------------------------
    # Construction UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ---- En-tête ----
        header = tk.Frame(self, bg="#2c3e50", height=70)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text="⚙️   Configuration du Système de Contrôle Qualité",
            font=("Arial", 16, "bold"),
            fg="white", bg="#2c3e50",
        ).pack(side="left", padx=20, pady=15)

        # ---- Corps ----
        body = tk.Frame(self, bg="#f0f2f5")
        body.pack(fill="both", expand=True, padx=20, pady=15)

        # Colonne gauche : choix service
        left = tk.Frame(body, bg="#f0f2f5", width=260)
        left.pack(side="left", fill="y", padx=(0, 15))
        left.pack_propagate(False)

        tk.Label(left, text="Famille d'algorithmes",
                 font=("Arial", 12, "bold"),
                 bg="#f0f2f5", fg="#2c3e50").pack(anchor="w", pady=(0, 10))

        for svc in SERVICES:
            self._build_service_card(left, svc)

        # Séparateur
        ttk.Separator(body, orient="vertical").pack(
            side="left", fill="y", padx=10)

        # Colonne droite : types de bouteilles
        right = tk.Frame(body, bg="#f0f2f5")
        right.pack(side="left", fill="both", expand=True)

        top_right = tk.Frame(right, bg="#f0f2f5")
        top_right.pack(fill="x", pady=(0, 10))

        tk.Label(top_right, text="Types de bouteilles",
                 font=("Arial", 12, "bold"),
                 bg="#f0f2f5", fg="#2c3e50").pack(side="left")

        ttk.Button(top_right, text="➕  Nouveau type",
                   command=self._create_new_type
                   ).pack(side="right")

        # Canvas scrollable pour les cartes
        self._cards_frame_outer = tk.Frame(right, bg="#f0f2f5")
        self._cards_frame_outer.pack(fill="both", expand=True)

        self._canvas_cards = tk.Canvas(
            self._cards_frame_outer, bg="#f0f2f5",
            highlightthickness=0
        )
        scrollbar = ttk.Scrollbar(self._cards_frame_outer,
                                  orient="vertical",
                                  command=self._canvas_cards.yview)
        self._canvas_cards.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._canvas_cards.pack(side="left", fill="both", expand=True)

        self._cards_inner = tk.Frame(self._canvas_cards, bg="#f0f2f5")
        self._canvas_cards.create_window(
            (0, 0), window=self._cards_inner, anchor="nw"
        )
        self._cards_inner.bind(
            "<Configure>",
            lambda e: self._canvas_cards.configure(
                scrollregion=self._canvas_cards.bbox("all")
            )
        )

        # ---- Pied de page ----
        footer = tk.Frame(self, bg="#e8eaf0", height=60)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        self._lbl_selection = tk.Label(
            footer,
            text="Aucune sélection",
            font=("Arial", 10, "italic"),
            bg="#e8eaf0", fg="#666666",
        )
        self._lbl_selection.pack(side="left", padx=20, pady=15)

        # Affichage du répertoire de données actif
        tk.Label(
            footer,
            text=f"📁  {get_data_dir()}",
            font=("Arial", 8, "italic"),
            bg="#e8eaf0", fg="#999999",
        ).pack(side="left", padx=10)

        ttk.Button(footer, text="Quitter",
                   command=self.destroy).pack(side="right", padx=10, pady=10)

        self._btn_ok = ttk.Button(
            footer, text="✅  Ouvrir",
            command=self._on_confirm,
            state="disabled",
        )
        self._btn_ok.pack(side="right", padx=5, pady=10)

    # ------------------------------------------------------------------
    # Carte service
    # ------------------------------------------------------------------

    def _build_service_card(self, parent: tk.Frame, service: str):
        color = SERVICE_COLORS[service]

        card = tk.Frame(
            parent, bg="white",
            relief="solid", bd=1,
            cursor="hand2",
        )
        card.pack(fill="x", pady=4)

        indicator = tk.Frame(card, bg=color, width=6)
        indicator.pack(side="left", fill="y")

        content = tk.Frame(card, bg="white", padx=10, pady=8)
        content.pack(side="left", fill="both", expand=True)

        lbl = tk.Label(content,
                       text=SERVICE_LABELS[service],
                       font=("Arial", 10), bg="white",
                       fg="#2c3e50", justify="left")
        lbl.pack(anchor="w")

        # Défauts couverts
        defauts = list(DEFAUTS_PAR_SERVICE[service].keys())
        tk.Label(content,
                 text="  ".join(defauts),
                 font=("Arial", 8), bg="white",
                 fg="#888888").pack(anchor="w")

        def _select(e=None, s=service, c=card):
            self._service_var.set(s)
            self._refresh_service_cards()
            self._refresh_types()

        for w in [card, indicator, content, lbl]:
            w.bind("<Button-1>", _select)

        card._service = service
        self._cards_service = getattr(self, "_cards_service", [])
        self._cards_service.append(card)
        self._refresh_service_cards()

    def _refresh_service_cards(self):
        current = self._service_var.get()
        for card in getattr(self, "_cards_service", []):
            is_sel = card._service == current
            color  = SERVICE_COLORS[card._service]
            card.config(bg="#f0f8ff" if is_sel else "white",
                        relief="solid", bd=2 if is_sel else 1)
            for child in card.winfo_children():
                if isinstance(child, tk.Frame) and child.winfo_width() == 6:
                    child.config(bg=color if is_sel else "#cccccc")

    # ------------------------------------------------------------------
    # Cartes types de bouteilles
    # ------------------------------------------------------------------

    def _refresh_types(self):
        # Vider
        for w in self._cards_inner.winfo_children():
            w.destroy()

        service = self._service_var.get()
        types   = list_types(service)

        if not types:
            tk.Label(
                self._cards_inner,
                text="Aucun type configuré pour cette famille.\n"
                     "Cliquez sur '➕ Nouveau type' pour commencer.",
                font=("Arial", 11, "italic"),
                fg="#999999", bg="#f0f2f5",
                justify="center",
            ).pack(pady=40)
            return

        # Grille 3 colonnes
        cols = 3
        for i, type_btl in enumerate(types):
            row = i // cols
            col = i % cols
            self._build_type_card(self._cards_inner, type_btl, service, row, col)

        for c in range(cols):
            self._cards_inner.columnconfigure(c, weight=1)

    def _build_type_card(self, parent, type_btl: str,
                          service: str, row: int, col: int):
        version = get_current_version_number(service, type_btl)
        color   = SERVICE_COLORS[service]

        card = tk.Frame(
            parent, bg="white",
            relief="solid", bd=1,
            cursor="hand2",
            width=200, height=110,
        )
        card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
        card.pack_propagate(False)

        # Barre de couleur en haut
        tk.Frame(card, bg=color, height=5).pack(fill="x")

        body = tk.Frame(card, bg="white", padx=12, pady=8)
        body.pack(fill="both", expand=True)

        tk.Label(body, text=type_btl,
                 font=("Arial", 13, "bold"),
                 bg="white", fg="#2c3e50").pack(anchor="w")

        tk.Label(body, text=f"Version active : v{version}",
                 font=("Arial", 9),
                 bg="white", fg="#888888").pack(anchor="w")

        # Indicateur sélectionné
        sel_indicator = tk.Frame(body, bg="white", height=3)
        sel_indicator.pack(fill="x", pady=(6, 0))

        card._type_btl       = type_btl
        card._sel_indicator  = sel_indicator

        def _select(e=None, t=type_btl, c=card):
            self._selected_type    = t
            self._selected_service = self._service_var.get()
            self._refresh_type_selection()
            self._lbl_selection.config(
                text=f"Sélectionné : {t}  |  {self._service_var.get()}  "
                     f"(v{get_current_version_number(self._service_var.get(), t)})"
            )
            self._btn_ok.config(state="normal")

        for w in [card, body]:
            w.bind("<Button-1>", _select)
            w.bind("<Double-Button-1>", lambda e, t=type_btl: self._on_confirm())

    def _refresh_type_selection(self):
        for card in self._cards_inner.winfo_children():
            if hasattr(card, "_type_btl"):
                is_sel = card._type_btl == self._selected_type
                card.config(bg="#f0f8ff" if is_sel else "white",
                            bd=2 if is_sel else 1)
                card._sel_indicator.config(
                    bg=SERVICE_COLORS[self._service_var.get()] if is_sel else "white"
                )

    # ------------------------------------------------------------------
    # Nouveau type
    # ------------------------------------------------------------------

    def _create_new_type(self):
        name = simpledialog.askstring(
            "Nouveau type de bouteille",
            "Nom du type (ex: Type_D, PET_500ml) :",
            parent=self,
        )
        if not name:
            return
        name = name.strip().replace(" ", "_")
        if not name:
            return

        service = self._service_var.get()
        existing = list_types(service)
        if name in existing:
            messagebox.showwarning(
                "Type existant",
                f"Le type '{name}' existe déjà pour {service}.",
                parent=self,
            )
            return

        desc = simpledialog.askstring(
            "Description",
            "Description courte (ex: Bouteille 750ml verre) :",
            parent=self,
        ) or ""

        # Mémoriser pour l'écran de config
        self._selected_type     = name
        self._selected_service  = service
        self._new_type_desc     = desc
        self._confirmed         = True
        self.destroy()

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------

    def _on_confirm(self):
        if not self._selected_type or not self._selected_service:
            messagebox.showwarning(
                "Sélection requise",
                "Veuillez sélectionner un type de bouteille.",
                parent=self,
            )
            return
        self._new_type_desc = ""
        self._confirmed     = True
        self.destroy()

    # ------------------------------------------------------------------
    # Résultat
    # ------------------------------------------------------------------

    def get_selection(self) -> Tuple[Optional[str], Optional[str], str]:
        """
        Retourne (type_bouteille, service, description).
        type_bouteille et service sont None si annulé.
        """
        if not self._confirmed:
            return None, None, ""
        return (
            self._selected_type,
            self._selected_service,
            getattr(self, "_new_type_desc", ""),
        )