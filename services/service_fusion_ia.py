import os
import io
import json
import time
import math
import threading
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import cv2
import numpy as np
import paho.mqtt.client as mqtt
from minio import Minio
from dotenv import load_dotenv

# =====================================================================
# 1. CONFIGURATION GLOBALE
# =====================================================================
load_dotenv()

# Connexion MQTT
MQTT_BROKER = os.getenv("MQTT_BROKER_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_BROKER_PORT", 1883))

# Topics MQTT
TOPIC_ENTREE = os.getenv("TOPIC_ENTREE_FUSION", "vision/ia/pretraitement")
TOPIC_SORTIE_RUN   = os.getenv("TOPIC_SORTIE_FUSION", "vision/ia/ready")
TOPIC_SORTIE_LEARN = "vision/ia/dataset_collected"
TOPIC_CONFIG_MODE  = os.getenv("TOPIC_CONFIG_MODE_IA", "vision/config/mode_ia")

# Topics visualisation temps réel
TOPIC_VISU_IMAGE = os.getenv("TOPIC_VISU_FUSION_IMAGE", "vision/visu/fusion/image_brute")
TOPIC_VISU_TRAIT = os.getenv("TOPIC_VISU_FUSION_TRAIT", "vision/visu/fusion/traitement")

# Connexion MinIO
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_USER = os.getenv("MINIO_USER", "admin_vision")
MINIO_PASS = os.getenv("MINIO_PASSWORD", "password123")
BUCKET_NAME = os.getenv("MINIO_BUCKET", "images-production")

# Configuration Fichiers
# On s'assure que le chemin est relatif à la racine du projet (parent du dossier services)
BASE_DIR_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSSIER_RECETTES = os.path.join(BASE_DIR_ROOT, "recettes/fusion")
TIMEOUT_BUFFER_SEC = float(os.getenv("TIMEOUT_BUFFER_SEC", 120.0))
MODE_DEFAUT = os.getenv("MODE_DEMARRAGE_DEFAUT", "RUN")

# =====================================================================
# 2. MOTEUR DE CORRECTION GÉOMÉTRIQUE & FUSION (CORE)
# =====================================================================
class CylindricalUnwrapperHeadless:
    """
    Classe responsable des calculs mathématiques purs.
    Ne dépend d'aucun service externe (MinIO/MQTT).
    """
    def __init__(self, diametre_mm: float, distance_mm: float, fov_deg: float, nb_angles: int):
        # Conversion en mètres pour respecter la formule physique
        self.D = diametre_mm / 1000.0
        self.d = distance_mm / 1000.0
        self.fov_deg = fov_deg
        self.angle_secteur_deg = 360.0 / nb_angles

    def unwrap_slice(self, img: np.ndarray) -> np.ndarray:
        """Déroule la courbure ET extrait uniquement la bande utile (Formule Exacte)"""
        h_src, w_src = img.shape[:2]
        
        # 1. Calculs Géométriques Préliminaires
        hfov_physique = 2 * self.d * math.tan(math.radians(self.fov_deg) / 2.0)
        beta_rad = math.radians((180.0 - self.angle_secteur_deg) / 2.0)
        
        # 2. Calcul du Crop (Rognahe) optimal
        fraction_centrale = (self.D * self.d * math.cos(beta_rad)) / (hfov_physique * (2 * self.d - self.D * math.sin(beta_rad)))
        crop_pixels = (0.5 - fraction_centrale) * w_src
        w_bande_dest = int(w_src - 2 * crop_pixels)
        
        if w_bande_dest <= 0:
            # Sécurité pour éviter le crash si les paramètres sont incohérents
            print("⚠️ AVERTISSEMENT MATH : Largeur calculée <= 0. Utilisation de 10px par défaut.")
            w_bande_dest = 10

        # 3. Projection Inverse 3D -> 2D (Remapping)
        f_px = (w_src / 2.0) / math.tan(math.radians(self.fov_deg) / 2.0)
        cx, cy = w_src / 2.0, h_src / 2.0
        R = self.D / 2.0
        
        angle_demi_secteur_rad = math.radians(self.angle_secteur_deg / 2.0)
        u_vals = np.linspace(-angle_demi_secteur_rad, angle_demi_secteur_rad, w_bande_dest)
        v_vals = np.linspace(-h_src/2, h_src/2, h_src)
        beta_grid, y_grid = np.meshgrid(u_vals, v_vals)
        
        # Coordonnées Cylindriques vers Cartésiennes
        X_3D = R * np.sin(beta_grid)
        Z_3D = self.d - R * np.cos(beta_grid)
        
        # Projection Perspective
        map_x = (f_px * X_3D / Z_3D) + cx
        Y_3D_physique = y_grid * (self.d - R) / f_px 
        map_y = (f_px * Y_3D_physique / Z_3D) + cy
        
        return cv2.remap(img, map_x.astype(np.float32), map_y.astype(np.float32), 
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    def detect_overlap_region(self, img1_top: np.ndarray, img2_bottom: np.ndarray) -> int:
        """Trouve la meilleure zone de superposition verticale"""
        h1, h2 = img1_top.shape[0], img2_bottom.shape[0]
        # On limite la recherche à 150 pixels max pour la performance
        overlap = min(h1, h2, 150)
        
        if overlap < 10: return 0
        
        # Comparaison en niveaux de gris pour la vitesse
        g1 = cv2.cvtColor(img1_top[-overlap:], cv2.COLOR_BGR2GRAY)
        g2 = cv2.cvtColor(img2_bottom[:overlap], cv2.COLOR_BGR2GRAY)
        
        best_offset, best_score = 0, float('inf')
        # Pas de 2 pixels pour accélérer
        for offset in range(0, overlap, 2):
            region1 = g1[offset:]
            region2 = g2[:region1.shape[0]]
            if region1.shape == region2.shape and region1.size > 0:
                # Différence moyenne des pixels
                score = np.mean(np.abs(region1.astype(float) - region2.astype(float)))
                if score < best_score:
                    best_score = score
                    best_offset = offset
        return best_offset

    def blend_images(self, img1: np.ndarray, img2: np.ndarray, overlap_pixels: int) -> np.ndarray:
        """Fusionne deux images avec un dégradé (Alpha Blending)"""
        if overlap_pixels <= 0: return np.vstack([img1, img2])
        
        top = img1[:-overlap_pixels]
        bottom = img2[overlap_pixels:]
        
        fade1 = img1[-overlap_pixels:].astype(float)
        fade2 = img2[:overlap_pixels].astype(float)
        
        # Création du masque de pondération lineaire
        weights = np.linspace(0, 1, overlap_pixels).reshape(-1, 1, 1)
        blended = (fade1 * (1 - weights) + fade2 * weights).astype(np.uint8)
        
        return np.vstack([top, blended, bottom])

    def process_all_in_ram(self, images_dict: Dict[int, Dict[int, np.ndarray]]) -> np.ndarray:
        """
        Orchestre tout le processus : Déroulement Horizontal -> Fusion Verticale.
        Entrée : Dictionnaire { Num_Etage : { Num_Angle : Image_Matrice } }
        Sortie : Image Finale Matrice
        """
        etages_panoramas = {}
        
        # 1. Assemblage Horizontal (Création des bandes pour chaque étage)
        for etage in sorted(images_dict.keys()):
            bandes_rectifiees = []
            # On trie par angle croissant (1, 2, 3...)
            for angle in sorted(images_dict[etage].keys()):
                img = images_dict[etage][angle]
                bande = self.unwrap_slice(img)
                bandes_rectifiees.append(bande)
            
            # Concaténation simple côte à côte
            etages_panoramas[etage] = cv2.hconcat(bandes_rectifiees)

        # 2. Assemblage Vertical (Fusion intelligente)
        # On trie à l'envers : l'étage le plus haut (ex: 2) est au dessus de l'étage bas (ex: 1)
        # Note : Cela dépend de votre convention PLC. Ici on suppose Etage 2 = Haut, Etage 1 = Bas.
        etages_tries = sorted(etages_panoramas.keys(), reverse=True)
        
        image_finale = etages_panoramas[etages_tries[0]]
        
        for i in range(1, len(etages_tries)):
            etage_inferieur = etages_panoramas[etages_tries[i]]
            
            # Calcul automatique du chevauchement
            overlap = self.detect_overlap_region(image_finale, etage_inferieur)
            # Fusion
            image_finale = self.blend_images(image_finale, etage_inferieur, overlap)

        return image_finale

# =====================================================================
# 3. LE SERVICE MQTT (WRAPPER & GESTION DES MODES)
# =====================================================================
class FusionIAService:
    def __init__(self):
        # Initialisation MinIO
        try:
            self.minio = Minio(MINIO_ENDPOINT, access_key=MINIO_USER, secret_key=MINIO_PASS, secure=False)
        except Exception as e:
            print(f"❌ Erreur critique MinIO : {e}")
            
        self.recettes_cache = {}
        self.buffer = {}
        self.buffer_lock = threading.Lock()
        
        # --- GESTION DU MODE ---
        self.current_mode = MODE_DEFAUT  # RUN, OFF, LEARN
        print(f"⚙️ Mode de démarrage : {self.current_mode}")

        # Initialisation MQTT
        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ServiceFusionIA")
        self.mqtt.on_connect = self.on_connect
        self.mqtt.on_message = self.on_message

        # Lancement du Garbage Collector (Nettoyage automatique)
        threading.Thread(target=self.garbage_collector, daemon=True).start()

    def get_recette(self, type_bouteille: str) -> dict:
        """Charge la recette JSON depuis le disque si pas en cache"""
        if type_bouteille not in self.recettes_cache:
            chemin = os.path.join(DOSSIER_RECETTES, f"recette_{type_bouteille}.json")
            if os.path.exists(chemin):
                try:
                    print(f"📖 [RECETTE] Chargement config Fusion : {chemin}")
                    with open(chemin, 'r') as f: self.recettes_cache[type_bouteille] = json.load(f)
                except Exception as e:
                    print(f"❌ Erreur lecture recette JSON {chemin}: {e}")
                    return None
            else:
                print(f"❌ Recette introuvable : {chemin}")
                return None
        return self.recettes_cache[type_bouteille]

    def on_connect(self, client, userdata, flags, rc, properties=None):
        print(f"✅ Connecté MQTT (Code: {rc})")
        # Abonnement aux données d'images ET au topic de configuration
        self.mqtt.subscribe([(TOPIC_ENTREE, 0), (TOPIC_CONFIG_MODE, 0)])
        print(f"🎧 Écoute Flux Images : {TOPIC_ENTREE}")
        print(f"🎧 Écoute Commandes  : {TOPIC_CONFIG_MODE}")

    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload_str = msg.payload.decode()

            # --- CAS 1 : COMMANDE DE CHANGEMENT DE MODE ---
            if topic == TOPIC_CONFIG_MODE:
                nouveau_mode = payload_str.upper().strip()
                if nouveau_mode in ["RUN", "OFF", "LEARN"]:
                    self.current_mode = nouveau_mode
                    print(f"\n🔄 CHANGEMENT DE MODE REÇU -> {self.current_mode}")
                    if self.current_mode == "OFF":
                        # Si on passe en OFF, on vide le buffer pour libérer la RAM
                        with self.buffer_lock:
                            self.buffer.clear()
                            print("   🧹 Buffer vidé (Mode OFF).")
                else:
                    print(f"⚠️ Mode inconnu reçu : {nouveau_mode} (Attendu: RUN, OFF, LEARN)")
                return

            # --- CAS 2 : RÉCEPTION IMAGE ---
            # Si mode OFF, on ne traite rien
            if self.current_mode == "OFF":
                return

            payload = json.loads(payload_str)
            id_bouteille = payload["id_bouteille"]
            type_bouteille = payload["type_bouteille"]
            
            # Lecture des indices (Int)
            etage = int(payload.get("etage", 1))
            angle = int(payload.get("angle", 1))
            chemin_minio = payload["chemin_minio"]

            recette = self.get_recette(type_bouteille)
            if not recette: return

            # Téléchargement RAM depuis MinIO
            try:
                response = self.minio.get_object(BUCKET_NAME, chemin_minio)
                img_data = response.read()
                response.close()
                response.release_conn()
                
                # Décodage OpenCV
                img_array = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)
                if img_array is None:
                    print(f"❌ Erreur décodage image : {chemin_minio}")
                    return
            except Exception as e:
                print(f"❌ Erreur téléchargement MinIO : {e}")
                return

            # Stockage dans le buffer
            with self.buffer_lock:
                if id_bouteille not in self.buffer:
                    self.buffer[id_bouteille] = {
                        "type"      : type_bouteille,
                        "images"    : {},
                        "chemins"   : {},    # chemin MinIO par etage/angle
                        "timestamp" : time.time()
                    }

                if etage not in self.buffer[id_bouteille]["images"]:
                    self.buffer[id_bouteille]["images"][etage] = {}
                if etage not in self.buffer[id_bouteille]["chemins"]:
                    self.buffer[id_bouteille]["chemins"][etage] = {}

                self.buffer[id_bouteille]["images"][etage][angle] = img_array
                self.buffer[id_bouteille]["chemins"][etage][angle] = chemin_minio
                self.buffer[id_bouteille]["timestamp"] = time.time()

                # Compter images reçues pour la progression
                recette_loc = self.get_recette(type_bouteille)
                nb_attendus = 0
                nb_recus    = 0
                if recette_loc:
                    for e in recette_loc["grille_capture"]["etages_attendus"]:
                        for a in recette_loc["grille_capture"]["angles_attendus"]:
                            nb_attendus += 1
                            if (e in self.buffer[id_bouteille]["images"] and
                                    a in self.buffer[id_bouteille]["images"][e]):
                                nb_recus += 1

                # Publish visualisation image_brute
                try:
                    payload_visu = {
                        "phase"              : "image_brute",
                        "id_bouteille"       : id_bouteille,
                        "type_bouteille"     : type_bouteille,
                        "service"            : "fusion",
                        "etage"              : etage,
                        "angle"              : angle,
                        "chemin_brute"       : chemin_minio,
                        "nb_images_recues"   : nb_recus,
                        "nb_images_attendues": nb_attendus,
                        "timestamp"          : datetime.now(timezone.utc)
                                               .isoformat().replace("+00:00", "Z"),
                    }
                    self.mqtt.publish(TOPIC_VISU_IMAGE,
                                      json.dumps(payload_visu))
                except Exception as ve:
                    print(f"[fusion] Erreur publish visu image: {ve}")

                self.check_trigger(id_bouteille)

        except json.JSONDecodeError:
            print("❌ Erreur JSON payload")
        except Exception as e:
            print(f"❌ Erreur inattendue : {e}")

    def check_trigger(self, id_bouteille: str):
        """Vérifie si toutes les images requises par la recette sont présentes"""
        data = self.buffer[id_bouteille]
        recette = self.get_recette(data["type"])
        
        # Récupération de la grille attendue depuis le JSON
        etages_attendus = recette["grille_capture"]["etages_attendus"]
        angles_attendus = recette["grille_capture"]["angles_attendus"]
        
        complet = True
        for e_req in etages_attendus:
            if e_req not in data["images"]: 
                complet = False
                break
            for a_req in angles_attendus:
                if a_req not in data["images"][e_req]: 
                    complet = False
                    break

        if complet:
            print(f"🟢 {id_bouteille} : Grille complète. Lancement Fusion en thread (Mode: {self.current_mode})...")
            t = threading.Thread(
                target=self.execute_fusion,
                args=(id_bouteille,),
                name=f"fusion-{id_bouteille}",
                daemon=True
            )
            t.start()

    def execute_fusion(self, id_bouteille: str):
        # --- EXTRACTION ATOMIQUE du buffer sous verrou ---
        # On fait un pop() immédiat pour qu'aucune autre coroutine
        # (garbage_collector ou autre message MQTT) ne puisse toucher
        # cette entrée pendant le long traitement OpenCV/MinIO.
        with self.buffer_lock:
            data = self.buffer.pop(id_bouteille, None)

        if data is None:
            # L'entrée a déjà été purgée par le garbage_collector : on abandonne
            print(f"⚠️ execute_fusion : buffer de {id_bouteille} déjà purgé, traitement annulé.")
            return

        type_bouteille = data["type"]
        recette = self.get_recette(type_bouteille)
        if not recette:
            return
        dims = recette["dimensions_physiques"]
        # On calcule le nombre d'angles depuis la liste attendue
        nb_angles = len(recette["grille_capture"]["angles_attendus"])

        try:
            # 1. Fusion Mathématique
            unwrapper = CylindricalUnwrapperHeadless(
                diametre_mm=dims["diametre_mm"],
                distance_mm=dims["distance_camera_mm"],
                fov_deg=dims["fov_camera_deg"],
                nb_angles=nb_angles
            )
            image_finale = unwrapper.process_all_in_ram(data["images"])

            # 2. Gestion du Stockage MinIO selon le MODE
            dossier_cible = "fusion_ia"  # Par défaut (RUN)

            if self.current_mode == "LEARN":
                # En mode apprentissage, on range dans dataset
                dossier_cible = "dataset/raw"
                print(f"   🎓 Mode LEARN : Sauvegarde pour entrainement.")

            chemin_fusion = f"bouteilles_{type_bouteille}/{id_bouteille}/{dossier_cible}/deroule.jpg"

            # Encodage JPEG en RAM
            _, encoded_image = cv2.imencode('.jpg', image_finale)
            bytes_io = io.BytesIO(encoded_image.tobytes())

            self.minio.put_object(
                BUCKET_NAME,
                chemin_fusion,
                bytes_io,
                length=bytes_io.getbuffer().nbytes,
                content_type="image/jpeg"
            )
            print(f"   ✅ Image fusionnée uploadée : {chemin_fusion}")

            # Publish visualisation traitement fusion
            try:
                # Compter le total d'images utilisées
                total_imgs = sum(
                    len(angles_dict)
                    for angles_dict in data["images"].values()
                )
                # Collecter les chemins sources dans l'ordre étage/angle
                chemins_sources = []
                for etage in sorted(data["chemins"].keys()):
                    for angle in sorted(data["chemins"][etage].keys()):
                        chemin_src = data["chemins"][etage][angle]
                        if chemin_src:
                            chemins_sources.append(chemin_src)

                payload_visu_trait = {
                    "phase"           : "traitement",
                    "id_bouteille"    : id_bouteille,
                    "type_bouteille"  : type_bouteille,
                    "service"         : "fusion",
                    "chemin_fusion"   : chemin_fusion,
                    "chemins_sources" : chemins_sources,
                    "nb_images"       : total_imgs,
                    "timestamp"       : datetime.now(timezone.utc)
                                       .isoformat().replace("+00:00", "Z"),
                }
                self.mqtt.publish(TOPIC_VISU_TRAIT,
                                  json.dumps(payload_visu_trait))
            except Exception as ve:
                print(f"[fusion] Erreur publish visu traitement: {ve}")

            # 3. Notification MQTT selon le MODE
            payload_sortie = {
                "id_objet": f"BTL_{id_bouteille}",
                "type_bouteille": type_bouteille,
                "chemin_image_fusionnee": f"/{BUCKET_NAME}/{chemin_fusion}",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "mode": self.current_mode
            }

            if self.current_mode == "RUN":
                # Production : On envoie à l'IA de détection
                self.mqtt.publish(TOPIC_SORTIE_RUN, json.dumps(payload_sortie))
                print(f"   🚀 RUN : Envoyé pour analyse IA.")

            elif self.current_mode == "LEARN":
                # Apprentissage : Juste un ACK, pas d'analyse
                self.mqtt.publish(TOPIC_SORTIE_LEARN, json.dumps(payload_sortie))
                print(f"   💾 LEARN : Sauvegardé, pas d'analyse.")

        except Exception as e:
            print(f"❌ Erreur lors du process de fusion : {e}")
        # Pas de del ici : la RAM est libérée automatiquement
        # car 'data' est une variable locale qui sort de scope.

    def garbage_collector(self):
        """Nettoie les buffers incomplets (si une image a été perdue en route)"""
        while True:
            time.sleep(5)
            now = time.time()
            with self.buffer_lock:
                ids_to_purge = [id_btl for id_btl, d in self.buffer.items() if now - d["timestamp"] > TIMEOUT_BUFFER_SEC]
                for id_btl in ids_to_purge:
                    print(f"⚠️ TIMEOUT : Purge du buffer fusion incomplet pour {id_btl}")
                    del self.buffer[id_btl]

    def run(self):
        self.mqtt.connect(MQTT_BROKER, MQTT_PORT, 60)
        self.mqtt.loop_forever()

if __name__ == "__main__":
    print("="*60)
    print("🧬 MICRO-SERVICE : FUSION IA & STITCHING (MULTI-MODES)")
    print("="*60)
    service = FusionIAService()
    service.run()