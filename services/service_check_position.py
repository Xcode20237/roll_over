"""
service_check_position.py
-------------------------
Service de production headless — vérification du positionnement bouteille.

Défaut couvert :
  CP1.1 — Mauvais positionnement bouteille (symmetry_canny)

Rôle dans l'architecture :
  - Reçoit les images de l'étage de référence (étage 1 par défaut)
  - Analyse l'axe de symétrie de la bouteille sur chaque image
  - Publie UN SEUL verdict (OK/NG) sur TOPIC_SORTIE_CHECK_POSITION
  - Si OK : inclut l'écart_px moyen dans le payload → utilisé par service_fusion
  - Si NG : tous les autres services vident leur buffer pour cette bouteille

Topics MQTT :
  Entrée : vision/check/entree
  Sortie : vision/check/position
"""

import os
from dotenv import load_dotenv
load_dotenv()

from service_base import ServiceBase


class ServiceCheckPosition(ServiceBase):

    SERVICE_NAME = "check_position"
    TOPIC_ENTREE = os.getenv("TOPIC_ENTREE_CHECK_POSITION",
                             "vision/check/entree")
    TOPIC_SORTIE = os.getenv("TOPIC_SORTIE_CHECK_POSITION",
                             "vision/check/position")

    def _build_check_payload(self, id_obj: str, type_btl: str,
                              verdict_global: str,
                              verdicts_defauts: list) -> dict:
        """
        Surcharge du payload de sortie pour inclure l'écart_px moyen
        (nécessaire pour le recadrage asymétrique dans service_fusion).
        """
        payload = super()._build_base_payload(
            id_obj, type_btl, verdict_global, verdicts_defauts
        )

        # Extraire l'écart_px depuis les détails du premier ROI
        # — valeur signée utilisée par service_fusion pour le recadrage
        ecart_px = 0.0
        for d in verdicts_defauts:
            for roi in d.get("details", []):
                if isinstance(roi, dict) and "ecart" in roi:
                    ecart_px = float(roi.get("ecart", 0.0))
                    break

        payload["ecart_position_px"] = round(ecart_px, 2)
        return payload


if __name__ == "__main__":
    print("=" * 60)
    print("SERVICE CHECK POSITION — Vérification positionnement bouteille")
    print("Défaut : CP1.1")
    print("=" * 60)
    ServiceCheckPosition().run()
