import os
import time
import json
import asyncio
from asyncua import Client
from minio import Minio
import paho.mqtt.client as mqtt

# Import de la librairie d'environnement
from dotenv import load_dotenv

# =========================================================
# 1. CONFIGURATION GLOBALE (Chargée depuis le .env)
# =========================================================
load_dotenv()

# --- CONFIG AUTOMATE (OPC UA) ---
PLC_URL = os.getenv("PLC_URL", "opc.tcp://192.168.0.1:4840")
NODE_ID_BOUTEILLE  = os.getenv("PLC_NODE_ID",    'ns=3;s="DB_Vision"."ID_Bouteille"')
NODE_TYPE_BOUTEILLE = os.getenv("PLC_NODE_TYPE",  'ns=3;s="DB_Vision"."Type_Bouteille"')
NODE_ETAGE        = os.getenv("PLC_NODE_ETAGE",  'ns=3;s="DB_Vision"."Etage"')
NODE_INDEX_ANGLE  = os.getenv("PLC_NODE_ANGLE",  'ns=3;s="DB_Vision"."Index_Angle"')

# --- CONFIG STOCKAGE (MinIO) ---
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_USER = os.getenv("MINIO_USER", "admin_vision")
MINIO_PASS = os.getenv("MINIO_PASSWORD", "password123")
BUCKET_NAME = os.getenv("MINIO_BUCKET", "images-production")

# --- CONFIG MESSAGERIE (MQTT) ---
MQTT_BROKER = os.getenv("MQTT_BROKER_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_BROKER_PORT", 1883))
# On publie directement vers l'entrée de l'orchestrateur
TOPIC_NOUVELLE_IMAGE = os.getenv("TOPIC_ORCHESTRATEUR_ENTREE", "vision/images/new")

# --- CONFIG DOSSIER LOCAL ---
# On s'assure que le chemin est relatif à la racine du projet (parent du dossier services)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_path = os.getenv("RECEPTION_FTP_PATH", "./Reception_ftp_file")
if not os.path.isabs(config_path):
    DOSSIER_RECEPTION = os.path.join(BASE_DIR, config_path.replace("./", ""))
else:
    DOSSIER_RECEPTION = config_path

# =========================================================
# 2. FONCTIONS UTILITAIRES
# =========================================================

def setup_minio():
    """Crée le bucket dans MinIO s'il n'existe pas encore"""
    client_minio = Minio(MINIO_ENDPOINT, access_key=MINIO_USER, secret_key=MINIO_PASS, secure=False)
    if not client_minio.bucket_exists(BUCKET_NAME):
        client_minio.make_bucket(BUCKET_NAME)
        print(f"📦 Bucket '{BUCKET_NAME}' créé dans MinIO.")
    else:
        print(f"📦 Bucket '{BUCKET_NAME}' détecté.")
    return client_minio

def envoyer_mqtt(payload):
    """Envoie un message JSON sur le réseau MQTT"""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.publish(TOPIC_NOUVELLE_IMAGE, json.dumps(payload))
    client.disconnect()
    print(f"   📨 Notification MQTT envoyée à l'Orchestrateur")

# =========================================================
# 3. BOUCLE PRINCIPALE (ASYNC)
# =========================================================

async def main():
    print("="*50)
    print("📸 MICRO-SERVICE : ACQUISITION & SYNCHRONISATION")
    print("="*50)
    
    # 1. Vérification du dossier de réception
    if not os.path.exists(DOSSIER_RECEPTION):
        os.makedirs(DOSSIER_RECEPTION)
        print(f"📁 Dossier local créé : {DOSSIER_RECEPTION}")

    # 2. Initialisation MinIO
    try:
        minio_client = setup_minio()
    except Exception as e:
        print(f"❌ Erreur critique MinIO (Vérifiez que Docker tourne) : {e}")
        return

    # 3. Connexion à l'Automate (OPC UA)
    print(f"🔗 Connexion à l'automate {PLC_URL}...")
    async with Client(url=PLC_URL) as client:
        print("✅ Connecté à l'automate PLC !")

        # Récupération des noeuds
        try:
            var_id    = client.get_node(NODE_ID_BOUTEILLE)
            var_etage = client.get_node(NODE_ETAGE)
            var_angle = client.get_node(NODE_INDEX_ANGLE)
        except Exception as e:
            print(f"❌ Erreur NodeID OPC UA (ID, Etage ou Index_Angle introuvable) : {e}")
            return

        # Tentative de récupération du noeud Type_Bouteille
        try:
            var_type = client.get_node(NODE_TYPE_BOUTEILLE)
            # Petit test de lecture pour vérifier que le noeud existe vraiment
            await var_type.read_value()
            has_type_node = True
        except:
            print("⚠️ Variable 'Type_Bouteille' non trouvée dans le PLC. Utilisation de '250ml' par défaut.")
            has_type_node = False

        print(f"👀 Surveillance du dossier '{DOSSIER_RECEPTION}' active...")

        # 4. Boucle infinie de surveillance FTP
        while True:
            fichiers =[f for f in os.listdir(DOSSIER_RECEPTION) if f.endswith(('.jpg', '.png', '.jpeg'))]

            for fichier in fichiers:
                chemin_complet = os.path.join(DOSSIER_RECEPTION, fichier)
                
                # --- A. LECTURE SYNCHRONISÉE AVEC L'AUTOMATE ---
                try:
                    val_id    = await var_id.read_value()
                    val_etage = int(await var_etage.read_value())
                    val_angle = int(await var_angle.read_value())
                    
                    if has_type_node:
                        val_type = str(await var_type.read_value())
                    else:
                        val_type = "250ml"  # Fallback par défaut
                    
                    timestamp = int(time.time())
                    
                    print(f"\n📸 IMAGE DÉTECTÉE : {fichier}")
                    print(f"   Contexte PLC -> Bouteille: {val_type}_{val_id} | Étage: {val_etage} | Index Angle: {val_angle}")

                except Exception as e:
                    print(f"❌ Erreur de communication PLC : {e}")
                    continue

                # --- B. RENOMMAGE ET SAUVEGARDE MINIO ---
                extension_origine = os.path.splitext(fichier)[1].lower()
                if not extension_origine:
                    extension_origine = ".jpg" # Fallback
                
                nom_fichier_final = f"ID{val_id}_E{val_etage}_A{val_angle}_{timestamp}{extension_origine}"
                chemin_minio = f"bouteilles_{val_type}/{val_id}/{nom_fichier_final}"

                # Détermination du content_type dynamique
                content_type = "image/png" if extension_origine == ".png" else "image/jpeg"

                try:
                    # Sécurité : Recréer le bucket si le conteneur Docker a été purgé
                    if not minio_client.bucket_exists(BUCKET_NAME):
                        minio_client.make_bucket(BUCKET_NAME)
                        print(f"   📦 Bucket '{BUCKET_NAME}' recréé à la volée.")

                    minio_client.fput_object(
                        BUCKET_NAME,
                        chemin_minio,
                        chemin_complet,
                        content_type=content_type
                    )
                    print(f"   ✅ Upload MinIO réussi : {chemin_minio}")
                except Exception as e:
                    print(f"❌ Erreur upload MinIO : {e}")
                    continue

                # --- C. NOTIFICATION MQTT VERS L'ORCHESTRATEUR ---
                message = {
                    "id_bouteille": val_id,
                    "type_bouteille": val_type,  # Transmis dynamiquement !
                    "etage": val_etage,           # Index étage (ex: 1, 2)
                    "angle": val_angle,           # Index angle (ex: 1 à 8)
                    "chemin_minio": chemin_minio,
                    "bucket": BUCKET_NAME,
                    "status": "ready_for_analysis"
                }
                envoyer_mqtt(message)

                # --- D. NETTOYAGE ---
                try:
                    os.remove(chemin_complet)
                    print("   🗑️ Fichier local supprimé.")
                except Exception as e:
                    print(f"   ⚠️ Impossible de supprimer le fichier local : {e}")

            # Petite pause pour soulager le CPU
            await asyncio.sleep(0.1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du service d'acquisition.")