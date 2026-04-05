"""
service_base.py
---------------
Classe de base commune aux 3 micro-services d'inspection headless.

Architecture :
  - Écoute MQTT sur un topic entrant (vision/classique/<service>)
  - Télécharge les images depuis MinIO en RAM
  - Accumule les images dans un Buffer RAM par bouteille ET par défaut
  - Déclenche l'inspection quand tous les défauts actifs sont complets
  - Publie UN seul payload MQTT vers vision/resultats/<service>
  - Garbage Collector : timeout → forçage NG

Buffer structure :
  {
    "BTL_001": {
      "type"     : "Type_A",
      "timestamp": float,
      "defauts"  : {
        "D3.1": {
          "defaut"       : DefautConfig,
          "etage"        : 2,
          "angles_requis": [1, 3, 5, 7],
          "images"       : {1: np.ndarray, 3: np.ndarray},
          "complet"      : False,
        },
      }
    }
  }
"""

from __future__ import annotations
import os
import json
import time
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import cv2
import numpy as np
import paho.mqtt.client as mqtt
from minio import Minio
from dotenv import load_dotenv

from shared.core.models import RecetteConfig, DefautConfig
from shared.core.recipe_manager import load_active, get_ref_image_path
from shared.engines.engine_base import create_engine, InspectionReport

load_dotenv()

MQTT_BROKER        = os.getenv("MQTT_BROKER_HOST",        "localhost")
MQTT_PORT          = int(os.getenv("MQTT_BROKER_PORT",     1883))
MINIO_ENDPOINT     = os.getenv("MINIO_ENDPOINT",           "localhost:9000")
MINIO_USER         = os.getenv("MINIO_USER",               "admin_vision")
MINIO_PASS         = os.getenv("MINIO_PASSWORD",           "password123")
TIMEOUT_BUFFER     = float(os.getenv("TIMEOUT_BUFFER_SEC", 120.0))
HEARTBEAT_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL_SEC", 10.0))
BUCKET_NAME        = os.getenv("MINIO_BUCKET",         "production")
VISU_STEPS_PREFIX  = os.getenv("VISU_STEPS_PREFIX",    "visu_steps")

print(f"[service_base] TIMEOUT_BUFFER_SEC = {TIMEOUT_BUFFER}s")

# Topics visualisation temps réel — un dict indexé par SERVICE_NAME
_VISU_TOPICS_IMAGE = {
    "colorimetrique" : os.getenv("TOPIC_VISU_COLOR_IMAGE", "vision/visu/colorimetrique/image_brute"),
    "gradient"       : os.getenv("TOPIC_VISU_GRAD_IMAGE",  "vision/visu/gradient/image_brute"),
    "geometrique"    : os.getenv("TOPIC_VISU_GEO_IMAGE",   "vision/visu/geometrique/image_brute"),
    "check_position" : os.getenv("TOPIC_VISU_CHECK_IMAGE", "vision/visu/check_position/image_brute"),
}
_VISU_TOPICS_TRAIT = {
    "colorimetrique" : os.getenv("TOPIC_VISU_COLOR_TRAIT", "vision/visu/colorimetrique/traitement"),
    "gradient"       : os.getenv("TOPIC_VISU_GRAD_TRAIT",  "vision/visu/gradient/traitement"),
    "geometrique"    : os.getenv("TOPIC_VISU_GEO_TRAIT",   "vision/visu/geometrique/traitement"),
    "check_position" : os.getenv("TOPIC_VISU_CHECK_TRAIT", "vision/visu/check_position/traitement"),
}

# Topic check_position
TOPIC_CHECK_POSITION = os.getenv("TOPIC_SORTIE_CHECK_POSITION", "vision/check/position")
TOPIC_STATUS_BASE    = os.getenv("TOPIC_STATUS_BASE", "vision/status/")


class ServiceBase:

    SERVICE_NAME : str = ""
    TOPIC_ENTREE : str = ""
    TOPIC_SORTIE : str = ""
    CLIENT_ID    : str = ""

    def __init__(self):
        self._minio = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_USER,
            secret_key=MINIO_PASS,
            secure=False,
        )
        self._recettes_cache   : Dict[str, RecetteConfig]              = {}
        self._ref_images_cache : Dict[tuple, Optional[np.ndarray]]     = {}
        self._buffer           : Dict[str, Any]                        = {}
        self._buffer_lock      = threading.Lock()

        self._mqtt = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id=self.CLIENT_ID,
        )
        self._mqtt.on_connect = self._on_connect
        self._mqtt.on_message = self._on_message

        threading.Thread(target=self._garbage_collector,
                         daemon=True).start()
        threading.Thread(target=self._heartbeat,
                         daemon=True).start()

    # ------------------------------------------------------------------
    # Recette & images de référence
    # ------------------------------------------------------------------

    def _get_recette(self, type_btl: str) -> Optional[RecetteConfig]:
        if type_btl not in self._recettes_cache:
            recette = load_active(self.SERVICE_NAME, type_btl)
            if recette is None:
                print(f"[{self.SERVICE_NAME}] Recette introuvable : {type_btl}")
                return None
            self._recettes_cache[type_btl] = recette
            actifs = [d.id_defaut for d in recette.defauts if d.actif]
            print(f"[{self.SERVICE_NAME}] Recette chargee : {type_btl} "
                  f"| defauts actifs : {actifs}")
        return self._recettes_cache[type_btl]

    def _get_ref_image(self, type_btl: str,
                        defaut: DefautConfig) -> Optional[np.ndarray]:
        key = (type_btl, defaut.id_defaut)
        if key not in self._ref_images_cache:
            path = get_ref_image_path(
                self.SERVICE_NAME, type_btl, defaut.id_defaut
            )
            img = None
            if path and path.exists():
                img = cv2.imdecode(
                    np.fromfile(str(path), dtype=np.uint8),
                    cv2.IMREAD_COLOR,
                )
            self._ref_images_cache[key] = img
        return self._ref_images_cache[key]

    # ------------------------------------------------------------------
    # MQTT
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc):
        print(f"[{self.SERVICE_NAME}] Connecte | ecoute : {self.TOPIC_ENTREE}")
        client.subscribe(self.TOPIC_ENTREE)
        # Tous les services (sauf check_position lui-même) écoutent
        # le verdict de positionnement pour débloquer ou vider leur buffer
        if self.SERVICE_NAME != "check_position":
            client.subscribe(TOPIC_CHECK_POSITION)
            print(f"[{self.SERVICE_NAME}] Ecoute check_position : {TOPIC_CHECK_POSITION}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            topic   = msg.topic

            # ── Message check_position (verdict positionnement) ──────────
            if topic == TOPIC_CHECK_POSITION:
                self._on_check_position(payload)
                return

            # ── Message image normale ────────────────────────────────────
            id_obj   = str(payload["id_bouteille"])
            type_btl = payload.get("type_bouteille", "default")
            etage    = int(payload.get("etage", -1))
            angle    = int(payload.get("angle", -1))

            recette = self._get_recette(type_btl)
            if recette is None:
                return

            # Téléchargement image MinIO → RAM
            resp     = self._minio.get_object(
                payload["bucket"], payload["chemin_minio"]
            )
            img_data = resp.read()
            resp.close()
            resp.release_conn()

            img_array = cv2.imdecode(
                np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR
            )
            if img_array is None:
                print(f"[{self.SERVICE_NAME}] Image illisible : "
                      f"{payload['chemin_minio']}")
                return

            # Ecriture buffer + vérification complétion (section critique)
            with self._buffer_lock:
                self._init_buffer_entry(id_obj, type_btl, recette)

                # Vérifier que l'init n'a pas été bloquée par un check NG
                if not self._buffer.get(id_obj, {}).get("defauts"):
                    print(f"[{self.SERVICE_NAME}] [{id_obj}] image ignorée "
                          f"(E{etage}/A{angle}) — check NG ou buffer invalide")
                    return

                self._store_image(id_obj, etage, angle, img_array,
                                  payload.get("chemin_minio", ""))
                self._log_buffer_state(id_obj)
                all_done = self._check_all_complete(id_obj)

            # Déclenchement hors du lock
            if all_done:
                self._execute_inspection(id_obj)

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[{self.SERVICE_NAME}] Erreur message : {e}")

    # ------------------------------------------------------------------
    # Buffer
    # ------------------------------------------------------------------

    def _init_buffer_entry(self, id_obj: str, type_btl: str,
                            recette: RecetteConfig):
        # Si l'entrée existe déjà avec des défauts → déjà initialisée
        if id_obj in self._buffer and self._buffer[id_obj].get("defauts"):
            return

        # Récupérer le statut check_position mémorisé si sentinelle existante
        check_status = None
        check_ecart  = 0.0
        fusion_ready = False
        if id_obj in self._buffer:
            check_status = self._buffer[id_obj].get("check_position_status")
            check_ecart  = self._buffer[id_obj].get("check_ecart_px", 0.0)
            fusion_ready = self._buffer[id_obj].get("fusion_ready", False)
            # Si check NG déjà reçu → ne pas initialiser, ignorer cette bouteille
            if check_status == "NG":
                print(f"[{self.SERVICE_NAME}] [{id_obj}] check NG déjà reçu "
                      f"— image ignorée")
                return

        defauts_buffer = {}
        for defaut in recette.defauts:
            if not defaut.actif:
                continue
            est_fused = getattr(defaut, "use_fused_image", False)
            defauts_buffer[defaut.id_defaut] = {
                "defaut"       : defaut,
                "etage"        : defaut.acquisition.etage,
                "angles_requis": list(defaut.acquisition.angles_requis),
                "images"       : {},
                "complet"      : est_fused,
            }

        self._buffer[id_obj] = {
            "type"                  : type_btl,
            "timestamp"             : time.time(),
            "defauts"               : defauts_buffer,
            "check_position_status" : check_status,
            "check_ecart_px"        : check_ecart,
            "fusion_ready"          : fusion_ready,  # conservé depuis sentinelle
        }

        defauts_actifs = list(defauts_buffer.keys())
        print(f"[{self.SERVICE_NAME}] [{id_obj}] buffer initialisé | "
              f"défauts actifs: {defauts_actifs} | "
              f"check_status mémorisé: {check_status}")

    def _store_image(self, id_obj: str, etage: int, angle: int,
                      img: np.ndarray, chemin_minio_original: str = ""):
        """
        Stocke l'image dans le buffer et publie immédiatement un topic
        visualisation image_brute pour que le dashboard puisse remplacer
        le spinner par l'image réelle.
        """
        entry = self._buffer[id_obj]
        entry["timestamp"] = time.time()
        stockee = False

        for did, ddata in entry["defauts"].items():
            if ddata["complet"]:
                continue
            if ddata["etage"] == etage:
                ddata["images"][angle] = img
                # Mémoriser le chemin MinIO original pour le payload traitement
                if "chemins_bruts" not in ddata:
                    ddata["chemins_bruts"] = {}
                ddata["chemins_bruts"][angle] = chemin_minio_original
                stockee = True
                print(f"[{self.SERVICE_NAME}] [{id_obj}] image stockée "
                      f"E{etage}/A{angle} → défaut {did}")

                # Publish visualisation image_brute
                topic_visu = _VISU_TOPICS_IMAGE.get(self.SERVICE_NAME)
                if topic_visu and chemin_minio_original:
                    angles_recus = sorted(ddata["images"].keys())
                    payload_visu = {
                        "phase"           : "image_brute",
                        "id_bouteille"    : id_obj,
                        "type_bouteille"  : entry.get("type", "?"),
                        "service"         : self.SERVICE_NAME,
                        "id_defaut"       : did,
                        "label_defaut"    : ddata["defaut"].label,
                        "algo"            : ddata["defaut"].algorithme,
                        "etage"           : etage,
                        "angle"           : angle,
                        "angles_requis"   : ddata["angles_requis"],
                        "angles_recus"    : angles_recus,
                        "chemin_brute"    : chemin_minio_original,
                        "timestamp"       : datetime.now(timezone.utc)
                                            .isoformat().replace("+00:00", "Z"),
                    }
                    try:
                        self._mqtt.publish(topic_visu,
                                           json.dumps(payload_visu,
                                                       ensure_ascii=False))
                    except Exception as e:
                        print(f"[{self.SERVICE_NAME}] Erreur publish visu image: {e}")

        if not stockee:
            print(f"[{self.SERVICE_NAME}] [{id_obj}] image E{etage}/A{angle} "
                  f"non utilisée par aucun défaut (étage ne correspond pas)")

    def _check_all_complete(self, id_obj: str) -> bool:
        entry = self._buffer[id_obj]

        if self.SERVICE_NAME != "check_position":
            if entry["check_position_status"] is None:
                print(f"[{self.SERVICE_NAME}] [{id_obj}] en attente check_position...")
                return False
            if entry["check_position_status"] == "NG":
                return False

        tous_complets = True
        for did, ddata in entry["defauts"].items():
            if ddata["complet"]:
                continue
            defaut    = ddata["defaut"]
            est_fused = getattr(defaut, "use_fused_image", False)

            if est_fused:
                # Défaut image fusionnée — complet quand fusion_ready
                if entry.get("fusion_ready"):
                    ddata["complet"] = True
                    print(f"[{self.SERVICE_NAME}] [{id_obj}] défaut {did} COMPLET ✅ (fusion)")
                else:
                    print(f"[{self.SERVICE_NAME}] [{id_obj}] défaut {did} "
                          f"en attente image fusionnée")
                    tous_complets = False
            else:
                # Défaut image d'angle — complet quand tous angles reçus
                recus  = set(ddata["images"].keys())
                requis = set(ddata["angles_requis"])
                if requis.issubset(recus):
                    ddata["complet"] = True
                    print(f"[{self.SERVICE_NAME}] [{id_obj}] défaut {did} COMPLET ✅")
                else:
                    manquants = sorted(requis - recus)
                    print(f"[{self.SERVICE_NAME}] [{id_obj}] défaut {did} "
                          f"en attente angles {manquants}")
                    tous_complets = False

        if tous_complets:
            print(f"[{self.SERVICE_NAME}] [{id_obj}] ✅ TOUS DÉFAUTS COMPLETS "
                  f"— lancement inspection")
        return tous_complets
        return True

    # ------------------------------------------------------------------
    # Gestion verdict check_position
    # ------------------------------------------------------------------

    def _on_check_position(self, payload: dict):
        """
        Reçoit le verdict de positionnement publié par service_check_position.

        Cas OK  → débloque le buffer de la bouteille si ses images sont complètes.
        Cas NG  → vide immédiatement le buffer, la bouteille est rejetée sans analyse.
        """
        id_obj  = str(payload.get("id_bouteille", "?"))
        verdict = payload.get("verdict_global", payload.get("status", "NG"))
        ecart   = float(payload.get("ecart_position_px", 0.0))

        print(f"[{self.SERVICE_NAME}] check_position reçu → "
              f"{id_obj} : {verdict} (ecart={ecart:+.1f}px)")

        all_done = False
        with self._buffer_lock:
            entry = self._buffer.get(id_obj)

            if entry is None:
                # Aucune entrée buffer — check arrivé avant toute image
                # Créer une sentinelle minimale pour mémoriser le statut
                self._buffer[id_obj] = {
                    "type"                  : payload.get("type_bouteille", "?"),
                    "timestamp"             : time.time(),
                    "defauts"               : {},
                    "check_position_status" : verdict,
                    "check_ecart_px"        : ecart,
                    "_sentinel"             : True,
                    "fusion_ready"          : False,
                }
                print(f"[{self.SERVICE_NAME}] [{id_obj}] check {verdict} "
                      f"avant images — sentinelle créée")
                if verdict == "NG":
                    print(f"[{self.SERVICE_NAME}] [{id_obj}] images futures ignorées")
                return

            # Le buffer existe — mettre à jour le statut check et rafraîchir timestamp
            entry["check_position_status"] = verdict
            entry["check_ecart_px"]        = ecart
            entry["timestamp"]             = time.time()  # évite purge GC

            if verdict == "NG":
                self._buffer.pop(id_obj, None)
                print(f"[{self.SERVICE_NAME}] [{id_obj}] check NG → "
                      f"buffer vidé, bouteille ignorée")
                return

            # Verdict OK — le buffer a-t-il des défauts (vrai buffer) ?
            if not entry.get("defauts"):
                # C'est une sentinelle sans défauts, les images n'ont pas
                # encore été reçues — rien à faire, _init_buffer_entry
                # récupérera le statut quand les images arriveront
                print(f"[{self.SERVICE_NAME}] [{id_obj}] check OK "
                      f"— sentinelle, en attente des images")
                return

            # Vrai buffer avec défauts — vérifier si tout est complet
            print(f"[{self.SERVICE_NAME}] [{id_obj}] check OK reçu "
                  f"— vérification buffer complet...")
            self._log_buffer_state(id_obj)
            all_done = self._check_all_complete(id_obj)

        if all_done:
            self._execute_inspection(id_obj)

    def _log_buffer_state(self, id_obj: str):
        """Log l'état détaillé du buffer pour debug."""
        entry = self._buffer.get(id_obj)
        if not entry:
            print(f"[{self.SERVICE_NAME}] [{id_obj}] buffer: VIDE")
            return
        check = entry.get("check_position_status", "None")
        print(f"[{self.SERVICE_NAME}] [{id_obj}] buffer state | "
              f"check={check}")
        for did, ddata in entry.get("defauts", {}).items():
            requis = set(ddata["angles_requis"])
            recus  = set(ddata["images"].keys())
            complet = ddata["complet"]
            print(f"[{self.SERVICE_NAME}]   └─ {did} | "
                  f"etage={ddata['etage']} | "
                  f"angles requis={sorted(requis)} | "
                  f"reçus={sorted(recus)} | "
                  f"{len(recus)}/{len(requis)} | "
                  f"complet={complet}")

    # ------------------------------------------------------------------
    # Construction payload de base (utilisé par sous-classes)
    # ------------------------------------------------------------------

    def _build_base_payload(self, id_obj: str, type_btl: str,
                             verdict_global: str,
                             verdicts_defauts: list) -> dict:
        """Construit le payload MQTT de sortie standard."""
        from datetime import datetime, timezone
        return {
            "id_bouteille"  : id_obj,
            "type_bouteille": type_btl,
            "service"       : self.SERVICE_NAME,
            "verdict_global": verdict_global,
            "timestamp"     : datetime.now(timezone.utc)
                              .isoformat().replace("+00:00", "Z"),
            "defauts"       : verdicts_defauts,
        }

    # ------------------------------------------------------------------
    # Inspection & publication
    # ------------------------------------------------------------------

    def _execute_inspection(self, id_obj: str, is_timeout: bool = False):
        with self._buffer_lock:
            entry = self._buffer.pop(id_obj, None)
        if entry is None:
            return

        type_btl        = entry["type"]
        verdicts_defauts = []
        verdict_global   = "OK"

        if is_timeout:
            verdict_global = "NG"
            for ddata in entry["defauts"].values():
                defaut : DefautConfig = ddata["defaut"]
                verdicts_defauts.append({
                    "id_defaut" : defaut.id_defaut,
                    "label"     : defaut.label,
                    "verdict"   : "NG",
                    "mesure"    : None,
                    "reference" : None,
                    "tolerance" : None,
                    "ecart"     : None,
                    "details"   : [{"error": "TIMEOUT_IMAGES_MANQUANTES"}],
                })
        else:
            for did, ddata in entry["defauts"].items():
                defaut  : DefautConfig = ddata["defaut"]
                ref_img = self._get_ref_image(type_btl, defaut)
                etage   = ddata["etage"]

                try:
                    engine = create_engine(defaut, ref_img)

                    all_roi_results  = []
                    last_report      = None
                    visu_angles      : dict = {}   # { angle: { step_name: chemin } }
                    # Récupérer les chemins MinIO originaux stockés dans le buffer
                    chemins_bruts    = ddata.get("chemins_bruts", {})

                    for angle_img in sorted(ddata["images"].keys()):
                        report : InspectionReport = engine.inspect(
                            ddata["images"][angle_img]
                        )
                        all_roi_results.extend(report.roi_results)
                        last_report = report

                        # Sauvegarder les steps OpenCV dans MinIO
                        steps_chemins = self._save_steps_minio(
                            id_obj, type_btl, did,
                            etage, angle_img, report
                        )
                        visu_angles[str(angle_img)] = {
                            "chemin_brute": chemins_bruts.get(angle_img, ""),
                            "steps"       : steps_chemins,
                        }

                    defaut_status = "OK" if all(
                        r.status == "OK" for r in all_roi_results
                    ) else "NG"

                    if defaut_status == "NG":
                        verdict_global = "NG"

                    vdict = self._build_defaut_verdict(
                        defaut, defaut_status, last_report
                    )
                    vdict["algo"]            = defaut.algorithme
                    vdict["angles_requis"]   = ddata["angles_requis"]
                    vdict["angles_visu"]     = visu_angles
                    verdicts_defauts.append(vdict)

                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    verdict_global = "NG"
                    verdicts_defauts.append({
                        "id_defaut"   : did,
                        "label"       : defaut.label,
                        "algo"        : defaut.algorithme,
                        "verdict"     : "NG",
                        "mesure"      : None,
                        "reference"   : None,
                        "tolerance"   : None,
                        "ecart"       : None,
                        "details"     : [{"error": str(e)}],
                        "angles_requis": ddata["angles_requis"],
                        "angles_visu" : {},
                    })

        # ── Publication visualisation traitement ─────────────────────
        # Topic séparé du verdict — permet au dashboard d'afficher les
        # steps sans attendre le service_decision_finale
        topic_visu_trait = _VISU_TOPICS_TRAIT.get(self.SERVICE_NAME)
        if topic_visu_trait and not is_timeout:
            payload_visu = {
                "phase"          : "traitement",
                "id_bouteille"   : id_obj,
                "type_bouteille" : type_btl,
                "service"        : self.SERVICE_NAME,
                "verdict_global" : verdict_global,
                "timestamp"      : datetime.now(timezone.utc)
                                   .isoformat().replace("+00:00", "Z"),
                "defauts"        : [
                    {
                        "id_defaut"    : d.get("id_defaut"),
                        "label"        : d.get("label"),
                        "algo"         : d.get("algo"),
                        "verdict"      : d.get("verdict"),
                        "mesure"       : d.get("mesure"),
                        "reference"    : d.get("reference"),
                        "tolerance"    : d.get("tolerance"),
                        "ecart"        : d.get("ecart"),
                        "details"      : d.get("details", {}),
                        "angles_requis": d.get("angles_requis", []),
                        "angles_visu"  : d.get("angles_visu", {}),
                    }
                    for d in verdicts_defauts
                ],
            }
            try:
                self._mqtt.publish(topic_visu_trait,
                                   json.dumps(payload_visu, ensure_ascii=False))
            except Exception as e:
                print(f"[{self.SERVICE_NAME}] Erreur publish visu traitement: {e}")

        # ── Publication verdict existant (inchangé) ───────────────────
        output = {
            "id_bouteille"  : id_obj,
            "type_bouteille": type_btl,
            "service"       : self.SERVICE_NAME,
            "verdict_global": verdict_global,
            "timestamp"     : datetime.now(timezone.utc)
                              .isoformat().replace("+00:00", "Z"),
            "defauts"       : verdicts_defauts,
        }
        self._mqtt.publish(self.TOPIC_SORTIE, json.dumps(output, ensure_ascii=False))
        print(f"[{self.SERVICE_NAME}] {id_obj} ({type_btl}) "
              f"-> {verdict_global} | {len(verdicts_defauts)} defaut(s)")

    def _save_steps_minio(
        self,
        id_obj    : str,
        type_btl  : str,
        id_defaut : str,
        etage     : int,
        angle     : int,
        report    : "InspectionReport",
    ) -> dict:
        """
        Sauvegarde les steps visuels OpenCV dans MinIO.
        Chemin : VISU_STEPS_PREFIX/<service>/<id>_<type>/<id_defaut>/E<e>_A<a>_<N>_<step>.jpg
        Retourne { "N_step_name": chemin, ... }
        N'inclut PAS l'image brute — elle est déjà dans MinIO à son chemin original.
        """
        import io
        base    = (f"bouteilles_{type_btl}/{id_obj}/"
                   f"visu_steps/{self.SERVICE_NAME}/{id_defaut}")
        chemins = {}

        if not report or not report.roi_results:
            return chemins

        try:
            for roi_r in report.roi_results:
                for step_name, step_img in (roi_r.steps or {}).items():
                    if step_img is None:
                        continue
                    # Nom safe pour MinIO
                    safe_step = step_name.replace(" ", "_") \
                                         .replace("/", "-") \
                                         .replace(".", "")
                    safe_roi  = roi_r.roi_name.replace(" ", "_")
                    key = (f"{base}/E{etage}_A{angle}"
                           f"_{safe_roi}_{safe_step}.jpg")

                    _, buf = cv2.imencode(
                        ".jpg", step_img,
                        [cv2.IMWRITE_JPEG_QUALITY, 88]
                    )
                    data = buf.tobytes()
                    self._minio.put_object(
                        BUCKET_NAME, key,
                        io.BytesIO(data), len(data),
                        content_type="image/jpeg"
                    )
                    # Clé lisible pour le dashboard
                    chemins[step_name] = key

        except Exception as e:
            print(f"[{self.SERVICE_NAME}] Erreur save_steps_minio "
                  f"({id_defaut} E{etage}/A{angle}): {e}")

        return chemins

    @staticmethod
    def _build_defaut_verdict(defaut: DefautConfig,
                               status: str,
                               report: InspectionReport) -> dict:
        roi_verdicts = []
        for r in report.roi_results:
            roi_verdicts.append({
                "roi_name" : r.roi_name,
                "status"   : r.status,
                "mesure"   : round(r.mesure, 3),
                "reference": round(r.reference, 3),
                "tolerance": [round(r.tolerance[0], 3),
                              round(r.tolerance[1], 3)],
                "ecart"    : round(r.ecart, 3),
                "details"  : {
                    k: v for k, v in r.details.items()
                    if isinstance(v, (int, float, str, bool))
                },
            })

        first = report.roi_results[0] if report.roi_results else None
        return {
            "id_defaut" : defaut.id_defaut,
            "label"     : defaut.label,
            "verdict"   : status,
            "mesure"    : round(first.mesure, 3)    if first else None,
            "reference" : round(first.reference, 3) if first else None,
            "tolerance" : [round(first.tolerance[0], 3),
                           round(first.tolerance[1], 3)] if first else None,
            "ecart"     : round(first.ecart, 3)     if first else None,
            "details"   : roi_verdicts,
        }

    # ------------------------------------------------------------------
    # Heartbeat — publication périodique du statut du service
    # ------------------------------------------------------------------

    def _heartbeat(self):
        """
        Publie le statut du service toutes les HEARTBEAT_INTERVAL secondes
        sur TOPIC_STATUS_BASE + SERVICE_NAME.
        Permet au dashboard de détecter les déconnexions même en l'absence
        de trafic de production.
        """
        topic = TOPIC_STATUS_BASE + self.SERVICE_NAME
        while True:
            try:
                payload = json.dumps({
                    "service"  : self.SERVICE_NAME,
                    "status"   : "OK",
                    "timestamp": datetime.now(timezone.utc)
                                 .isoformat().replace("+00:00", "Z"),
                })
                self._mqtt.publish(topic, payload)
            except Exception:
                pass  # Non bloquant — le GC et le listener continuent
            time.sleep(HEARTBEAT_INTERVAL)

    # ------------------------------------------------------------------
    # Garbage Collector
    # ------------------------------------------------------------------

    def _garbage_collector(self):
        while True:
            time.sleep(2)
            now = time.time()
            with self._buffer_lock:
                to_purge = []
                for i, d in self._buffer.items():
                    # Ne pas purger les sentinelles sans défauts
                    if not d.get("defauts"):
                        continue
                    # Ne pas purger un buffer qui attend UNIQUEMENT le check_position
                    # (toutes ses images sont là, il ne manque que le verdict)
                    if d.get("check_position_status") is None:
                        tous_images_ok = all(
                            set(ddata["angles_requis"]).issubset(
                                set(ddata["images"].keys())
                            ) or ddata["complet"]
                            for ddata in d["defauts"].values()
                        )
                        if tous_images_ok:
                            # Buffer complet en attente check — ne pas purger
                            continue
                    if now - d["timestamp"] > TIMEOUT_BUFFER:
                        to_purge.append(i)

            for i in to_purge:
                print(f"[{self.SERVICE_NAME}] Timeout {i} -> forcage NG")
                self._execute_inspection(i, is_timeout=True)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self):
        self._mqtt.connect(MQTT_BROKER, MQTT_PORT, 60)
        self._mqtt.loop_forever()