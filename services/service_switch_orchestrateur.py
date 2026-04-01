import os
import json
import time
from datetime import datetime, timezone
import paho.mqtt.client as mqtt

# Import de la librairie d'environnement
from dotenv import load_dotenv

# =====================================================================
# 1. SETTINGS & CONFIGURATION (Chargée depuis le .env)
# =====================================================================
load_dotenv()

# Connexion MQTT
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", 1883))

# Topics MQTT
TOPIC_ENTREE = os.getenv("TOPIC_ORCHESTRATEUR_ENTREE", "vision/images/new")
TOPIC_STATUS = os.getenv("TOPIC_ORCHESTRATEUR_STATUS", "vision/filtre/status")

# Chemins des recettes orchestrateur
# On s'assure que le chemin est relatif à la racine du projet (parent du dossier services)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_path = os.getenv("CHEMIN_RECETTES_GLOBALES", "./recettes/switch/")
if not os.path.isabs(config_path):
    CHEMIN_RECETTES = os.path.join(BASE_DIR, config_path.replace("./", ""))
else:
    CHEMIN_RECETTES = config_path

# Topic check_position — les images de l'étage de référence y sont routées
# en plus du routage normal vers les services d'analyse
TOPIC_CHECK_POSITION = os.getenv("TOPIC_ENTREE_CHECK_POSITION",
                                  "vision/check/entree")
CHECK_POSITION_ETAGE = int(os.getenv("CHECK_POSITION_ETAGE", 1))

# =====================================================================
# 2. RECETTE MANAGER (Gestion du cache et chargement JSON)
# =====================================================================
class RecetteManager:
    def __init__(self, dossier_recettes):
        self.dossier_recettes = dossier_recettes
        self.type_actif = None
        self.recette_active = None

    def verifier_et_charger(self, type_bouteille):
        """Vérifie si la recette doit être changée, et la charge si besoin."""
        # Si le type n'a pas changé, on garde la recette en mémoire (Performance)
        if type_bouteille == self.type_actif and self.recette_active is not None:
            return True
            
        # Construction du nom de fichier : recette_Type_A.json
        chemin_fichier = os.path.join(self.dossier_recettes, f"recette_{type_bouteille}.json")
        
        try:
            print(f"📖 [RECETTE] Chargement Orchestrateur : {chemin_fichier}")
            with open(chemin_fichier, 'r', encoding='utf-8') as f:
                self.recette_active = json.load(f)
            self.type_actif = type_bouteille
            print(f"   ✅ [RECETTE] Type '{type_bouteille}' chargé avec succès.")
            return True
        except FileNotFoundError:
            print(f"❌ [ERREUR] Fichier recette introuvable : {chemin_fichier}")
            return False
        except json.JSONDecodeError:
            print(f"❌ [ERREUR] JSON corrompu dans le fichier : {chemin_fichier}")
            return False

# =====================================================================
# 3. FILTRE ORCHESTRATEUR (Logique de routage par indices)
# =====================================================================
class FiltreOrchestrateur:
    @staticmethod
    def router_image(image_data, recette):
        """
        Analyse les indices de l'image (Etage/Angle) et les compare 
        à la grille définie dans la recette globale.
        """
        # Récupération des indices venant du PLC (Acquisition)
        try:
            etage_image = int(image_data.get("etage", -1))
            angle_image = int(image_data.get("angle", -1))
        except (ValueError, TypeError):
            print("⚠️ Indices Etage/Angle invalides dans le message entrant.")
            return []

        destinations = []

        # On parcourt tous les algorithmes configurés pour ce type de bouteille
        for algo_nom, algo_config in recette.get("algorithmes", {}).items():
            # Si l'algorithme est désactivé dans la recette → aucun envoi, log visible
            if not algo_config.get("actif", True):
                print(f"   ⏸️  [{algo_nom}] désactivé (actif: false) — aucune publication.")
                continue

            sel = algo_config.get("selection_images", {})
            
            # --- LOGIQUE DE MATCH PAR INDICES ---
            etages_attendus = sel.get("etages_attendus", [])
            angles_attendus = sel.get("angles_attendus", [])

            # L'image est routée si son étage ET son angle sont dans les listes autorisées
            if etage_image in etages_attendus and angle_image in angles_attendus:
                destinations.append({
                    "topic": algo_config["topic_mqtt"],
                    "algo_nom": algo_nom,
                    "info_recette": sel
                })

        return destinations

# =====================================================================
# 4. POINT D'ENTRÉE (SERVICE MQTT)
# =====================================================================
class OrchestrateurService:
    def __init__(self):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ServiceFiltreOrchestrateur")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.recette_manager = RecetteManager(CHEMIN_RECETTES)

    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            print(f"✅ [MQTT] Connecté au Broker ({MQTT_BROKER_HOST})")
            client.subscribe(TOPIC_ENTREE)
            print(f"🎧 [MQTT] En écoute sur : {TOPIC_ENTREE}")
        else:
            print(f"❌ [MQTT] Échec de connexion. Code : {rc}")

    def on_message(self, client, userdata, msg):
        start_time = time.time()
        try:
            # 1. Lecture du message de l'Acquisition
            payload = json.loads(msg.payload.decode('utf-8'))
            type_btl = payload.get("type_bouteille")
            
            if not type_btl:
                print("⚠️ Message reçu sans 'type_bouteille'. Ignoré.")
                return

            # 2. Chargement de la recette correspondante
            if not self.recette_manager.verifier_et_charger(type_btl):
                return # Impossible de router sans recette
                
            # 3. Calcul du routage (Décision)
            destinations = FiltreOrchestrateur.router_image(
                payload, 
                self.recette_manager.recette_active
            )
            
            # 4. Envoi vers les topics des algorithmes
            if not destinations:
                return

            id_btl  = payload.get('id_bouteille', '?')
            etage   = payload.get('etage', '?')
            angle   = payload.get('angle', '?')
            chemin  = payload.get('chemin_minio', '?')

            print(f"\n[SWITCH] 📦 ID:{id_btl} | E:{etage} A:{angle} | {chemin}")

            for dest in destinations:
                msg_enrichi = payload.copy()
                msg_enrichi["timestamp_filtre"]  = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                msg_enrichi["algo_destinataire"] = dest["algo_nom"]
                msg_enrichi["parametres_algo"]   = dest["info_recette"]

                self.client.publish(dest["topic"], json.dumps(msg_enrichi))
                print(f"[SWITCH]   ➔ topic: {dest['topic']} "
                      f"[{dest['algo_nom']}]")

            # 5. Routage parallèle vers check_position
            etage_image = int(payload.get("etage", -1))
            if etage_image == CHECK_POSITION_ETAGE:
                msg_check = payload.copy()
                msg_check["timestamp_filtre"]  = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                msg_check["algo_destinataire"] = "check_position"
                self.client.publish(TOPIC_CHECK_POSITION, json.dumps(msg_check))
                print(f"[SWITCH]   ➔ topic: {TOPIC_CHECK_POSITION} "
                      f"[check_position] (étage {etage_image})")
                
            # Log de performance
            diff_ms = (time.time() - start_time) * 1000
            if len(destinations) > 0:
                print(f"⏱️ Routage effectué en {diff_ms:.2f} ms")

        except json.JSONDecodeError:
            print("❌ [ERREUR] Payload MQTT n'est pas un JSON valide.")
        except Exception as e:
            print(f"❌ [ERREUR] Système : {e}")

    def run(self):
        try:
            self.client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
            self.client.loop_start() 
            
            print("\n🚀 ORCHESTRATEUR EN LIGNE (Mode Indices Etage/Angle)")
            print("="*50)

            while True:
                # Heartbeat de supervision
                status = {
                    "service": "filtre_orchestrateur",
                    "status": "OK",
                    "type_actif": self.recette_manager.type_actif,
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                }
                self.client.publish(TOPIC_STATUS, json.dumps(status))
                time.sleep(5)
                
        except KeyboardInterrupt:
            print("\n🛑 Arrêt de l'orchestrateur.")
            self.client.loop_stop()
            self.client.disconnect()
        except Exception as e:
            print(f"❌ Erreur critique : {e}")

if __name__ == "__main__":
    service = OrchestrateurService()
    service.run()