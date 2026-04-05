import os
import io
import json
import time
import threading
from datetime import datetime, timezone
from typing import Dict, Optional

import cv2
import numpy as np
import paho.mqtt.client as mqtt
from minio import Minio
from dotenv import load_dotenv

# =====================================================================
# 1. CONFIGURATION GLOBALE
# =====================================================================
load_dotenv()

MQTT_BROKER = os.getenv("MQTT_BROKER_HOST", "localhost")
MQTT_PORT   = int(os.getenv("MQTT_BROKER_PORT", 1883))

TOPIC_ENTREE  = os.getenv("TOPIC_SORTIE_FUSION", "vision/ia/ready")
TOPIC_SORTIE  = os.getenv("TOPIC_SORTIE_IA",    "vision/resultats/ia")
TOPIC_STATUS  = os.getenv("TOPIC_STATUS_BASE",  "vision/status/") + "ia"
TOPIC_VISU_IA = os.getenv("TOPIC_VISU_IA_TRAIT","vision/visu/ia/resultat")

VISU_STEPS_PREFIX = os.getenv("VISU_STEPS_PREFIX", "visu_steps")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT",  "localhost:9000")
MINIO_USER     = os.getenv("MINIO_USER",      "admin_vision")
MINIO_PASS     = os.getenv("MINIO_PASSWORD",  "password123")
BUCKET_NAME    = os.getenv("MINIO_BUCKET",    "images-production")

# Chemin vers un modèle ONNX/PyTorch (laisser vide = placeholder actif)
# On s'assure que le chemin est relatif à la racine du projet
BASE_DIR_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_model_path = os.getenv("MODEL_PATH", "").split("#")[0].strip() # Nettoyage des commentaires eol
if config_model_path and not os.path.isabs(config_model_path):
    MODEL_PATH = os.path.join(BASE_DIR_ROOT, config_model_path.replace("./", ""))
else:
    MODEL_PATH = config_model_path

TIMEOUT_SEC = float(os.getenv("TIMEOUT_BUFFER_SEC", 60.0))


# =====================================================================
# 2. MOTEUR D'ANALYSE IA (HEADLESS)
# =====================================================================
class IAInspectorHeadless:
    """
    Moteur d'analyse IA sans interface graphique.

    Mode PLACEHOLDER (MODEL_PATH vide) :
        Analyse simple du contraste/luminosité du panorama.
        Retourne toujours OK avec un score de confiance fictif.
        Structure conçue pour accueillir un vrai modèle sans refactoring.

    Mode MODELE (MODEL_PATH renseigné) :
        Charge un modèle ONNX via OpenCV DNN.
        → Remplacer la méthode `_run_model()` pour PyTorch/TensorFlow.
    """

    def __init__(self, model_path: str = ""):
        self.model_path = model_path
        self.model = None
        self.mode = "placeholder"

        if model_path and os.path.exists(model_path):
            try:
                self.model = cv2.dnn.readNet(model_path)
                self.mode = "onnx"
                print(f"   ✅ Modèle IA chargé : {model_path}")
            except Exception as e:
                print(f"   ⚠️ Impossible de charger le modèle '{model_path}' : {e}")
                print(f"   ⚠️ Passage en mode PLACEHOLDER.")
        else:
            if model_path:
                print(f"   ⚠️ MODEL_PATH introuvable : '{model_path}' → mode PLACEHOLDER.")
            else:
                print(f"   ℹ️ MODEL_PATH non défini → mode PLACEHOLDER.")

    def analyser(self, panorama: np.ndarray) -> dict:
        """
        Point d'entrée unique de l'analyse.
        Retourne un dict conforme au format des autres services.
        """
        if self.mode == "onnx" and self.model is not None:
            return self._run_model(panorama)
        else:
            return self._run_placeholder(panorama)

    def _run_placeholder(self, panorama: np.ndarray) -> dict:
        """
        Analyse basique : calcule le contraste global du panorama.
        Utilisé quand aucun modèle ML n'est disponible.

        ─── À REMPLACER par votre logique de prétraitement quand le modèle sera prêt ───
        """
        gray = cv2.cvtColor(panorama, cv2.COLOR_BGR2GRAY)

        # Métriques simples pour simuler une analyse
        mean_val  = float(np.mean(gray))
        std_val   = float(np.std(gray))
        # Score fictif normalisé entre 0 et 1 (STD élevée = image riche = "bonne")
        score = min(std_val / 80.0, 1.0)

        return {
            "IA_SURFACE": {
                "status":           "OK",
                "defauts_detectes": 0,
                "score_confiance":  round(score, 4),
                "luminosite_mean":  round(mean_val, 2),
                "contraste_std":    round(std_val, 2),
                "mode":             "placeholder",
                "note":             "Modèle ML non disponible — résultat simulé"
            }
        }

    def annoter_panorama(self, panorama: np.ndarray,
                          details_ia: dict) -> np.ndarray:
        """
        Génère une image annotée du panorama avec les résultats IA.
        En mode placeholder : affiche le statut global + métriques.
        En mode modèle ONNX : dessine les bounding boxes si disponibles.
        """
        vis = panorama.copy()
        h, w = vis.shape[:2]

        # Fond semi-transparent pour le texte
        overlay = vis.copy()
        cv2.rectangle(overlay, (0, 0), (w, 60), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.55, vis, 0.45, 0, vis)

        # Statut global
        statut_global = "OK"
        for res in details_ia.values():
            if res.get("status") == "NG":
                statut_global = "NG"
                break

        color = (0, 220, 0) if statut_global == "OK" else (0, 0, 220)
        cv2.putText(vis, f"IA — {statut_global}",
                    (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

        # Détails par ROI / détection
        y_off = 55
        for nom, res in details_ia.items():
            score = res.get("score_confiance", 0)
            mode  = res.get("mode", "?")
            nb    = res.get("defauts_detectes", 0)
            c     = (0, 220, 0) if res.get("status") == "OK" else (0, 0, 220)
            cv2.putText(vis,
                        f"{nom}: {res.get('status','?')}  "
                        f"score={score:.3f}  defauts={nb}  [{mode}]",
                        (12, y_off),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1)
            y_off += 20

            # Bounding boxes si disponibles (mode YOLO futur)
            for bbox in res.get("bboxes", []):
                x1, y1, x2, y2 = bbox.get("x1",0), bbox.get("y1",0), \
                                  bbox.get("x2",0), bbox.get("y2",0)
                label = bbox.get("label", "?")
                conf  = bbox.get("confidence", 0)
                cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 0, 220), 2)
                cv2.putText(vis, f"{label} {conf:.2f}",
                            (x1, max(y1-6, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0,0,220), 1)
        return vis
        """
        Inférence avec modèle ONNX chargé via OpenCV DNN.

        ─── À ADAPTER selon l'architecture de votre modèle ───
        Taille d'entrée, classes de sortie, seuil de décision.
        """
        try:
            # Prétraitement standard (adapter selon votre modèle)
            blob = cv2.dnn.blobFromImage(
                panorama,
                scalefactor=1.0 / 255.0,
                size=(224, 224),
                mean=(0.485, 0.456, 0.406),
                swapRB=True,
                crop=False
            )
            self.model.setInput(blob)
            output = self.model.forward()

            # Interprétation : adapter selon les sorties de votre modèle
            # Exemple : 2 classes [OK_score, NG_score]
            scores = output[0]
            idx_max = int(np.argmax(scores))
            confiance = float(scores[idx_max])
            status = "OK" if idx_max == 0 else "NG"
            nb_defauts = 0 if status == "OK" else 1

            return {
                "IA_SURFACE": {
                    "status":           status,
                    "defauts_detectes": nb_defauts,
                    "score_confiance":  round(confiance, 4),
                    "mode":             "onnx",
                    "model_path":       self.model_path
                }
            }
        except Exception as e:
            print(f"   ❌ Erreur inférence modèle : {e}")
            return {
                "IA_SURFACE": {
                    "status": "NG",
                    "defauts_detectes": -1,
                    "score_confiance":  0.0,
                    "mode":   "onnx_erreur",
                    "erreur": str(e)
                }
            }


# =====================================================================
# 3. WRAPPER MICRO-SERVICE (MQTT)
# =====================================================================
class IAService:
    """
    Wrapper MQTT autour du moteur IA.
    Écoute vision/ia/ready → télécharge panorama → analyse → publie vision/resultats/ia.
    Pas de buffer ici : chaque message = 1 panorama = 1 analyse indépendante.
    """

    def __init__(self):
        # Connexion MinIO
        try:
            self.minio = Minio(
                MINIO_ENDPOINT,
                access_key=MINIO_USER,
                secret_key=MINIO_PASS,
                secure=False
            )
        except Exception as e:
            print(f"❌ Erreur initialisation MinIO : {e}")
            self.minio = None

        # Chargement du moteur IA (unique, partagé)
        self.inspector = IAInspectorHeadless(MODEL_PATH)

        # Client MQTT (Utilisation de la version 2 de l'API pour éviter les warnings)
        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ServiceIA")
        self.mqtt.on_connect = self.on_connect
        self.mqtt.on_message = self.on_message

        # Heartbeat toutes les 10s
        threading.Thread(target=self._heartbeat, daemon=True).start()

    # ------------------------------------------------------------------
    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            print(f"✅ Connecté MQTT (code: {rc})")
            self.mqtt.subscribe(TOPIC_ENTREE, qos=0)
            print(f"🎧 Écoute panoramas : {TOPIC_ENTREE}")
        else:
            print(f"❌ Échec de connexion MQTT (code: {rc})")

    # ------------------------------------------------------------------
    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            id_bouteille   = payload["id_objet"].replace("BTL_", "")
            type_bouteille = payload["type_bouteille"]
            chemin_panorama = payload["chemin_image_fusionnee"].lstrip("/")

            # Extraction du bucket si présent dans le chemin
            # Format attendu : "images-production/bouteilles_Type_A/.../deroule.jpg"
            chemin_parts = chemin_panorama.split("/", 1)
            if len(chemin_parts) == 2 and chemin_parts[0] == BUCKET_NAME:
                chemin_objet = chemin_parts[1]
            else:
                chemin_objet = chemin_panorama

            print(f"\n🧠 ANALYSE IA : bouteille {id_bouteille} ({type_bouteille})")
            print(f"   Panorama : {chemin_objet}")

            # --- Téléchargement du panorama depuis MinIO ---
            if self.minio is None:
                raise RuntimeError("MinIO non initialisé")

            try:
                response = self.minio.get_object(BUCKET_NAME, chemin_objet)
                img_data = response.read()
                response.close()
                response.release_conn()
            except Exception as e:
                print(f"   ❌ Erreur téléchargement panorama : {e}")
                self._publier_erreur(id_bouteille, type_bouteille, str(e))
                return

            # --- Décodage ---
            panorama = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)
            if panorama is None:
                print(f"   ❌ Impossible de décoder l'image panorama.")
                self._publier_erreur(id_bouteille, type_bouteille, "Décodage image échoué")
                return

            print(f"   📐 Panorama décodé : {panorama.shape[1]}×{panorama.shape[0]} px")

            # --- Analyse IA ---
            t_start = time.time()
            details_ia = self.inspector.analyser(panorama)
            duree_ms = int((time.time() - t_start) * 1000)

            # Verdict global : NG si au moins un sous-résultat est NG
            statut_global = "OK"
            for roi_result in details_ia.values():
                if roi_result.get("status") == "NG":
                    statut_global = "NG"
                    break

            print(f"   ✅ Analyse terminée en {duree_ms} ms → {statut_global}")
            for nom, res in details_ia.items():
                print(f"      {nom} : {res['status']} (confiance={res.get('score_confiance','?')}, mode={res.get('mode','?')})")

            # --- Génération et sauvegarde image annotée ---
            chemin_annote = ""
            try:
                img_annotee  = self.inspector.annoter_panorama(panorama, details_ia)
                _, buf = cv2.imencode(".jpg", img_annotee,
                                     [cv2.IMWRITE_JPEG_QUALITY, 88])
                data_ann = buf.tobytes()
                chemin_annote = (f"bouteilles_{type_bouteille}/{id_bouteille}/"
                                 f"visu_steps/ia/resultat_annote.jpg")
                self.minio.put_object(
                    BUCKET_NAME, chemin_annote,
                    io.BytesIO(data_ann), len(data_ann),
                    content_type="image/jpeg"
                )
                print(f"   ✅ Image annotée IA sauvegardée : {chemin_annote}")
            except Exception as e:
                print(f"   ⚠️ Erreur sauvegarde image annotée IA : {e}")

            # --- Publication visualisation IA ---
            try:
                detections = []
                for nom, res in details_ia.items():
                    detections.append({
                        "label"      : nom,
                        "status"     : res.get("status"),
                        "confidence" : res.get("score_confiance", 0),
                        "defauts_nb" : res.get("defauts_detectes", 0),
                        "mode"       : res.get("mode"),
                        "bboxes"     : res.get("bboxes", []),
                    })
                payload_visu = {
                    "phase"          : "traitement",
                    "id_bouteille"   : id_bouteille,
                    "type_bouteille" : type_bouteille,
                    "service"        : "ia",
                    "verdict_global" : statut_global,
                    "chemin_brute"   : chemin_objet,
                    "chemin_annote"  : chemin_annote,
                    "detections"     : detections,
                    "duree_ms"       : duree_ms,
                    "timestamp"      : datetime.now(timezone.utc)
                                       .isoformat().replace("+00:00", "Z"),
                }
                self.mqtt.publish(TOPIC_VISU_IA, json.dumps(payload_visu))
            except Exception as e:
                print(f"   ⚠️ Erreur publish visu IA : {e}")

            # --- Publication résultat ---
            output = {
                "id_bouteille":    id_bouteille,
                "type_bouteille":  type_bouteille,
                "status":          statut_global,
                "details":         details_ia,
                "duree_analyse_ms": duree_ms,
                "mode_ia":         self.inspector.mode,
                "timestamp":       datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            }
            self.mqtt.publish(TOPIC_SORTIE, json.dumps(output))
            print(f"   📤 Résultat publié sur {TOPIC_SORTIE}")

        except json.JSONDecodeError:
            print("❌ Payload JSON invalide reçu")
        except KeyError as e:
            print(f"❌ Champ manquant dans le payload : {e}")
        except Exception as e:
            print(f"❌ Erreur inattendue : {e}")

    # ------------------------------------------------------------------
    def _publier_erreur(self, id_bouteille: str, type_bouteille: str, raison: str):
        """Publie un résultat NG en cas d'erreur technique."""
        output = {
            "id_bouteille":   id_bouteille,
            "type_bouteille": type_bouteille,
            "status":         "NG",
            "details": {
                "IA_SURFACE": {
                    "status":           "NG",
                    "defauts_detectes": -1,
                    "score_confiance":  0.0,
                    "mode":             "erreur",
                    "erreur":           raison
                }
            },
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        }
        self.mqtt.publish(TOPIC_SORTIE, json.dumps(output))

    # ------------------------------------------------------------------
    def _heartbeat(self):
        """Publie un statut toutes les 10 secondes."""
        while True:
            time.sleep(10)
            try:
                self.mqtt.publish(TOPIC_STATUS, json.dumps({
                    "service": "ia",
                    "mode":    self.inspector.mode,
                    "ts":      datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                }))
            except Exception:
                pass

    # ------------------------------------------------------------------
    def run(self):
        self.mqtt.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        self.mqtt.loop_forever()


# =====================================================================
# 4. POINT D'ENTRÉE
# =====================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("🧠 MICRO-SERVICE : ANALYSE IA (PANORAMA SURFACE)")
    print("=" * 60)
    print(f"   MODEL_PATH : '{MODEL_PATH}' {'(placeholder actif)' if not MODEL_PATH else ''}")
    service = IAService()
    service.run()