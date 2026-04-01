"""
models.py
---------
Structures de données représentant la recette JSON en mémoire.
Chaque dataclass correspond exactement à un niveau du JSON.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SERVICES = ("colorimetrique", "gradient", "geometrique", "check_position")

ALGORITHMES_PAR_SERVICE = {
    # colorimetrique : tout ce qui se détecte par couleur HSV
    "colorimetrique": ["presence_hsv", "orientation_masque"],
    # gradient : tout ce qui se mesure par distance ancre→surface (Sobel Y)
    "gradient":       ["niveau_sobel"],
    # geometrique : tout ce qui se mesure par contours géométriques (Canny)
    "geometrique":    ["profil_canny", "derive_centre"],
    # check_position : vérification du positionnement de la bouteille par axe de symétrie
    "check_position": ["symmetry_canny"],
}

DEFAUTS_PAR_SERVICE = {
    # ----------------------------------------------------------------
    # Service colorimetrique — détection par segmentation HSV
    # Tous les défauts détectables par la COULEUR d une zone
    # ----------------------------------------------------------------
    "colorimetrique": {
        "D3.1": {"label": "Bouchon manquant",          "severite": "Critique", "algorithme": "presence_hsv"},
        "D3.2": {"label": "Bouchon de travers",        "severite": "Critique", "algorithme": "orientation_masque"},
        "D3.3": {"label": "Bague inviolabilité cassée", "severite": "Critique", "algorithme": "presence_hsv"},
        "D2.4": {"label": "Mousse excessive",          "severite": "Mineur",   "algorithme": "presence_hsv"},
        "D4.1": {"label": "Fuites parois",             "severite": "Critique", "algorithme": "presence_hsv"},
        "D4.4": {"label": "Absence de marquage",       "severite": "Majeur",   "algorithme": "presence_hsv"},
    },
    # ----------------------------------------------------------------
    # Service gradient — détection par mesure de distance Sobel Y
    # Tous les défauts détectables par la POSITION d une surface
    # ----------------------------------------------------------------
    "gradient": {
        "D2.1": {"label": "Sous-remplissage",    "severite": "Critique", "algorithme": "niveau_sobel"},
        "D2.2": {"label": "Sur-remplissage",     "severite": "Majeur",   "algorithme": "niveau_sobel"},
    },
    # ----------------------------------------------------------------
    # Service geometrique — détection par analyse de contours Canny
    # Tous les défauts détectables par la GÉOMÉTRIE du profil
    # ----------------------------------------------------------------
    "geometrique": {
        "D1.4": {"label": "Déformation corps",     "severite": "Majeur",   "algorithme": "profil_canny"},
        "D1.5": {"label": "Col tordu",             "severite": "Critique", "algorithme": "derive_centre"},
        "D4.2": {"label": "Étiquette mal centrée", "severite": "Mineur",   "algorithme": "profil_canny"},
    },
    # ----------------------------------------------------------------
    # Service check_position — vérification positionnement bouteille
    # Détecte si la bouteille est bien centrée dans le champ de la caméra
    # ----------------------------------------------------------------
    "check_position": {
        "CP1.1": {"label": "Mauvais positionnement bouteille", "severite": "Critique", "algorithme": "symmetry_canny"},
    },
}

TYPES_ROI_PAR_ALGORITHME = {
    "presence_hsv"    : ["presence"],
    "orientation_masque": ["orientation"],
    "niveau_sobel"    : ["niveau"],
    "profil_canny"    : ["profil"],
    "derive_centre"   : ["profil"],
    "symmetry_canny"  : ["position"],
}

# Labels des services pour l UI
SERVICE_DESCRIPTIONS = {
    "colorimetrique": "Détection par couleur HSV\n(Bouchon, Bague, Mousse, Fuites, Marquage)",
    "gradient":       "Mesure par gradient Sobel Y\n(Niveau liquide)",
    "geometrique":    "Analyse de contours Canny\n(Déformation, Col tordu, Étiquette)",
    "check_position": "Vérification positionnement\n(Axe de symétrie bouteille)",
}


# ---------------------------------------------------------------------------
# ROIConfig
# ---------------------------------------------------------------------------

@dataclass
class ROIConfig:
    """Un rectangle d'intérêt avec tous ses paramètres algorithmiques."""

    id     : int
    type   : str           # "presence", "height", "niveau", "profil", etc.
    name   : str
    x      : int
    y      : int
    width  : int
    height : int
    color  : List[int]     # [B, G, R]

    # Paramètres spécifiques selon le type — tous optionnels
    # --- presence_hsv ---
    hsv_params    : Optional[Dict[str, int]]  = None
    expected_area : Optional[int]             = None
    min_area      : Optional[int]             = None
    max_area      : Optional[int]             = None

    # --- height ---
    y_top_relative  : Optional[int]   = None
    y_ref_relative  : Optional[int]   = None
    expected_height : Optional[int]   = None
    min_height      : Optional[int]   = None
    max_height      : Optional[int]   = None
    detection_method: Optional[str]   = None  # "profile"

    # --- niveau_sobel ---
    y_ligne_local_ref   : Optional[int]   = None
    y_ligne_global_ref  : Optional[int]   = None
    distance_ref_px     : Optional[float] = None
    distance_min_px     : Optional[float] = None
    distance_max_px     : Optional[float] = None
    # Ratio distance/largeur — indépendant du scale (nouveau verdict)
    ratio_ref           : Optional[float] = None
    tolerance_ratio_min : Optional[float] = None
    tolerance_ratio_max : Optional[float] = None

    # --- presence_seuillage ---
    threshold       : Optional[int]   = None
    invert          : Optional[bool]  = None

    # --- profil_canny / derive_centre ---
    canny_low           : Optional[int]   = None
    canny_high          : Optional[int]   = None
    min_largeur_px      : Optional[float] = None
    max_largeur_px      : Optional[float] = None
    max_ecart_type_px   : Optional[float] = None
    max_pct_lignes_ng   : Optional[float] = None
    largeur_reference_px: Optional[float] = None
    derive_max_px       : Optional[float] = None   # pour derive_centre

    # --- symmetry_canny (check_position) ---
    tolerance_ecart_px  : Optional[float] = None   # tolérance écart axe/centre image

    # --- orientation_masque (D3.2 bouchon de travers) ---
    tolerance_angle_deg     : Optional[float] = None  # tolérance inclinaison (degrés)
    tolerance_decentrage_px : Optional[float] = None  # tolérance décentrage (pixels)

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise uniquement les champs non-None."""
        base = {
            "id"    : self.id,
            "type"  : self.type,
            "name"  : self.name,
            "x"     : self.x,
            "y"     : self.y,
            "width" : self.width,
            "height": self.height,
            "color" : self.color,
        }
        optionals = [
            "hsv_params", "expected_area", "min_area", "max_area",
            "y_top_relative", "y_ref_relative", "expected_height",
            "min_height", "max_height", "detection_method",
            "y_ligne_local_ref", "y_ligne_global_ref",
            "distance_ref_px", "distance_min_px", "distance_max_px",
            "ratio_ref", "tolerance_ratio_min", "tolerance_ratio_max",
            "threshold", "invert",
            "canny_low", "canny_high",
            "min_largeur_px", "max_largeur_px",
            "max_ecart_type_px", "max_pct_lignes_ng",
            "largeur_reference_px", "derive_max_px",
            "tolerance_ecart_px",
            "tolerance_angle_deg", "tolerance_decentrage_px",
        ]
        for attr in optionals:
            val = getattr(self, attr)
            if val is not None:
                base[attr] = val
        return base

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ROIConfig":
        return cls(
            id              = d["id"],
            type            = d["type"],
            name            = d["name"],
            x               = d["x"],
            y               = d["y"],
            width           = d["width"],
            height          = d["height"],
            color           = d["color"],
            hsv_params          = d.get("hsv_params"),
            expected_area       = d.get("expected_area"),
            min_area            = d.get("min_area"),
            max_area            = d.get("max_area"),
            y_top_relative      = d.get("y_top_relative"),
            y_ref_relative      = d.get("y_ref_relative"),
            expected_height     = d.get("expected_height"),
            min_height          = d.get("min_height"),
            max_height          = d.get("max_height"),
            detection_method    = d.get("detection_method"),
            y_ligne_local_ref   = d.get("y_ligne_local_ref"),
            y_ligne_global_ref  = d.get("y_ligne_global_ref"),
            distance_ref_px     = d.get("distance_ref_px"),
            distance_min_px     = d.get("distance_min_px"),
            distance_max_px     = d.get("distance_max_px"),
            ratio_ref           = d.get("ratio_ref"),
            tolerance_ratio_min = d.get("tolerance_ratio_min"),
            tolerance_ratio_max = d.get("tolerance_ratio_max"),
            threshold           = d.get("threshold"),
            invert              = d.get("invert"),
            canny_low           = d.get("canny_low"),
            canny_high          = d.get("canny_high"),
            min_largeur_px      = d.get("min_largeur_px"),
            max_largeur_px      = d.get("max_largeur_px"),
            max_ecart_type_px   = d.get("max_ecart_type_px"),
            max_pct_lignes_ng   = d.get("max_pct_lignes_ng"),
            largeur_reference_px    = d.get("largeur_reference_px"),
            derive_max_px           = d.get("derive_max_px"),
            tolerance_ecart_px      = d.get("tolerance_ecart_px"),
            tolerance_angle_deg     = d.get("tolerance_angle_deg"),
            tolerance_decentrage_px = d.get("tolerance_decentrage_px"),
        )


# ---------------------------------------------------------------------------
# AlignmentConfig
# ---------------------------------------------------------------------------

@dataclass
class AlignmentConfig:
    """
    Zone d ancrage pour le recalage dynamique (RobustAligner V3).

    Paramètres réglables depuis la recette :
      max_transl    : déplacement max accepté en pixels (défaut 20)
      search_margin : marge de recherche autour de l ancre en px (défaut 40)
      tm_threshold  : score minimum de corrélation (défaut 0.60)
      scale_min/max : plage de zoom testée (défaut 0.95-1.05)
      scale_steps   : nombre de niveaux de zoom (défaut 5)
      debug         : afficher les scores dans la console (défaut False)
    """

    use_alignment   : bool  = False
    x               : int   = 0
    y               : int   = 0
    width           : int   = 0
    height          : int   = 0
    anchor_center_y : float = 0.0

    # Paramètres RobustAligner V3 — tous optionnels
    max_transl      : float = 40.0
    search_margin   : float = 40.0
    tm_threshold    : float = 0.60
    scale_min       : float = 0.97
    scale_max       : float = 1.03
    scale_steps     : int   = 5
    debug           : bool  = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "use_alignment"  : self.use_alignment,
            "x"              : self.x,
            "y"              : self.y,
            "width"          : self.width,
            "height"         : self.height,
            "anchor_center_y": round(self.anchor_center_y, 2),
            "max_transl"     : self.max_transl,
            "search_margin"  : self.search_margin,
            "tm_threshold"   : self.tm_threshold,
            "scale_min"      : self.scale_min,
            "scale_max"      : self.scale_max,
            "scale_steps"    : self.scale_steps,
            "debug"          : self.debug,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AlignmentConfig":
        return cls(
            use_alignment   = d.get("use_alignment",  False),
            x               = d.get("x",              0),
            y               = d.get("y",              0),
            width           = d.get("width",           0),
            height          = d.get("height",          0),
            anchor_center_y = d.get("anchor_center_y", 0.0),
            max_transl      = d.get("max_transl",      40.0),
            search_margin   = d.get("search_margin",   40.0),
            tm_threshold    = d.get("tm_threshold",    0.60),
            scale_min       = d.get("scale_min",       0.95),
            scale_max       = d.get("scale_max",       1.05),
            scale_steps     = d.get("scale_steps",     5),
            debug           = d.get("debug",           False),
        )


# ---------------------------------------------------------------------------
# AcquisitionConfig
# ---------------------------------------------------------------------------

@dataclass
class AcquisitionConfig:
    """Paramètres d'acquisition pour un défaut donné."""

    mode          : str       = "unique"   # "unique" | "multiple"
    etage         : int       = 1
    angles_requis : List[int] = field(default_factory=lambda: [1])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode"         : self.mode,
            "etage"        : self.etage,
            "angles_requis": self.angles_requis,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AcquisitionConfig":
        return cls(
            mode          = d.get("mode", "unique"),
            etage         = d.get("etage", 1),
            angles_requis = d.get("angles_requis", [1]),
        )


# ---------------------------------------------------------------------------
# DefautConfig
# ---------------------------------------------------------------------------

@dataclass
class DefautConfig:
    """Bloc complet d'un défaut dans la recette."""

    id_defaut      : str
    label          : str
    severite       : str
    actif          : bool
    algorithme     : str
    acquisition    : AcquisitionConfig
    reference_image: str
    alignment      : AlignmentConfig
    rois           : List[ROIConfig]    = field(default_factory=list)
    verdict_fusion : Optional[Dict]    = None
    # Chantier 4 — source image pour l'analyse
    # False (défaut) : image d'angle du buffer RAM
    # True           : image fusionnée (panorama) téléchargée depuis MinIO
    # Applicable uniquement au service colorimetrique
    use_fused_image: bool              = False

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id_defaut"      : self.id_defaut,
            "label"          : self.label,
            "severite"       : self.severite,
            "actif"          : self.actif,
            "algorithme"     : self.algorithme,
            "acquisition"    : self.acquisition.to_dict(),
            "reference_image": self.reference_image,
            "alignment"      : self.alignment.to_dict(),
            "rois"           : [r.to_dict() for r in self.rois],
            "use_fused_image": self.use_fused_image,
        }
        if self.verdict_fusion:
            d["verdict_fusion"] = self.verdict_fusion
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DefautConfig":
        return cls(
            id_defaut       = d["id_defaut"],
            label           = d["label"],
            severite        = d["severite"],
            actif           = d.get("actif", True),
            algorithme      = d["algorithme"],
            acquisition     = AcquisitionConfig.from_dict(d.get("acquisition", {})),
            reference_image = d.get("reference_image", ""),
            alignment       = AlignmentConfig.from_dict(d.get("alignment", {})),
            rois            = [ROIConfig.from_dict(r) for r in d.get("rois", [])],
            verdict_fusion  = d.get("verdict_fusion"),
            use_fused_image = d.get("use_fused_image", False),
        )

    @classmethod
    def nouveau(cls, id_defaut: str, service: str) -> "DefautConfig":
        """Crée un bloc défaut vide à partir de son ID."""
        meta = DEFAUTS_PAR_SERVICE[service][id_defaut]
        return cls(
            id_defaut       = id_defaut,
            label           = meta["label"],
            severite        = meta["severite"],
            actif           = True,
            algorithme      = meta["algorithme"],
            acquisition     = AcquisitionConfig(),
            reference_image = "",
            alignment       = AlignmentConfig(),
            rois            = [],
        )


# ---------------------------------------------------------------------------
# CalibrationGlobale
# ---------------------------------------------------------------------------

@dataclass
class CalibrationGlobale:
    pixels_per_mm : float = 1.0
    clahe_clip    : float = 2.5
    clahe_tile    : int   = 8

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pixels_per_mm": self.pixels_per_mm,
            "clahe_clip"   : self.clahe_clip,
            "clahe_tile"   : self.clahe_tile,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CalibrationGlobale":
        return cls(
            pixels_per_mm = d.get("pixels_per_mm", 1.0),
            clahe_clip    = d.get("clahe_clip", 2.5),
            clahe_tile    = d.get("clahe_tile", 8),
        )


# ---------------------------------------------------------------------------
# RecetteConfig  (racine du JSON)
# ---------------------------------------------------------------------------

@dataclass
class RecetteConfig:
    """Recette complète d'un type de bouteille pour un service donné."""

    type_bouteille     : str
    description        : str
    service            : str
    version            : int
    created_at         : str
    calibration_globale: CalibrationGlobale
    defauts            : List[DefautConfig] = field(default_factory=list)

    # ---- accès rapide par id_defaut ----
    def get_defaut(self, id_defaut: str) -> Optional[DefautConfig]:
        for d in self.defauts:
            if d.id_defaut == id_defaut:
                return d
        return None

    def set_defaut(self, defaut: DefautConfig):
        """Remplace ou ajoute un bloc défaut."""
        for i, d in enumerate(self.defauts):
            if d.id_defaut == defaut.id_defaut:
                self.defauts[i] = defaut
                return
        self.defauts.append(defaut)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type_bouteille"     : self.type_bouteille,
            "description"        : self.description,
            "service"            : self.service,
            "version"            : self.version,
            "created_at"         : self.created_at,
            "calibration_globale": self.calibration_globale.to_dict(),
            "defauts"            : [d.to_dict() for d in self.defauts],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RecetteConfig":
        return cls(
            type_bouteille      = d["type_bouteille"],
            description         = d.get("description", ""),
            service             = d["service"],
            version             = d.get("version", 1),
            created_at          = d.get("created_at", ""),
            calibration_globale = CalibrationGlobale.from_dict(
                                    d.get("calibration_globale", {})),
            defauts             = [DefautConfig.from_dict(x)
                                   for x in d.get("defauts", [])]
        )

    @classmethod
    def nouvelle(cls, type_bouteille: str, description: str,
                 service: str) -> "RecetteConfig":
        """Crée une recette vide version 1."""
        from datetime import datetime
        return cls(
            type_bouteille      = type_bouteille,
            description         = description,
            service             = service,
            version             = 1,
            created_at          = datetime.now().isoformat(),
            calibration_globale = CalibrationGlobale(),
            defauts             = [],
        )