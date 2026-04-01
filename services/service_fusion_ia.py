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
TOPIC_SORTIE_RUN = os.getenv("TOPIC_SORTIE_FUSION", "vision/ia/ready")
TOPIC_SORTIE_LEARN = "vision/ia/dataset_collected"
TOPIC_CONFIG_MODE = os.getenv("TOPIC_CONFIG_MODE_IA", "vision/config/mode_ia")

# check_position — fusion s'y abonne pour récupérer l'écart de positionnement
# et effectuer un recadrage asymétrique de la bouteille dans le panorama
TOPIC_CHECK_POSITION = os.getenv("TOPIC_SORTIE_CHECK_POSITION", "vision/check/position")

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

    def unwrap_slice(self, img: np.ndarray,
                     ecart_px: float = 0.0) -> np.ndarray:
        """
        Déroule la courbure ET extrait uniquement la bande utile (Formule Exacte).

        ecart_px : écart de positionnement fourni par check_position (signé).
          Positif → bouteille décalée à droite → on rogne plus à gauche
          Négatif → bouteille décalée à gauche  → on rogne plus à droite
        """
        h_src, w_src = img.shape[:2]
        
        # 1. Calculs Géométriques Préliminaires
        hfov_physique = 2 * self.d * math.tan(math.radians(self.fov_deg) / 2.0)
        beta_rad = math.radians((180.0 - self.angle_secteur_deg) / 2.0)
        
        # 2. Calcul du Crop (Rognage) symétrique de base
        fraction_centrale = (self.D * self.d * math.cos(beta_rad)) / (hfov_physique * (2 * self.d - self.D * math.sin(beta_rad)))
        crop_base = (0.5 - fraction_centrale) * w_src

        # 3. Correction asymétrique selon l'écart de positionnement
        #    ecart_px > 0 → bouteille à droite → rogne plus à gauche, moins à droite
        #    ecart_px < 0 → bouteille à gauche → rogne plus à droite, moins à gauche
        crop_gauche = int(max(0, crop_base + ecart_px))
        crop_droite = int(max(0, crop_base - ecart_px))

        w_bande_dest = w_src - crop_gauche - crop_droite
        
        if w_bande_dest <= 0:
            print("⚠️ AVERTISSEMENT MATH : Largeur calculée <= 0. Utilisation de 10px par défaut.")
            w_bande_dest = 10
            crop_gauche  = (w_src - 10) // 2
            crop_droite  = w_src - 10 - crop_gauche

        # 4. Projection Inverse 3D -> 2D (Remapping)
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

    def process_all_in_ram(self, images_dict: Dict[int, Dict[int, np.ndarray]],
                            ecart_px: float = 0.0) -> np.ndarray:
        """
        Orchestre tout le processus : Déroulement Horizontal -> Fusion Verticale.
        Entrée : Dictionnaire { Num_Etage : { Num_Angle : Image_Matrice } }
        ecart_px : écart de positionnement (signé) depuis check_position
        Sortie : Image Finale Matrice
        """
        etages_panoramas = {}
        
        # 1. Assemblage Horizontal (Création des bandes pour chaque étage)
        for etage in sorted(images_dict.keys()):
            bandes_rectifiees = []
            for angle in sorted(images_dict[etage].keys()):
                img   = images_dict[etage][angle]
                # Recadrage asymétrique appliqué sur chaque bande
                bande = self.unwrap_slice(img, ecart_px=ecart_px)
                bandes_rectifiees.append(bande)
            
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
        self.mqtt.subscribe([
            (TOPIC_ENTREE,          0),
            (TOPIC_CONFIG_MODE,     0),
            (TOPIC_CHECK_POSITION,  0),   # pour récupérer l'écart de positionnement
        ])
        print(f"🎧 Écoute Flux Images    : {TOPIC_ENTREE}")
        print(f"🎧 Écoute Commandes      : {TOPIC_CONFIG_MODE}")
        print(f"🎧 Écoute Check Position : {TOPIC_CHECK_POSITION}")

    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload_str = msg.payload.decode()

            # ── Verdict check_position → stocker l'écart dans le buffer ──
            if topic == TOPIC_CHECK_POSITION:
                try:
                    payload      = json.loads(payload_str)
                    id_bouteille = str(payload.get("id_bouteille", "?"))
                    ecart_px     = float(payload.get("ecart_position_px", 0.0))
                    verdict      = payload.get("verdict_global",
                                               payload.get("status", "NG"))
                    with self.buffer_lock:
                        if id_bouteille not in self.buffer:
                            # Pré-créer l'entrée pour stocker l'écart en avance
                            self.buffer[id_bouteille] = {
                                "type"     : payload.get("type_bouteille", "?"),
                                "images"   : {},
                                "timestamp": time.time(),
                                "ecart_px" : ecart_px,
                            }
                        else:
                            self.buffer[id_bouteille]["ecart_px"] = ecart_px

                    print(f"   🎯 [Fusion] check_position reçu → "
                          f"{id_bouteille} : {verdict} (ecart={ecart_px:+.1f}px)")
                except Exception as e:
                    print(f"❌ Erreur traitement check_position : {e}")
                return

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
                        "type"     : type_bouteille,
                        "images"   : {},
                        "timestamp": time.time(),
                        "ecart_px" : 0.0,   # sera mis à jour par check_position
                    }
                
                if etage not in self.buffer[id_bouteille]["images"]:
                    self.buffer[id_bouteille]["images"][etage] = {}
                    
                self.buffer[id_bouteille]["images"][etage][angle] = img_array
                self.buffer[id_bouteille]["timestamp"] = time.time()
                
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
        ecart_px       = data.get("ecart_px", 0.0)
        recette = self.get_recette(type_bouteille)
        if not recette:
            return
        dims = recette["dimensions_physiques"]
        nb_angles = len(recette["grille_capture"]["angles_attendus"])

        try:
            # 1. Fusion Mathématique avec recadrage asymétrique
            unwrapper = CylindricalUnwrapperHeadless(
                diametre_mm=dims["diametre_mm"],
                distance_mm=dims["distance_camera_mm"],
                fov_deg=dims["fov_camera_deg"],
                nb_angles=nb_angles
            )
            if ecart_px != 0.0:
                print(f"   🎯 Recadrage asymétrique appliqué : ecart={ecart_px:+.1f}px")
            image_finale = unwrapper.process_all_in_ram(data["images"],
                                                         ecart_px=ecart_px)

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