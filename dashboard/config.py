"""
config.py — Configuration centralisée chargée depuis .env
"""
import os
from dotenv import load_dotenv
load_dotenv()

MQTT_BROKER = os.getenv("MQTT_BROKER_HOST", "localhost")
MQTT_PORT   = int(os.getenv("MQTT_BROKER_PORT", 1883))

# Base des topics de statut — doit correspondre à TOPIC_STATUS_BASE des services
_STATUS_BASE = os.getenv("TOPIC_STATUS_BASE", "vision/status/")

# Topics de statut par service (lus depuis le .env)
TOPIC_STATUS_COLORIMETRIQUE = os.getenv(
    "TOPIC_STATUS_COLORIMETRIQUE", _STATUS_BASE + "colorimetrique")
TOPIC_STATUS_GRADIENT       = os.getenv(
    "TOPIC_STATUS_GRADIENT",       _STATUS_BASE + "gradient")
TOPIC_STATUS_GEOMETRIQUE    = os.getenv(
    "TOPIC_STATUS_GEOMETRIQUE",    _STATUS_BASE + "geometrique")
TOPIC_STATUS_DECISION       = os.getenv(
    "TOPIC_STATUS_DECISION",       _STATUS_BASE + "decision")
TOPIC_STATUS_IA             = os.getenv(
    "TOPIC_STATUS_IA",             _STATUS_BASE + "ia")

TOPIC_STATUS_CHECK_POSITION = os.getenv(
    "TOPIC_STATUS_CHECK_POSITION", _STATUS_BASE + "check_position")

# Topic de sortie check_position (verdict positionnement)
TOPIC_SORTIE_CHECK_POSITION = os.getenv(
    "TOPIC_SORTIE_CHECK_POSITION", "vision/check/position")

# ── Topics visualisation temps réel ──────────────────────────────
TOPIC_VISU_COLOR_IMAGE  = os.getenv("TOPIC_VISU_COLOR_IMAGE",  "vision/visu/colorimetrique/image_brute")
TOPIC_VISU_GRAD_IMAGE   = os.getenv("TOPIC_VISU_GRAD_IMAGE",   "vision/visu/gradient/image_brute")
TOPIC_VISU_GEO_IMAGE    = os.getenv("TOPIC_VISU_GEO_IMAGE",    "vision/visu/geometrique/image_brute")
TOPIC_VISU_CHECK_IMAGE  = os.getenv("TOPIC_VISU_CHECK_IMAGE",  "vision/visu/check_position/image_brute")
TOPIC_VISU_FUSION_IMAGE = os.getenv("TOPIC_VISU_FUSION_IMAGE", "vision/visu/fusion/image_brute")
TOPIC_VISU_COLOR_TRAIT  = os.getenv("TOPIC_VISU_COLOR_TRAIT",  "vision/visu/colorimetrique/traitement")
TOPIC_VISU_GRAD_TRAIT   = os.getenv("TOPIC_VISU_GRAD_TRAIT",   "vision/visu/gradient/traitement")
TOPIC_VISU_GEO_TRAIT    = os.getenv("TOPIC_VISU_GEO_TRAIT",    "vision/visu/geometrique/traitement")
TOPIC_VISU_CHECK_TRAIT  = os.getenv("TOPIC_VISU_CHECK_TRAIT",  "vision/visu/check_position/traitement")
TOPIC_VISU_FUSION_TRAIT = os.getenv("TOPIC_VISU_FUSION_TRAIT", "vision/visu/fusion/traitement")
TOPIC_VISU_IA_TRAIT     = os.getenv("TOPIC_VISU_IA_TRAIT",     "vision/visu/ia/resultat")

TOPICS_VISU = [
    TOPIC_VISU_COLOR_IMAGE,  TOPIC_VISU_GRAD_IMAGE,  TOPIC_VISU_GEO_IMAGE,
    TOPIC_VISU_CHECK_IMAGE,  TOPIC_VISU_FUSION_IMAGE,
    TOPIC_VISU_COLOR_TRAIT,  TOPIC_VISU_GRAD_TRAIT,  TOPIC_VISU_GEO_TRAIT,
    TOPIC_VISU_CHECK_TRAIT,  TOPIC_VISU_FUSION_TRAIT, TOPIC_VISU_IA_TRAIT,
]

# Mapping topic visu → nom service
TOPIC_VISU_SERVICE = {
    TOPIC_VISU_COLOR_IMAGE  : "colorimetrique",
    TOPIC_VISU_GRAD_IMAGE   : "gradient",
    TOPIC_VISU_GEO_IMAGE    : "geometrique",
    TOPIC_VISU_CHECK_IMAGE  : "check_position",
    TOPIC_VISU_FUSION_IMAGE : "fusion",
    TOPIC_VISU_COLOR_TRAIT  : "colorimetrique",
    TOPIC_VISU_GRAD_TRAIT   : "gradient",
    TOPIC_VISU_GEO_TRAIT    : "geometrique",
    TOPIC_VISU_CHECK_TRAIT  : "check_position",
    TOPIC_VISU_FUSION_TRAIT : "fusion",
    TOPIC_VISU_IA_TRAIT     : "ia",
}

TOPICS_ECOUTE = [
    # Flux de production
    os.getenv("TOPIC_ORCHESTRATEUR_ENTREE",  "vision/images/new"),
    os.getenv("TOPIC_ENTREE_COLORIMETRIQUE", "vision/classique/colorimetrique"),
    os.getenv("TOPIC_ENTREE_GRADIENT",       "vision/classique/gradient"),
    os.getenv("TOPIC_ENTREE_GEOMETRIQUE",    "vision/classique/geometrique"),
    os.getenv("TOPIC_ENTREE_IA",             "vision/ia/pretraitement"),
    os.getenv("TOPIC_SORTIE_COLORIMETRIQUE", "vision/resultats/colorimetrique"),
    os.getenv("TOPIC_SORTIE_GRADIENT",       "vision/resultats/gradient"),
    os.getenv("TOPIC_SORTIE_GEOMETRIQUE",    "vision/resultats/geometrique"),
    os.getenv("TOPIC_SORTIE_IA",             "vision/resultats/ia"),
    os.getenv("TOPIC_SORTIE_DECISION",       "vision/resultats/final"),
    os.getenv("TOPIC_ORCHESTRATEUR_STATUS",  "vision/filtre/status"),
    # Heartbeats des services
    TOPIC_STATUS_COLORIMETRIQUE,
    TOPIC_STATUS_GRADIENT,
    TOPIC_STATUS_GEOMETRIQUE,
    TOPIC_STATUS_DECISION,
    TOPIC_STATUS_IA,
    TOPIC_STATUS_CHECK_POSITION,
    # Topics visualisation temps réel
    *TOPICS_VISU,
]

# Mapping topic → nom court
TOPIC_NOMS = {
    "vision/images/new"               : "acquisition",
    "vision/classique/colorimetrique" : "colorimetrique",
    "vision/classique/gradient"       : "gradient",
    "vision/classique/geometrique"    : "geometrique",
    "vision/ia/pretraitement"         : "ia",
    "vision/resultats/colorimetrique" : "colorimetrique",
    "vision/resultats/gradient"       : "gradient",
    "vision/resultats/geometrique"    : "geometrique",
    "vision/resultats/ia"             : "ia",
    "vision/resultats/final"          : "final",
}

SERVICE_COLORS = {
    "colorimetrique": "#3a7bd5",
    "gradient"      : "#00b09b",
    "geometrique"   : "#f7971e",
    "ia"            : "#9b59b6",
    "final"         : "#2ecc71",
}

DB_HOST     = os.getenv("DB_HOST",     "localhost")
DB_PORT     = int(os.getenv("DB_PORT", 5432))
DB_NAME     = os.getenv("DB_NAME",     "vision_system")
DB_USER     = os.getenv("DB_USER",     "admin_bdd")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password123")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_USER     = os.getenv("MINIO_USER",     "admin_vision")
MINIO_PASS     = os.getenv("MINIO_PASSWORD", "password123")
BUCKET_NAME    = os.getenv("MINIO_BUCKET",   "images-production")

DASHBOARD_HOST   = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT   = int(os.getenv("DASHBOARD_PORT", 5000))
MAX_VERDICTS     = 50
SERVICE_TIMEOUT  = float(os.getenv("SERVICE_TIMEOUT_S", 30.0))

DEFAULT_ALERT_NG_PCT = float(os.getenv("ALERT_NG_PCT", 10.0))
DEFAULT_ALERT_WINDOW = int(os.getenv("ALERT_WINDOW",   20))