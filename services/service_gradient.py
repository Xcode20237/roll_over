"""
service_gradient.py
-------------------
Service de production headless — famille gradient.

Defauts couverts :
  D2.1 — Sous-remplissage           (niveau_sobel)
  D2.2 — Sur-remplissage            (niveau_sobel)
  D3.2 — Bouchon de travers         (niveau_sobel)

Topics MQTT :
  Entree : vision/classique/gradient
  Sortie : vision/resultats/gradient
"""

import os
from dotenv import load_dotenv
load_dotenv()

from service_base import ServiceBase


class ServiceGradient(ServiceBase):

    SERVICE_NAME = "gradient"
    TOPIC_ENTREE = os.getenv("TOPIC_ENTREE_GRADIENT",
                             "vision/classique/gradient")
    TOPIC_SORTIE = os.getenv("TOPIC_SORTIE_GRADIENT",
                             "vision/resultats/gradient")


if __name__ == "__main__":
    print("=" * 60)
    print("SERVICE GRADIENT — Inspection par mesure Sobel Y")
    print("Defauts : D2.1, D2.2, D3.2")
    print("=" * 60)
    ServiceGradient().run()
