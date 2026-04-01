"""
service_geometrique.py
----------------------
Service de production headless — famille geometrique.

Defauts couverts :
  D1.4 — Deformation corps          (profil_canny)
  D1.5 — Col tordu                  (derive_centre)
  D4.2 — Etiquette mal centree      (profil_canny)

Topics MQTT :
  Entree : vision/classique/geometrique
  Sortie : vision/resultats/geometrique
"""

import os
from dotenv import load_dotenv
load_dotenv()

from service_base import ServiceBase


class ServiceGeometrique(ServiceBase):

    SERVICE_NAME = "geometrique"
    TOPIC_ENTREE = os.getenv("TOPIC_ENTREE_GEOMETRIQUE",
                             "vision/classique/geometrique")
    TOPIC_SORTIE = os.getenv("TOPIC_SORTIE_GEOMETRIQUE",
                             "vision/resultats/geometrique")


if __name__ == "__main__":
    print("=" * 60)
    print("SERVICE GEOMETRIQUE — Inspection par contours Canny")
    print("Defauts : D1.4, D1.5, D4.2")
    print("=" * 60)
    ServiceGeometrique().run()
