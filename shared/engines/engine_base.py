"""
engine_base.py
--------------
Structures de données, RobustAligner V3 et EngineBase.

RobustAligner V3 — corrections v2 :
  - Recherche restreinte à une zone autour de la position attendue
    (élimine les faux positifs sur toute l'image)
  - MAX_TRANSL et SEARCH_MARGIN configurables par recette
  - Validation de cohérence : le match doit être proche de la position attendue
  - Debug optionnel : affiche le score et la position trouvée
  - Template size check : avertit si la zone d'ancrage est trop petite
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import numpy as np
import cv2

from shared.core.models import DefautConfig, ROIConfig


# ---------------------------------------------------------------------------
# Structures de résultat
# ---------------------------------------------------------------------------

@dataclass
class ROIResult:
    roi_name  : str
    roi_type  : str
    status    : str
    mesure    : float
    reference : float
    tolerance : tuple
    ecart     : float
    details   : Dict[str, Any]
    steps     : Dict[str, np.ndarray] = field(default_factory=dict)
    roi_rect  : tuple = (0, 0, 0, 0)


@dataclass
class InspectionReport:
    id_defaut       : str
    label           : str
    algorithme      : str
    status_global   : str
    roi_results     : List[ROIResult]
    image_originale : np.ndarray
    match_info      : Optional[Dict] = None

    @property
    def is_ok(self) -> bool:
        return self.status_global == "OK"

    def get_all_steps(self) -> Dict[str, np.ndarray]:
        all_steps = {}
        for roi_res in self.roi_results:
            for name, img in roi_res.steps.items():
                all_steps[f"[{roi_res.roi_name}] {name}"] = img
        return all_steps


# ---------------------------------------------------------------------------
# RobustAligner V3
# ---------------------------------------------------------------------------

class RobustAligner:
    """
    Recalage par Template Matching multi-échelle (MSTM) + CLAHE.

    RÔLE : trouver le décalage (dx, dy) de la bouteille par rapport
    à sa position de référence. Le scale sert UNIQUEMENT à améliorer
    la robustesse du matching — il ne doit PAS être utilisé pour
    corriger les mesures métriques (distance, largeur, aire).

    Raison : TM_CCOEFF_NORMED retourne des scores élevés même pour
    des templates très redimensionnés (texture locale suffisante).
    Le scale "gagnant" n'est donc pas une mesure fiable du zoom réel
    de l'objet — c'est juste le scale qui maximise la corrélation locale.

    Paramètres configurables (via align_cfg) :
      max_transl    : déplacement max autorisé en px (défaut 20)
      search_margin : marge autour de la zone ancre en px (défaut 40)
      tm_threshold  : score minimum pour accepter le match (défaut 0.60)
      scale_min     : zoom minimum testé (défaut 0.95) — rester proche de 1.0
      scale_max     : zoom maximum testé (défaut 1.05) — rester proche de 1.0
      scale_steps   : nombre de niveaux de zoom (défaut 3)
      debug         : True pour afficher les scores dans la console
    """

    # ── Valeurs par défaut — toutes surchargeables par recette ─────────
    # IMPORTANT : garder scale_min/max proche de 1.0 (±5% max)
    # Une plage trop large (ex 0.5-1.5) rend le scale non fiable
    # car TM_CCOEFF_NORMED favorise les petits templates (plus de matches locaux)
    DEFAULT_SCALE_MIN    =  0.97
    DEFAULT_SCALE_MAX    =  1.03
    DEFAULT_SCALE_STEPS  =  3        # 3 niveaux suffisent : min, 1.0, max
    DEFAULT_MAX_TRANSL   =  40       # px — déplacement max accepté
    DEFAULT_SEARCH_MARGIN=  40       # px de marge autour de la zone ancre
    DEFAULT_TM_THRESHOLD =  0.60     # seuil acceptation
    DEFAULT_DEBUG        =  False

    def __init__(self, reference_img: np.ndarray, align_cfg: dict):
        self.ax  = int(align_cfg["x"])
        self.ay  = int(align_cfg["y"])
        self.aw  = int(align_cfg["width"])
        self.ah  = int(align_cfg["height"])
        self.anchor_cy_ref = float(align_cfg.get(
            "anchor_center_y", self.ay + self.ah / 2.0
        ))

        # Paramètres configurables depuis la recette
        self.max_transl    = float(align_cfg.get("max_transl",     self.DEFAULT_MAX_TRANSL))
        self.search_margin = float(align_cfg.get("search_margin",  self.DEFAULT_SEARCH_MARGIN))
        self.tm_threshold  = float(align_cfg.get("tm_threshold",   self.DEFAULT_TM_THRESHOLD))
        self.debug         = bool(align_cfg.get("debug",           self.DEFAULT_DEBUG))

        scale_min   = float(align_cfg.get("scale_min",   self.DEFAULT_SCALE_MIN))
        scale_max   = float(align_cfg.get("scale_max",   self.DEFAULT_SCALE_MAX))
        scale_steps = int(align_cfg.get("scale_steps",   self.DEFAULT_SCALE_STEPS))
        self.scale_range = np.linspace(scale_min, scale_max, scale_steps)

        # CLAHE
        self.clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))

        # Extraction template depuis l'image de référence
        ref_gray = self._to_gray(reference_img)
        ref_eq   = self.clahe.apply(ref_gray)
        self.template = ref_eq[self.ay: self.ay + self.ah,
                                self.ax: self.ax + self.aw].copy()

        # Avertissement si template trop petit
        th, tw = self.template.shape[:2]
        if tw < 20 or th < 10:
            print(f"  [Aligner] ⚠️  Zone ancre petite ({tw}×{th}px) "
                  f"→ risque de faux positifs. Agrandir la zone dans la config.")
        else:
            print(f"  [Aligner] ✅ Template {tw}×{th}px | "
                  f"max_transl={self.max_transl}px | "
                  f"search_margin={self.search_margin}px | "
                  f"threshold={self.tm_threshold}")

    # ------------------------------------------------------------------

    def _to_gray(self, img: np.ndarray) -> np.ndarray:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) \
               if len(img.shape) == 3 else img.copy()

    def _null_result(self, score: float = 0.0, raison: str = "") -> dict:
        if self.debug:
            print(f"  [Aligner] NULL → {raison} (score={score:.3f})")
        return {
            "method"               : "NONE",
            "dx"                   : 0,
            "dy"                   : 0,
            "scale"                : 1.0,
            "score"                : score,
            "loc"                  : (self.ax, self.ay),
            "anchor_center_y_current": self.anchor_cy_ref,
            "raison"               : raison,
        }

    def _subpixel_refine(self, res_map: np.ndarray,
                          loc: tuple) -> tuple:
        """Raffinement parabolique sous-pixel (±0.5px max)."""
        x, y = int(loc[0]), int(loc[1])
        h, w = res_map.shape
        x = max(1, min(x, w - 2))
        y = max(1, min(y, h - 2))

        dx_num = res_map[y, x+1] - res_map[y, x-1]
        dx_den = 2.0 * (2*res_map[y,x] - res_map[y,x-1] - res_map[y,x+1])
        dx_sub = float(dx_num / dx_den) if abs(dx_den) > 1e-6 else 0.0

        dy_num = res_map[y+1, x] - res_map[y-1, x]
        dy_den = 2.0 * (2*res_map[y,x] - res_map[y-1,x] - res_map[y+1,x])
        dy_sub = float(dy_num / dy_den) if abs(dy_den) > 1e-6 else 0.0

        dx_sub = max(-0.5, min(0.5, dx_sub))
        dy_sub = max(-0.5, min(0.5, dy_sub))
        return x + dx_sub, y + dy_sub

    def calculate_offset(self, current_img: np.ndarray) -> dict:
        """
        Calcule le décalage (dx, dy) entre l'image de référence et l'image courante.

        Stratégie V3 :
          1. Zone de recherche restreinte = zone ancre ± search_margin
             → évite les faux positifs sur des zones similaires ailleurs
          2. Si le meilleur match est hors de max_transl → NULL
          3. Si le score < tm_threshold → NULL
          4. Sinon → offset valide
        """
        gray = self._to_gray(current_img)
        eq   = self.clahe.apply(gray)
        H, W = eq.shape

        th, tw = self.template.shape[:2]

        # ── Zone de recherche restreinte ──────────────────────────────
        # On cherche uniquement dans une fenêtre autour de la position
        # de référence, pas dans toute l'image
        margin = int(self.search_margin)
        sx1 = max(0, self.ax - margin)
        sy1 = max(0, self.ay - margin)
        sx2 = min(W, self.ax + self.aw + margin)
        sy2 = min(H, self.ay + self.ah + margin)

        search_zone = eq[sy1:sy2, sx1:sx2]
        sz_h, sz_w  = search_zone.shape

        # Vérification que la zone de recherche est assez grande
        if sz_w < tw + 2 or sz_h < th + 2:
            return self._null_result(0.0,
                "Zone de recherche trop petite — agrandir search_margin")

        best_score = -1.0
        best_loc   = (0, 0)
        best_scale = 1.0
        best_map   = None

        for s in self.scale_range:
            nw = max(4, int(tw * s))
            nh = max(4, int(th * s))

            # Template redimensionné doit tenir dans la zone de recherche
            if nh >= sz_h or nw >= sz_w:
                continue

            interp = cv2.INTER_AREA if s < 1.0 else cv2.INTER_LINEAR
            tpl    = cv2.resize(self.template, (nw, nh), interpolation=interp)

            try:
                res_map = cv2.matchTemplate(
                    search_zone, tpl, cv2.TM_CCOEFF_NORMED
                )
            except cv2.error:
                continue

            _, score, _, loc = cv2.minMaxLoc(res_map)
            if score > best_score:
                best_score = score
                best_loc   = loc
                best_scale = float(s)
                best_map   = res_map

        if self.debug:
            print(f"  [Aligner] score={best_score:.3f} | "
                  f"loc_in_zone={best_loc} | scale={best_scale:.3f}")

        # ── Vérification seuil de score ────────────────────────────────
        if best_score < self.tm_threshold or best_map is None:
            return self._null_result(best_score,
                f"Score {best_score:.3f} < seuil {self.tm_threshold}")

        # ── Raffinement sous-pixel ──────────────────────────────────────
        fx_zone, fy_zone = self._subpixel_refine(best_map, best_loc)

        # Reconversion en coordonnées image globale
        fx_global = fx_zone + sx1
        fy_global = fy_zone + sy1

        # Déplacement par rapport à la position de référence
        dx = fx_global - self.ax
        dy = fy_global - self.ay

        if self.debug:
            print(f"  [Aligner] dx={dx:+.2f}px | dy={dy:+.2f}px | "
                  f"max_transl={self.max_transl}px")

        # ── Vérification cohérence déplacement ─────────────────────────
        if abs(dx) > self.max_transl or abs(dy) > self.max_transl:
            return self._null_result(best_score,
                f"Déplacement hors limite: dx={dx:+.1f} dy={dy:+.1f} "
                f"(max={self.max_transl}px)")

        return {
            "method"               : "MSTM_V3",
            "dx"                   : round(dx, 2),
            "dy"                   : round(dy, 2),
            "scale"                : round(best_scale, 4),
            "score"                : round(best_score, 4),
            "loc"                  : (int(round(fx_global)),
                                      int(round(fy_global))),
            "anchor_center_y_current": round(self.anchor_cy_ref + dy, 2),
            "raison"               : "OK",
        }


# ---------------------------------------------------------------------------
# EngineBase
# ---------------------------------------------------------------------------

class EngineBase(ABC):

    def __init__(self, defaut: DefautConfig, ref_image: Optional[np.ndarray]):
        self._defaut  = defaut
        self._aligner : Optional[RobustAligner] = None

        if defaut.alignment.use_alignment and ref_image is not None:
            try:
                # Passer tous les champs de AlignmentConfig comme dict
                cfg = defaut.alignment.__dict__.copy()
                self._aligner = RobustAligner(ref_image, cfg)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"  ⚠️ Recalage non initialisé : {e}")

    def inspect(self, image: np.ndarray) -> InspectionReport:
        h_img, w_img = image.shape[:2]

        match_info = None
        dx, dy     = 0.0, 0.0
        anchor_cy  = (self._defaut.alignment.anchor_center_y
                      if self._defaut.alignment.use_alignment else 0.0)

        if self._aligner is not None:
            result    = self._aligner.calculate_offset(image)
            match_info= result

            if result["method"] != "NONE":
                dx        = result["dx"]
                dy        = result["dy"]
                anchor_cy = result["anchor_center_y_current"]
                # Log systématique du recalage — toujours visible
                print(
                    f"  [Recalage {self._defaut.id_defaut}] "
                    f"OK | score={result['score']:.3f} | "
                    f"scale={result['scale']:.4f} | "
                    f"dx={result['dx']:+.2f}px | "
                    f"dy={result['dy']:+.2f}px | "
                    f"anchor_cy={result['anchor_center_y_current']:.2f}"
                )
            else:
                print(
                    f"  [Recalage {self._defaut.id_defaut}] "
                    f"NULL | score={result.get('score',0):.3f} | "
                    f"raison={result.get('raison','?')}"
                )

        # Le scale MSTM n'est pas fiable comme mesure de zoom réel
        # (TM_CCOEFF_NORMED favorise les petits templates → biais vers scale bas)
        # On passe scale=1.0 aux engines : pas de correction métrique par scale.
        # La robustesse vient des tolérances calibrées sur image de référence.
        scale = 1.0
        # Info : scale MSTM disponible dans match_info["scale"] pour diagnostic
        # mais ne doit pas corriger les mesures.

        roi_results: List[ROIResult] = []
        for roi_cfg in self._defaut.rois:
            x = max(0, min(int(roi_cfg.x + dx), w_img - 1))
            y = max(0, min(int(roi_cfg.y + dy), h_img - 1))
            w = min(roi_cfg.width,  w_img - x)
            h = min(roi_cfg.height, h_img - y)

            roi_img = image[y:y+h, x:x+w]
            if roi_img.size == 0:
                continue
            try:
                result = self._inspect_roi(
                    roi_img, roi_cfg, anchor_cy, y, scale
                )
                result.roi_rect = (x, y, w, h)
                roi_results.append(result)
            except Exception as e:
                import traceback
                traceback.print_exc()
                roi_results.append(ROIResult(
                    roi_name=roi_cfg.name, roi_type=roi_cfg.type,
                    status="NG", mesure=0.0, reference=0.0,
                    tolerance=(0.0, 0.0), ecart=0.0,
                    details={"error": str(e), "scale": scale},
                    steps={"Erreur": roi_img},
                    roi_rect=(x, y, w, h),
                ))

        status_global = (
            "OK" if roi_results and all(r.status == "OK" for r in roi_results)
            else "NG"
        )
        return InspectionReport(
            id_defaut       = self._defaut.id_defaut,
            label           = self._defaut.label,
            algorithme      = self._defaut.algorithme,
            status_global   = status_global,
            roi_results     = roi_results,
            image_originale = image,
            match_info      = match_info,
        )

    @abstractmethod
    def _inspect_roi(
        self,
        roi_img      : np.ndarray,
        roi_cfg      : ROIConfig,
        anchor_cy    : float,
        roi_y_global : int,
        scale        : float = 1.0,   # facteur d'échelle MSTM pour correction mesures
    ) -> ROIResult:
        ...


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_engine(defaut: DefautConfig,
                  ref_image: Optional[np.ndarray]) -> EngineBase:
    from shared.engines.engine_colorimetrique  import EngineColorimetrique
    from shared.engines.engine_gradient        import EngineGradient
    from shared.engines.engine_geometrique     import EngineGeometrique
    from shared.engines.engine_check_position  import EngineCheckPosition

    algo = defaut.algorithme
    if algo == "presence_hsv":
        return EngineColorimetrique(defaut, ref_image)
    elif algo == "niveau_sobel":
        return EngineGradient(defaut, ref_image)
    elif algo in ("profil_canny", "derive_centre"):
        return EngineGeometrique(defaut, ref_image)
    elif algo == "symmetry_canny":
        return EngineCheckPosition(defaut, ref_image)
    else:
        raise ValueError(f"Algorithme inconnu : '{algo}'")