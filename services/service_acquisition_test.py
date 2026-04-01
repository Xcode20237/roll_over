"""
service_acquisition_test.py
===========================
Variante TEST du service d'acquisition — SANS connexion PLC (OPC UA).

Utilisation :
    python service_acquisition_test.py

Comportement :
    - Surveille le dossier Reception_ftp_file/ comme le vrai service
    - PARSE le nom du fichier pour extraire etage et angle
      -> Convention attendue : Img_Etage{etage}_Angle{angle:03d}.png
         Ex : Img_Etage1_Angle003.png  -> etage=1, angle=3
    - ID de bouteille : auto-incremente (1, 2, 3...) a chaque cycle complet
      (quand l'ensemble des angles d'un meme etage a ete detecte)
    - Type bouteille : toujours "Type_A" (force pour les tests)
    - Upload MinIO + Notification MQTT identiques au vrai service

Optimisations v3 (contexte FTP Windows) :
    - is_file_ready() detecte le verrou Windows (WinError 32) via tentative
      d'ouverture exclusive -- instantane, sans boucle d'attente.
    - Client MQTT persistant : une seule connexion TCP reutilisee pour toutes
      les notifications, au lieu d'une connexion/deconnexion par image.
"""

import os
import re
import time
import json
from minio import Minio
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# =====================================================================
# 1. CONFIGURATION (meme .env que le vrai service)
# =====================================================================
load_dotenv()  # DOIT etre en premier pour que os.getenv() lise le .env

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_USER     = os.getenv("MINIO_USER", "admin_vision")
MINIO_PASS     = os.getenv("MINIO_PASSWORD", "password123")
BUCKET_NAME    = os.getenv("MINIO_BUCKET", "images-production")

MQTT_BROKER = os.getenv("MQTT_BROKER_HOST", "localhost")
MQTT_PORT   = int(os.getenv("MQTT_BROKER_PORT", 1883))
TOPIC_OUT   = os.getenv("TOPIC_ORCHESTRATEUR_ENTREE", "vision/images/new")

# Le dossier a surveiller (meme que le vrai service)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_path = os.getenv("RECEPTION_FTP_PATH", "./Reception_ftp_file")
if not os.path.isabs(config_path):
    DOSSIER_RECEPTION = os.path.join(BASE_DIR, config_path.replace("./", ""))
else:
    DOSSIER_RECEPTION = config_path

# Delai en secondes sans nouvelle image -> nouvelle bouteille
DELAI_NOUVEAU_CYCLE_SEC = float(os.getenv("DELAI_NOUVEAU_CYCLE_SEC", 5.0))

# --- Parametres TEST ---
TYPE_BOUTEILLE_TEST = "Type_B"   # Type fixe pour les tests

# Regex pour parser le nom de fichier
# Exemples reconnus :
#   Img_Etage1_Angle003.png   -> etage=1, angle=3
#   Img_Etage2_Angle008.png   -> etage=2, angle=8
PATTERN_NOM = re.compile(
    r"Img_Etage(\d+)_Angle(\d+)",
    re.IGNORECASE
)

# =====================================================================
# 2. UTILITAIRES
# =====================================================================
def setup_minio():
    client = Minio(MINIO_ENDPOINT, access_key=MINIO_USER, secret_key=MINIO_PASS, secure=False)
    if not client.bucket_exists(BUCKET_NAME):
        client.make_bucket(BUCKET_NAME)
        print(f"Bucket '{BUCKET_NAME}' cree.")
    else:
        print(f"Bucket '{BUCKET_NAME}' pret.")
    return client


def setup_mqtt() -> mqtt.Client:
    """
    Cree et connecte un client MQTT persistant.
    Une seule connexion TCP est maintenue pour toute la duree du service,
    evitant le cout de connect/disconnect a chaque image.
    """
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()  # thread de maintien de connexion en arriere-plan
    print(f"MQTT connecte : {MQTT_BROKER}:{MQTT_PORT}")
    return client


def envoyer_mqtt(client: mqtt.Client, payload: dict):
    """Publie un message JSON sur le topic de sortie (connexion persistante)."""
    result = client.publish(TOPIC_OUT, json.dumps(payload))
    result.wait_for_publish(timeout=3.0)
    print(f"   MQTT -> {TOPIC_OUT}")


def parser_nom_fichier(filename: str):
    """
    Extrait (etage, angle) depuis le nom de fichier.
    Retourne (None, None) si le format n'est pas reconnu.
    """
    match = PATTERN_NOM.search(filename)
    if match:
        etage = int(match.group(1))
        angle = int(match.group(2))
        return etage, angle
    return None, None


def is_file_ready(path: str) -> bool:
    """
    Detecte si le fichier est encore verrouille par le client FTP (Windows).

    Sous Windows, le client FTP (FileZilla, etc.) maintient un verrou exclusif
    sur le fichier pendant tout le transfert. Tenter de l'ouvrir en mode
    ajout ('a+b') est la methode la plus fiable pour detecter ce verrou :
    - Si le client FTP ecrit encore  -> PermissionError (WinError 32) -> False
    - Si le transfert est termine    -> ouverture reussie              -> True

    Cette approche est instantanee (pas de boucle d'attente) et sans risque :
    le mode 'a+b' n'ecrase ni ne tronque le fichier.
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    try:
        with open(path, 'a+b'):
            return True
    except (PermissionError, OSError):
        return False


# =====================================================================
# 3. GESTIONNAIRE D'ID BOUTEILLE
#    Un seul id_bouteille par "cycle" = toutes les images arrivees
#    pour une meme bouteille (groupees par proximite temporelle).
# =====================================================================
class IdManager:
    def __init__(self):
        self._compteur = 0
        self._id_courant = None
        self._derniere_image_ts = 0
        self._delai_nouveau_cycle = DELAI_NOUVEAU_CYCLE_SEC

    def get_id(self) -> int:
        """
        Retourne l'ID courant. Incremente si le delai depuis la derniere image
        depasse _delai_nouveau_cycle secondes (= nouvelle bouteille).
        """
        now = time.time()
        if self._id_courant is None or (now - self._derniere_image_ts) > self._delai_nouveau_cycle:
            self._compteur += 1
            self._id_courant = self._compteur
            print(f"\nNouvelle bouteille detectee -> ID = {self._id_courant}")
        self._derniere_image_ts = now
        return self._id_courant


# =====================================================================
# 4. BOUCLE PRINCIPALE
# =====================================================================
def main():
    print("=" * 60)
    print("SERVICE ACQUISITION - MODE TEST (Sans PLC)")
    print("=" * 60)
    print(f"   Dossier surveille  : {os.path.abspath(DOSSIER_RECEPTION)}")
    print(f"   Type bouteille fixe: {TYPE_BOUTEILLE_TEST}")
    print(f"   MinIO              : {MINIO_ENDPOINT}")
    print(f"   MQTT               : {MQTT_BROKER}:{MQTT_PORT} -> {TOPIC_OUT}")
    print(f"   Parsing nom fichier: Img_Etage{{N}}_Angle{{NNN}}.png")
    print(f"   Delai nouvelle btl : {DELAI_NOUVEAU_CYCLE_SEC:.0f}s sans image")
    print(f"   Mode transfert     : FTP Windows (detection verrou WinError 32)")
    print("=" * 60)

    # Verification du dossier
    if not os.path.exists(DOSSIER_RECEPTION):
        os.makedirs(DOSSIER_RECEPTION)
        print(f"Dossier cree : {DOSSIER_RECEPTION}")

    # Connexion MinIO
    try:
        minio_client = setup_minio()
    except Exception as e:
        print(f"Erreur MinIO : {e}")
        print("   -> Verifiez que Docker est lance (docker-compose up -d)")
        return

    # Connexion MQTT persistante
    try:
        mqtt_client = setup_mqtt()
    except Exception as e:
        print(f"Erreur MQTT : {e}")
        print("   -> Verifiez que le broker MQTT est accessible.")
        return

    id_manager = IdManager()
    print(f"\nSurveillance active sur : {os.path.abspath(DOSSIER_RECEPTION)}\n")

    try:
        while True:
            extensions = ('.jpg', '.jpeg', '.png', '.bmp')
            fichiers = sorted([
                f for f in os.listdir(DOSSIER_RECEPTION)
                if f.lower().endswith(extensions)
            ])

            for fichier in fichiers:
                chemin_complet = os.path.join(DOSSIER_RECEPTION, fichier)

                # --- A. PARSING DU NOM DE FICHIER ---
                etage, angle = parser_nom_fichier(fichier)

                if etage is None or angle is None:
                    print(f"Nom de fichier non reconnu : '{fichier}'")
                    print(f"   Format attendu : Img_Etage{{N}}_Angle{{NNN}}.png")
                    print(f"   -> Fichier ignore et supprime.")
                    try:
                        os.remove(chemin_complet)
                    except OSError:
                        pass
                    continue

                # --- A.bis VERIFICATION VERROU FTP WINDOWS ---
                # Tentative d'ouverture exclusive : si FileZilla tient encore
                # le fichier (WinError 32), on le laisse et on reviendra au
                # prochain cycle (0.2s). Instantane, sans boucle d'attente.
                if not is_file_ready(chemin_complet):
                    continue

                # Determination de l'ID bouteille (auto-incremente)
                id_btl = id_manager.get_id()
                timestamp = int(time.time())

                print(f"\nIMAGE : {fichier}")
                print(f"   -> Etage: {etage} | Angle: {angle} | ID: {id_btl} | Type: {TYPE_BOUTEILLE_TEST}")

                # --- B. UPLOAD MINIO ---
                extension_origine = os.path.splitext(fichier)[1].lower()
                if not extension_origine:
                    extension_origine = ".jpg"

                nom_final    = f"ID{id_btl}_E{etage}_A{angle}_{timestamp}{extension_origine}"
                chemin_minio = f"bouteilles_{TYPE_BOUTEILLE_TEST}/{id_btl}/{nom_final}"
                content_type = "image/png" if extension_origine == ".png" else "image/jpeg"

                try:
                    # Verification a la volee du bucket (utile si Docker a redemarre)
                    if not minio_client.bucket_exists(BUCKET_NAME):
                        minio_client.make_bucket(BUCKET_NAME)
                        print(f"   Bucket '{BUCKET_NAME}' recree a la volee.")

                    minio_client.fput_object(
                        BUCKET_NAME,
                        chemin_minio,
                        chemin_complet,
                        content_type=content_type
                    )
                    print(f"   Upload MinIO OK : {chemin_minio}")
                except Exception as e:
                    print(f"   Erreur upload MinIO : {e}")
                    continue

                # --- C. NOTIFICATION MQTT ---
                message = {
                    "id_bouteille"  : id_btl,
                    "type_bouteille": TYPE_BOUTEILLE_TEST,
                    "etage"         : etage,
                    "angle"         : angle,
                    "chemin_minio"  : chemin_minio,
                    "bucket"        : BUCKET_NAME,
                    "status"        : "ready_for_analysis",
                    "source"        : "TEST_SANS_PLC"
                }
                try:
                    envoyer_mqtt(mqtt_client, message)
                except Exception as e:
                    print(f"   Erreur MQTT : {e}")

                # --- D. NETTOYAGE ---
                try:
                    os.remove(chemin_complet)
                    print(f"   Fichier supprime.")
                except OSError as e:
                    print(f"   Suppression impossible : {e}")

            # Pause legere pour ne pas saturer le CPU
            time.sleep(0.2)

    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("\nMQTT deconnecte.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nArret du service d'acquisition TEST.")