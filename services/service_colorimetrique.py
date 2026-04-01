"""
service_colorimetrique.py
-------------------------
Service de production headless — famille colorimetrique.

Defauts couverts :
  D3.1 — Bouchon manquant          (presence_hsv)
  D3.2 — Bouchon de travers        (orientation_masque)  ← migré depuis gradient
  D3.3 — Bague inviolabilite        (presence_hsv)
  D2.4 — Mousse excessive           (presence_hsv)
  D4.1 — Fuites parois              (presence_hsv)
  D4.4 — Absence de marquage        (presence_hsv)

Chantier 4 — Image fusionnée :
  Si un ROI a use_fused_image=True, le service télécharge l'image fusionnée
  depuis MinIO (chemin stocké dans le buffer à la réception du message
  vision/ia/ready) au lieu d'utiliser l'image d'angle du buffer RAM.

Topics MQTT :
  Entrée : vision/classique/colorimetrique
  Entrée fusion : vision/ia/ready  (pour récupérer le chemin du panorama)
  Sortie : vision/resultats/colorimetrique
"""

import os
import json
import time
import threading
from datetime import datetime, timezone
from typing import Dict, Optional, Any

import cv2
import numpy as np
import paho.mqtt.client as mqtt
from minio import Minio
from dotenv import load_dotenv

load_dotenv()

from service_base import ServiceBase
from shared.core.models import RecetteConfig, DefautConfig
from shared.engines.engine_base import create_engine, InspectionReport

# Topic fusion — pour récupérer le chemin de l'image fusionnée
TOPIC_FUSION_READY = os.getenv("TOPIC_SORTIE_FUSION", "vision/ia/ready")
MINIO_ENDPOINT     = os.getenv("MINIO_ENDPOINT",  "localhost:9000")
MINIO_USER         = os.getenv("MINIO_USER",       "admin_vision")
MINIO_PASS         = os.getenv("MINIO_PASSWORD",   "password123")
BUCKET_NAME        = os.getenv("MINIO_BUCKET",     "images-production")


class ServiceColorimetrique(ServiceBase):

    SERVICE_NAME = "colorimetrique"
    TOPIC_ENTREE = os.getenv("TOPIC_ENTREE_COLORIMETRIQUE",
                             "vision/classique/colorimetrique")
    TOPIC_SORTIE = os.getenv("TOPIC_SORTIE_COLORIMETRIQUE",
                             "vision/resultats/colorimetrique")

    def __init__(self):
        super().__init__()
        # Cache des images fusionnées par id_bouteille
        # { id_bouteille: {"chemin": str, "image": np.ndarray | None} }
        self._fused_cache     : Dict[str, Dict[str, Any]] = {}
        self._fused_cache_lock = threading.Lock()

        # Client MinIO dédié pour téléchargement images fusionnées
        try:
            self._minio_fused = Minio(
                MINIO_ENDPOINT,
                access_key=MINIO_USER,
                secret_key=MINIO_PASS,
                secure=False,
            )
        except Exception as e:
            print(f"[colorimetrique] Erreur init MinIO fused : {e}")
            self._minio_fused = None

    # ------------------------------------------------------------------
    # Abonnement supplémentaire au topic fusion
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc):
        super()._on_connect(client, userdata, flags, rc)
        # S'abonner aussi au topic fusion pour stocker le chemin du panorama
        client.subscribe(TOPIC_FUSION_READY)
        print(f"[colorimetrique] Écoute image fusionnée : {TOPIC_FUSION_READY}")

    # ------------------------------------------------------------------
    # Surcharge _on_message pour intercepter le message fusion
    # ------------------------------------------------------------------

    def _on_message(self, client, userdata, msg):
        if msg.topic == TOPIC_FUSION_READY:
            self._on_fusion_ready(msg)
            return
        # Traitement normal (images d'angle)
        super()._on_message(client, userdata, msg)

    def _on_fusion_ready(self, msg):
        """
        Reçoit le message vision/ia/ready publié par service_fusion.
        Stocke le chemin dans le cache et marque fusion_ready=True dans le buffer.
        Déclenche l'inspection si check_position est déjà OK et tout est complet.
        """
        try:
            payload      = json.loads(msg.payload.decode())
            id_obj_raw   = payload.get("id_objet", "")
            id_bouteille = id_obj_raw.replace("BTL_", "") if id_obj_raw \
                           else str(payload.get("id_bouteille", "?"))
            chemin       = payload.get("chemin_image_fusionnee", "")

            chemin_propre = chemin.lstrip("/")
            if chemin_propre.startswith(BUCKET_NAME + "/"):
                chemin_propre = chemin_propre[len(BUCKET_NAME) + 1:]

            with self._fused_cache_lock:
                self._fused_cache[id_bouteille] = {
                    "chemin": chemin_propre,
                    "image" : None,
                    "ts"    : time.time(),
                }
            print(f"[colorimetrique] Image fusionnée disponible → "
                  f"{id_bouteille} : {chemin_propre}")

            # Marquer fusion_ready dans le buffer et vérifier complétion
            all_done = False
            with self._buffer_lock:
                if id_bouteille not in self._buffer:
                    # Buffer pas encore créé — mémoriser dans cache suffit
                    # fusion_ready sera mis à True lors de _init_buffer_entry
                    print(f"[colorimetrique] [{id_bouteille}] fusion reçue avant images "
                          f"— mémorisée dans cache")
                    return

                entry = self._buffer[id_bouteille]
                entry["fusion_ready"] = True

                if not entry.get("defauts"):
                    # Sentinelle sans défauts — images pas encore arrivées
                    print(f"[colorimetrique] [{id_bouteille}] fusion reçue "
                          f"— sentinelle, en attente images")
                    return

                print(f"[colorimetrique] [{id_bouteille}] fusion_ready=True "
                      f"— vérification buffer...")
                self._log_buffer_state(id_bouteille)
                all_done = self._check_all_complete(id_bouteille)

            if all_done:
                self._execute_inspection(id_bouteille)

        except Exception as e:
            print(f"[colorimetrique] Erreur réception fusion : {e}")

    # ------------------------------------------------------------------
    # Téléchargement image fusionnée à la demande
    # ------------------------------------------------------------------

    def _get_fused_image(self, id_bouteille: str) -> Optional[np.ndarray]:
        """
        Retourne l'image fusionnée pour cet id_bouteille.
        La télécharge depuis MinIO si pas encore en cache.
        Retourne None si indisponible.
        """
        with self._fused_cache_lock:
            entry = self._fused_cache.get(id_bouteille)

        if entry is None:
            print(f"[colorimetrique] Image fusionnée non disponible "
                  f"pour {id_bouteille}")
            return None

        # Déjà téléchargée
        if entry["image"] is not None:
            return entry["image"]

        # Téléchargement depuis MinIO
        if self._minio_fused is None:
            return None
        try:
            resp     = self._minio_fused.get_object(BUCKET_NAME, entry["chemin"])
            img_data = resp.read()
            resp.close()
            resp.release_conn()

            img = cv2.imdecode(
                np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR
            )
            if img is not None:
                with self._fused_cache_lock:
                    self._fused_cache[id_bouteille]["image"] = img
                print(f"[colorimetrique] Image fusionnée téléchargée → "
                      f"{id_bouteille} ({img.shape[1]}×{img.shape[0]})")
            return img

        except Exception as e:
            print(f"[colorimetrique] Erreur téléchargement image fusionnée "
                  f"{id_bouteille} : {e}")
            return None

    # ------------------------------------------------------------------
    # Surcharge _execute_inspection pour injecter l'image fusionnée
    # ------------------------------------------------------------------

    def _execute_inspection(self, id_obj: str, is_timeout: bool = False):
        """
        Surcharge de _execute_inspection pour remplacer l'image d'angle
        par l'image fusionnée pour les ROIs qui ont use_fused_image=True.
        """
        with self._buffer_lock:
            entry = self._buffer.pop(id_obj, None)
        if entry is None:
            return

        type_btl         = entry["type"]
        verdicts_defauts = []
        verdict_global   = "OK"

        if is_timeout:
            verdict_global = "NG"
            for ddata in entry["defauts"].values():
                defaut: DefautConfig = ddata["defaut"]
                verdicts_defauts.append({
                    "id_defaut": defaut.id_defaut,
                    "label"    : defaut.label,
                    "verdict"  : "NG",
                    "mesure"   : None,
                    "reference": None,
                    "tolerance": None,
                    "ecart"    : None,
                    "details"  : [{"error": "TIMEOUT_IMAGES_MANQUANTES"}],
                })
        else:
            # Charger l'image fusionnée une seule fois (si nécessaire)
            fused_img : Optional[np.ndarray] = None
            needs_fused = any(
                getattr(ddata["defaut"], "use_fused_image", False)
                for ddata in entry["defauts"].values()
            )
            if needs_fused:
                fused_img = self._get_fused_image(id_obj)
                if fused_img is None:
                    print(f"[colorimetrique] ⚠️ [{id_obj}] "
                          f"Image fusionnée demandée mais indisponible — "
                          f"utilisation de l'image d'angle à la place")

            for did, ddata in entry["defauts"].items():
                defaut  : DefautConfig = ddata["defaut"]
                ref_img = self._get_ref_image(type_btl, defaut)

                try:
                    engine = create_engine(defaut, ref_img)

                    all_roi_results = []
                    last_report     = None

                    for angle_img in sorted(ddata["images"].keys()):
                        # Choisir l'image selon use_fused_image du défaut
                        img_to_inspect = ddata["images"][angle_img]
                        if getattr(defaut, "use_fused_image", False) \
                                and fused_img is not None:
                            img_to_inspect = fused_img

                        report: InspectionReport = engine.inspect(img_to_inspect)
                        all_roi_results.extend(report.roi_results)
                        last_report = report

                    defaut_status = "OK" if all(
                        r.status == "OK" for r in all_roi_results
                    ) else "NG"

                    if defaut_status == "NG":
                        verdict_global = "NG"

                    verdicts_defauts.append(
                        self._build_defaut_verdict(defaut, defaut_status, last_report)
                    )

                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    verdict_global = "NG"
                    verdicts_defauts.append({
                        "id_defaut": did,
                        "label"    : defaut.label,
                        "verdict"  : "NG",
                        "mesure"   : None,
                        "reference": None,
                        "tolerance": None,
                        "ecart"    : None,
                        "details"  : [{"error": str(e)}],
                    })

        # Nettoyage cache fusionné pour cette bouteille
        with self._fused_cache_lock:
            self._fused_cache.pop(id_obj, None)

        output = {
            "id_bouteille"  : id_obj,
            "type_bouteille": type_btl,
            "service"       : self.SERVICE_NAME,
            "verdict_global": verdict_global,
            "timestamp"     : datetime.now(timezone.utc)
                              .isoformat().replace("+00:00", "Z"),
            "defauts"       : verdicts_defauts,
        }
        self._mqtt.publish(self.TOPIC_SORTIE,
                           json.dumps(output, ensure_ascii=False))
        print(f"[colorimetrique] {id_obj} ({type_btl}) "
              f"-> {verdict_global} | {len(verdicts_defauts)} defaut(s)")


if __name__ == "__main__":
    print("=" * 60)
    print("SERVICE COLORIMETRIQUE — Inspection HSV + Orientation")
    print("Defauts : D3.1, D3.2, D3.3, D2.4, D4.1, D4.4")
    print("=" * 60)
    ServiceColorimetrique().run()