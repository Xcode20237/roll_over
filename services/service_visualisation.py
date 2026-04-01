import os
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from urllib.parse import unquote

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import paho.mqtt.client as mqtt
from minio import Minio
from minio.error import S3Error
from dotenv import load_dotenv

import urllib3
urllib3.disable_warnings()

# ---------------------------------------------------------------------------
# CONFIGURATION & INITIALISATION
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="[VISUALISATION] %(asctime)s - %(message)s")
logger = logging.getLogger("visualisation")

load_dotenv()

# Configuration MQTT
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", 18830))

# Topics à écouter
TOPICS_LISTEN = [
    (os.getenv("TOPIC_ORCHESTRATEUR_ENTREE", "vision/images/new"), 0),
    (os.getenv("TOPIC_ENTREE_FUSION", "vision/ia/pretraitement"), 0),
    (os.getenv("TOPIC_SORTIE_FUSION", "vision/ia/ready"), 0),
    (os.getenv("TOPIC_ENTREE_BOUCHON", "vision/classique/bouchon"), 0),
    (os.getenv("TOPIC_SORTIE_BOUCHON", "vision/resultats/bouchon"), 0),
    (os.getenv("TOPIC_ENTREE_NIVEAU", "vision/classique/niveau"), 0),
    (os.getenv("TOPIC_SORTIE_NIVEAU", "vision/resultats/niveau"), 0),
    (os.getenv("TOPIC_ENTREE_DEFORMATION", "vision/classique/deformation"), 0),
    (os.getenv("TOPIC_SORTIE_DEFORMATION", "vision/resultats/deformation"), 0),
    (os.getenv("TOPIC_SORTIE_IA", "vision/resultats/ia"), 0),
    (os.getenv("TOPIC_SORTIE_DECISION", "vision/resultats/final"), 0),
    (os.getenv("TOPIC_ORCHESTRATEUR_STATUS", "vision/filtre/status"), 0)
]

# Configuration MinIO
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_USER = os.getenv("MINIO_USER", "admin_vision")
MINIO_PASSWORD = os.getenv("MINIO_PASSWORD", "password123")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "images-production")

# Client MinIO
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_USER,
    secret_key=MINIO_PASSWORD,
    secure=False
)

# ---------------------------------------------------------------------------
# CYCLE DE VIE DE L'APP
# ---------------------------------------------------------------------------
mqtt_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global mqtt_client
    
    # Démarrer le client MQTT en arrière plan (startup)
    loop = asyncio.get_running_loop()
    
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata={"loop": loop})
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message
    
    try:
        mqtt_client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
        mqtt_client.loop_start()
        logger.info(f"MQTT Client démarré vers {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")
    except Exception as e:
        logger.error(f"Impossible de démarrer MQTT: {e}")

    yield  # C'est ici que l'application tourne
    
    # Arrêt du client MQTT (shutdown)
    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        logger.info("MQTT Client arrêté")

# Application FastAPI
app = FastAPI(title="Roll-Over Visualisation Dashboard", lifespan=lifespan)

# CORS (si le frontend est servi sur un autre port)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Monter le répertoire statique (frontend)
# On s'assure que le chemin est relatif à la racine du projet
BASE_DIR_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR_ROOT, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ---------------------------------------------------------------------------
# GESTION DES WEBSOCKETS
# ---------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client WS connecté. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Client WS déconnecté. Total: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Erreur d'envoi WS: {e}")

manager = ConnectionManager()

# ---------------------------------------------------------------------------
# CLIENT MQTT (Tourne dans son thread/runloop)
# ---------------------------------------------------------------------------
def get_event_type_from_topic(topic: str) -> str:
    """Mappe un topic MQTT à un type d'événement pour le frontend"""
    if topic == os.getenv("TOPIC_ORCHESTRATEUR_ENTREE", "vision/images/new"):
        return "acquisition"
    elif topic == os.getenv("TOPIC_ENTREE_FUSION", "vision/ia/pretraitement"):
        return "fusion_input"
    elif topic == os.getenv("TOPIC_SORTIE_FUSION", "vision/ia/ready"):
        return "fusion_done"
    elif topic == os.getenv("TOPIC_ENTREE_BOUCHON", "vision/classique/bouchon"):
        return "input_bouchon"
    elif topic == os.getenv("TOPIC_SORTIE_BOUCHON", "vision/resultats/bouchon"):
        return "result_bouchon"
    elif topic == os.getenv("TOPIC_ENTREE_NIVEAU", "vision/classique/niveau"):
        return "input_niveau"
    elif topic == os.getenv("TOPIC_SORTIE_NIVEAU", "vision/resultats/niveau"):
        return "result_niveau"
    elif topic == os.getenv("TOPIC_ENTREE_DEFORMATION", "vision/classique/deformation"):
        return "input_deformation"
    elif topic == os.getenv("TOPIC_SORTIE_DEFORMATION", "vision/resultats/deformation"):
        return "result_deformation"
    elif topic == os.getenv("TOPIC_SORTIE_IA", "vision/resultats/ia"):
        return "result_ia"
    elif topic == os.getenv("TOPIC_SORTIE_DECISION", "vision/resultats/final"):
        return "verdict_final"
    elif topic == os.getenv("TOPIC_ORCHESTRATEUR_STATUS", "vision/filtre/status"):
        return "status_orchestrateur"
    return "unknown"

def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logger.info("✅ Connecté au Broker MQTT")
        client.subscribe(TOPICS_LISTEN)
        topics_str = ", ".join([t[0] for t in TOPICS_LISTEN])
        logger.info(f"🎧 Abonné aux topics: {topics_str}")
    else:
        logger.error(f"❌ Échec de connexion MQTT (code {rc})")

def on_mqtt_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload_str = msg.payload.decode('utf-8')
        payload = json.loads(payload_str)
        
        event_type = get_event_type_from_topic(topic)
        
        # On prépare le message global
        event = {
            "type": event_type,
            "topic": topic,
            "data": payload
        }
        
        # Envoi via WebSocket (utilise evt_loop courant de FastAPI)
        asyncio.run_coroutine_threadsafe(
            manager.broadcast(json.dumps(event)),
            userdata["loop"]
        )
        
    except json.JSONDecodeError:
        pass # Ignorer les messages non JSON (sauvegarde du dataset etc.)
    except Exception as e:
        logger.error(f"Erreur traitement MQTT: {e}")

# ---------------------------------------------------------------------------
# ENDPOINTS FASTAPI
# ---------------------------------------------------------------------------
@app.get("/")
async def get_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    return Response(content=open(index_path, "r", encoding="utf-8").read(), media_type="text/html")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Maintenir la connexion, parfois le frontend ping
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/api/image/{bucket_name}/{object_name:path}")
async def get_image(bucket_name: str, object_name: str):
    """Proxy HTTP local pour récupérer les images de MinIO sans exposer les identifiants MinIO au frontend"""
    try:
        object_name = unquote(object_name)
        response = minio_client.get_object(bucket_name, object_name)
        img_data = response.read()
        response.close()
        response.release_conn()
        return Response(content=img_data, media_type="image/jpeg")
    except S3Error as err:
        logger.error(f"Erreur MinIO: {err}")
        raise HTTPException(status_code=404, detail="Image non trouvée dans MinIO")
    except Exception as e:
        logger.error(f"Erreur lecture image: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne serveur")

if __name__ == "__main__":
    import uvicorn
    # En phase de développement avec rechargement à chaud
    # Lancement standard: uvicorn service_visualisation:app --host 0.0.0.0 --port 7343
    uvicorn.run("service_visualisation:app", host="0.0.0.0", port=7343, reload=True)
