import os
import json
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# ─── Import OPC UA (optionnel — non bloquant si non dispo) ───────────
try:
    from asyncua.sync import Client as OpcClient
    OPCUA_AVAILABLE = True
except ImportError:
    OPCUA_AVAILABLE = False

# ─── Import PostgreSQL (optionnel — non bloquant si non dispo) ────────
try:
    import psycopg2
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

# =====================================================================
# 1. CONFIGURATION GLOBALE
# =====================================================================
load_dotenv()

MQTT_BROKER = os.getenv("MQTT_BROKER_HOST", "localhost")
MQTT_PORT   = int(os.getenv("MQTT_BROKER_PORT", 1883))

# Topics d'entrée (résultats des services)
TOPIC_COLORIMETRIQUE = os.getenv("TOPIC_SORTIE_COLORIMETRIQUE", "vision/resultats/colorimetrique")
TOPIC_GRADIENT       = os.getenv("TOPIC_SORTIE_GRADIENT",       "vision/resultats/gradient")
TOPIC_GEOMETRIQUE    = os.getenv("TOPIC_SORTIE_GEOMETRIQUE",    "vision/resultats/geometrique")
TOPIC_IA             = os.getenv("TOPIC_SORTIE_IA",             "vision/resultats/ia")

# Topic de sortie (verdict final)
TOPIC_SORTIE_FINAL = os.getenv("TOPIC_SORTIE_DECISION", "vision/resultats/final")

# Dossier des recettes orchestrateur (pour savoir quels services sont actifs)
CHEMIN_RECETTES = os.getenv("CHEMIN_RECETTES_GLOBALES", "./recettes/orchestrateur_filtre/")

# Timeout (déclenché depuis la réception du 1er message)
TIMEOUT_DECISION_SEC = float(os.getenv("TIMEOUT_DECISION_SEC", 15.0))

# Heartbeat
HEARTBEAT_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL_SEC", 10.0))
TOPIC_STATUS_BASE  = os.getenv("TOPIC_STATUS_BASE", "vision/status/")
TOPIC_STATUS_DECISION = TOPIC_STATUS_BASE + "decision"

# OPC UA — Verdict PLC
PLC_URL             = os.getenv("PLC_URL", "opc.tcp://192.168.0.1:4840")
PLC_NODE_VERDICT    = os.getenv("PLC_NODE_VERDICT",    'ns=3;s="DB_Vision"."Status_OK_NG"')
PLC_NODE_ID_VERDICT = os.getenv("PLC_NODE_ID_VERDICT", 'ns=3;s="DB_Vision"."ID_Verdict"')
# Tag écrit quand check_position retourne NG — signal mauvais positionnement
PLC_NODE_POSITION_NG = os.getenv("PLC_NODE_POSITION_NG", 'ns=3;s="DB_Vision"."Position_NG"')

# Topic check_position — la décision finale s'y abonne pour écrire le tag PLC si NG
TOPIC_CHECK_POSITION = os.getenv("TOPIC_SORTIE_CHECK_POSITION", "vision/check/position")

# PostgreSQL
DB_HOST     = os.getenv("DB_HOST",     "localhost")
DB_PORT     = int(os.getenv("DB_PORT", 5432))
DB_NAME     = os.getenv("DB_NAME",     "vision_system")
DB_USER     = os.getenv("DB_USER",     "admin_bdd")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password123")


# ─── Mapping : clé recette orchestrateur → topic résultat ────────────
# Les clés correspondent aux noms d'algorithmes dans recette_Type_X.json
ALGO_VERS_TOPIC = {
    "traitement_colorimetrique": TOPIC_COLORIMETRIQUE,
    "traitement_gradient"      : TOPIC_GRADIENT,
    "traitement_geometrique"   : TOPIC_GEOMETRIQUE,
    "pretraitement_fusion_ia"  : TOPIC_IA,
    # Rétrocompatibilité avec anciennes recettes orchestrateur
    "traitement_bouchon"       : TOPIC_COLORIMETRIQUE,
    "traitement_niveau"        : TOPIC_GRADIENT,
    "traitement_deformation"   : TOPIC_GEOMETRIQUE,
}

# ─── Mapping inverse : topic → nom court pour les logs ───────────────
TOPIC_VERS_NOM = {
    TOPIC_COLORIMETRIQUE: "colorimetrique",
    TOPIC_GRADIENT      : "gradient",
    TOPIC_GEOMETRIQUE   : "geometrique",
    TOPIC_IA            : "ia",
}


# =====================================================================
# 2. GESTIONNAIRE DE RECETTES ORCHESTRATEUR
# =====================================================================
class RecetteManager:
    """
    Charge et met en cache les recettes orchestrateur par type de bouteille.
    Retourne la liste des topics à attendre selon les services actifs (actif: true).
    """
    def __init__(self, dossier: str):
        self.dossier = dossier
        self._cache: Dict[str, List[str]] = {}

    def get_topics_attendus(self, type_bouteille: str) -> List[str]:
        """
        Retourne la liste des TOPICS correspondant aux services actifs
        pour ce type de bouteille.
        """
        if type_bouteille in self._cache:
            return self._cache[type_bouteille]

        chemin = os.path.join(self.dossier, f"recette_{type_bouteille}.json")
        if not os.path.exists(chemin):
            print(f"   ⚠️ Recette orchestrateur introuvable : {chemin}")
            print(f"   ⚠️ Tous les services seront attendus par défaut.")
            return list(ALGO_VERS_TOPIC.values())

        try:
            with open(chemin, "r", encoding="utf-8") as f:
                recette = json.load(f)
        except Exception as e:
            print(f"   ❌ Erreur lecture recette {chemin} : {e}")
            return list(ALGO_VERS_TOPIC.values())

        topics_actifs = []
        for algo, cfg in recette.get("algorithmes", {}).items():
            if cfg.get("actif", False) and algo in ALGO_VERS_TOPIC:
                topics_actifs.append(ALGO_VERS_TOPIC[algo])

        noms = [TOPIC_VERS_NOM.get(t, t) for t in topics_actifs]
        print(f"   📋 Services attendus pour {type_bouteille} : {noms}")

        self._cache[type_bouteille] = topics_actifs
        return topics_actifs


# =====================================================================
# 3. CONNECTEUR POSTGRESQL
# =====================================================================
class BDDConnector:
    """Gère la sauvegarde des verdicts dans PostgreSQL."""

    def __init__(self):
        self._connexion = None
        self._initialiser()

    def _initialiser(self):
        if not PSYCOPG2_AVAILABLE:
            print("   ⚠️ psycopg2 non installé — sauvegarde BDD désactivée.")
            return
        try:
            conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT,
                dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
            )
            conn.autocommit = True
            cursor = conn.cursor()
            # Création de la table si elle n'existe pas
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS resultats_inspection (
                    id               SERIAL PRIMARY KEY,
                    id_bouteille     VARCHAR(64)  NOT NULL,
                    type_bouteille   VARCHAR(32)  NOT NULL,
                    verdict          VARCHAR(4)   NOT NULL,
                    services_evalues TEXT,
                    services_ignores TEXT,
                    details_json     TEXT,
                    raison_ng        TEXT,
                    timestamp_utc    TIMESTAMP    DEFAULT NOW()
                );
            """)
            self._connexion = conn
            print("   ✅ Base de données PostgreSQL connectée.")
        except Exception as e:
            print(f"   ⚠️ PostgreSQL non disponible : {e}")
            print(f"   ⚠️ Les verdicts ne seront pas sauvegardés en BDD.")

    def sauvegarder(self, payload: dict):
        if self._connexion is None:
            return
        try:
            cursor = self._connexion.cursor()
            cursor.execute("""
                INSERT INTO resultats_inspection
                    (id_bouteille, type_bouteille, verdict,
                     services_evalues, services_ignores,
                     details_json, raison_ng)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                str(payload.get("id_bouteille", "")),
                str(payload.get("type_bouteille", "")),
                str(payload.get("verdict", "NG")),
                json.dumps(payload.get("services_evalues", [])),
                json.dumps(payload.get("services_ignores", [])),
                json.dumps(payload.get("details", payload.get("defauts", {}))),
                payload.get("error", None)
            ))
            print(f"   📥 [BDD] Verdict de la bouteille {payload.get('id_bouteille', '?')} enregistré avec succès dans PostgreSQL.")
        except Exception as e:
            print(f"   ⚠️ Erreur BDD sauvegarde : {e}")
            # Tentative de reconnexion
            self._initialiser()


# =====================================================================
# 4. ENVOI VERDICT AU PLC (OPC UA)
# =====================================================================
def envoyer_verdict_plc(id_bouteille: str, verdict: str):
    """Envoie le verdict OK/NG au PLC via OPC UA. Non bloquant en cas d'erreur."""
    if not OPCUA_AVAILABLE:
        print("   ⚠️ asyncua non installé — verdict PLC non envoyé.")
        return
    try:
        with OpcClient(url=PLC_URL) as client:
            node_verdict = client.get_node(PLC_NODE_VERDICT)
            node_id      = client.get_node(PLC_NODE_ID_VERDICT)
            # Convention : True = OK, False = NG
            node_verdict.write_value(verdict == "OK")
            node_id.write_value(str(id_bouteille))
        print(f"   ✅ Verdict PLC envoyé : {id_bouteille} → {verdict}")
    except Exception as e:
        print(f"   ⚠️ Erreur envoi PLC (non bloquant) : {e}")


def envoyer_position_ng_plc(id_bouteille: str):
    """
    Écrit le tag PLC 'Position_NG' quand check_position retourne NG.
    Indique à l'automate un mauvais positionnement — distinct d'un défaut qualité.
    Non bloquant en cas d'erreur.
    """
    if not OPCUA_AVAILABLE:
        print("   ⚠️ asyncua non installé — tag Position_NG non écrit.")
        return
    try:
        with OpcClient(url=PLC_URL) as client:
            node_pos = client.get_node(PLC_NODE_POSITION_NG)
            node_pos.write_value(True)   # True = mauvais positionnement détecté
        print(f"   ✅ Tag Position_NG écrit : {id_bouteille}")
    except Exception as e:
        print(f"   ⚠️ Erreur écriture tag Position_NG (non bloquant) : {e}")


# =====================================================================
# 5. SERVICE DÉCISION FINALE
# =====================================================================
class DecisionFinaleService:
    """
    Agrège les résultats des services d'inspection et rend un verdict global OK/NG.

    Logique :
    ─ À la réception du 1er résultat pour une bouteille :
        → Lit la recette orchestrateur → détermine les topics attendus
        → Démarre un timer TIMEOUT_DECISION_SEC
    ─ Dès que tous les résultats attendus sont reçus :
        → Calcule le verdict → publie → PLC → BDD
    ─ Si timeout : NG avec liste des services manquants
    """

    def __init__(self):
        # buffer[id_bouteille] = {
        #   "type":     str,
        #   "attendus": [topic, ...],      ← topics à recevoir (actifs dans recette)
        #   "recus":    {topic: payload},  ← résultats déjà reçus
        #   "timer":    Timer,             ← timer timeout
        #   "timestamp": float
        # }
        self.buffer: Dict[str, dict] = {}
        self.buffer_lock = threading.Lock()

        self.recette_manager = RecetteManager(CHEMIN_RECETTES)
        self.bdd = BDDConnector()

        self.mqtt = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id="ServiceDecisionFinale"
        )
        self.mqtt.on_connect = self.on_connect
        self.mqtt.on_message = self.on_message

        threading.Thread(target=self._heartbeat, daemon=True).start()

    # ------------------------------------------------------------------
    def _heartbeat(self):
        """
        Publie le statut du service décision toutes les HEARTBEAT_INTERVAL
        secondes sur TOPIC_STATUS_DECISION.
        """
        while True:
            try:
                payload = json.dumps({
                    "service"  : "decision",
                    "status"   : "OK",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                })
                self.mqtt.publish(TOPIC_STATUS_DECISION, payload)
            except Exception:
                pass
            time.sleep(HEARTBEAT_INTERVAL)

    # ------------------------------------------------------------------
    def on_connect(self, client, userdata, flags, rc):
        print(f"✅ Connecté MQTT (code: {rc})")
        # On souscrit à TOUS les topics résultats (filtrage dynamique ensuite)
        topics = [
            (TOPIC_COLORIMETRIQUE,  0),
            (TOPIC_GRADIENT,        0),
            (TOPIC_GEOMETRIQUE,     0),
            (TOPIC_IA,              0),
            (TOPIC_CHECK_POSITION,  0),   # pour écrire le tag PLC si NG positionnement
        ]
        self.mqtt.subscribe(topics)
        for t, _ in topics:
            print(f"🎧 Écoute : {t}")

    # ------------------------------------------------------------------
    def on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
            id_bouteille   = str(payload["id_bouteille"])
            type_bouteille = str(payload["type_bouteille"])
        except (json.JSONDecodeError, KeyError) as e:
            print(f"❌ Payload invalide sur {topic} : {e}")
            return

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
            id_bouteille   = str(payload["id_bouteille"])
            type_bouteille = str(payload["type_bouteille"])
        except (json.JSONDecodeError, KeyError) as e:
            print(f"❌ Payload invalide sur {topic} : {e}")
            return

        # ── Verdict check_position — écriture tag PLC si NG ───────────
        if topic == TOPIC_CHECK_POSITION:
            verdict_check = payload.get("verdict_global", payload.get("status", "NG"))
            if verdict_check == "NG":
                print(f"\n⚠️ CHECK POSITION NG [{id_bouteille}] — "
                      f"écriture tag PLC mauvais positionnement")
                threading.Thread(
                    target=envoyer_position_ng_plc,
                    args=(id_bouteille,),
                    daemon=True
                ).start()
            return   # Le check_position ne participe pas au verdict qualité

        nom_service = TOPIC_VERS_NOM.get(topic, topic)

        data_snapshot = None  # ← initialisé avant le verrou

        with self.buffer_lock:
            # ── Première arrivée pour cette bouteille ──────────────────
            if id_bouteille not in self.buffer:
                topics_attendus = self.recette_manager.get_topics_attendus(type_bouteille)

                # Timer timeout déclenché dès maintenant
                timer = threading.Timer(
                    TIMEOUT_DECISION_SEC,
                    self._timeout_callback,
                    args=(id_bouteille,)
                )
                timer.daemon = True
                timer.start()

                self.buffer[id_bouteille] = {
                    "type":      type_bouteille,
                    "attendus":  topics_attendus,
                    "recus":     {},
                    "timer":     timer,
                    "timestamp": time.time()
                }
                noms_attendus = [TOPIC_VERS_NOM.get(t, t) for t in topics_attendus]
                print(f"\n📥 [{id_bouteille}] Premier résultat reçu ({nom_service})")
                print(f"   ⏳ Attente : {noms_attendus} (timeout {TIMEOUT_DECISION_SEC}s)")

            data = self.buffer[id_bouteille]

            # ── Vérifier si ce topic est attendu pour cette bouteille ──
            if topic not in data["attendus"]:
                print(f"   ℹ️ [{id_bouteille}] Service '{nom_service}' ignoré (inactif dans la recette)")
                return

            # Vérifier doublon
            if topic in data["recus"]:
                print(f"   ⚠️ [{id_bouteille}] Doublon ignoré pour '{nom_service}'")
                return

            # Stocker le résultat
            data["recus"][topic] = payload
            recus_noms = [TOPIC_VERS_NOM.get(t, t) for t in data["recus"]]
            attendus_noms = [TOPIC_VERS_NOM.get(t, t) for t in data["attendus"]]
            print(f"   ✅ [{id_bouteille}] Reçu '{nom_service}' | {len(data['recus'])}/{len(data['attendus'])} : {recus_noms}")

            # ── Déclenchement si tous les services attendus ont répondu ──
            if set(data["recus"].keys()) >= set(data["attendus"]):
                data["timer"].cancel()  # Annule le timeout
                data_snapshot = dict(data)
                del self.buffer[id_bouteille]

        # Traitement hors verrou — uniquement si grille complète
        if data_snapshot is not None:
            threading.Thread(
                target=self._conclure,
                args=(id_bouteille, data_snapshot, False),
                daemon=True
            ).start()

    # ------------------------------------------------------------------
    def _timeout_callback(self, id_bouteille: str):
        """Appelé si tous les résultats attendus ne sont pas arrivés à temps."""
        with self.buffer_lock:
            data = self.buffer.pop(id_bouteille, None)

        if data is None:
            return  # Déjà traité normalement

        manquants = [
            TOPIC_VERS_NOM.get(t, t)
            for t in data["attendus"]
            if t not in data["recus"]
        ]
        print(f"\n⏰ TIMEOUT [{id_bouteille}] — Services manquants : {manquants}")
        self._conclure(id_bouteille, data, timeout=True)

    # ------------------------------------------------------------------
    def _conclure(self, id_bouteille: str, data: dict, timeout: bool):
        """
        Calcule le verdict final, publie sur MQTT, envoie au PLC et sauvegarde en BDD.
        """
        type_bouteille  = data["type"]
        attendus_topics = data["attendus"]
        recus           = data["recus"]

        # ── Construction des détails et du verdict ────────────────────
        verdict         = "OK"
        details         = {}
        raison_ng       = None
        ids_defauts_ng  = []   # collecte de tous les id_defaut NG pour raison_ng

        for topic in attendus_topics:
            nom = TOPIC_VERS_NOM.get(topic, topic)
            if topic in recus:
                payload_svc = recus[topic]
                # Lecture verdict — nouveau format "verdict_global", fallback "status"
                statut  = (payload_svc.get("verdict_global")
                           or payload_svc.get("status", "NG"))
                # Défauts bruts — liste avec mesures / tolérances / écarts
                defauts = payload_svc.get("defauts",
                          payload_svc.get("details", []))

                details[nom] = {
                    "status" : statut,
                    "defauts": defauts,
                }

                if statut == "NG":
                    verdict = "NG"
                    # Extraire les id_defaut NG pour construire raison_ng
                    if isinstance(defauts, list):
                        for d in defauts:
                            if isinstance(d, dict) and d.get("verdict") == "NG":
                                ids_defauts_ng.append(
                                    f"{d.get('id_defaut','?')} ({d.get('label','')})"
                                )
            else:
                # Service attendu mais non reçu (timeout)
                details[nom] = {
                    "status" : "NG",
                    "defauts": [{"error": "TIMEOUT_NON_RECU"}],
                }
                verdict   = "NG"
                ids_defauts_ng.append(f"TIMEOUT_{nom.upper()}")

        if timeout and not ids_defauts_ng:
            ids_defauts_ng.append("TIMEOUT_RESULTATS_MANQUANTS")

        # Construire raison_ng lisible depuis tous les défauts NG collectés
        raison_ng = ", ".join(ids_defauts_ng) if ids_defauts_ng else None

        # ── Services non attendus (inactifs) ───────────────────────────
        # Dédoublonnage : ALGO_VERS_TOPIC contient des alias rétrocompat.
        tous_topics = {TOPIC_COLORIMETRIQUE, TOPIC_GRADIENT,
                       TOPIC_GEOMETRIQUE, TOPIC_IA}
        ignores_topics  = tous_topics - set(attendus_topics)
        evalues_noms = [TOPIC_VERS_NOM.get(t, t) for t in attendus_topics]
        ignores_noms = [TOPIC_VERS_NOM.get(t, t) for t in ignores_topics]

        # ── Log de conclusion ─────────────────────────────────────────
        icone = "✅" if verdict == "OK" else "❌"
        print(f"\n{icone} VERDICT FINAL [{id_bouteille}] : {verdict}")
        print(f"   Évalués : {evalues_noms}")
        print(f"   Ignorés : {ignores_noms}")
        for nom, res in details.items():
            print(f"   {nom:12s} → {res['status']}")
        if raison_ng:
            print(f"   ⚠️ Raison NG : {raison_ng}")

        # ── Payload de sortie ─────────────────────────────────────────
        payload_final = {
            "id_bouteille":    id_bouteille,
            "type_bouteille":  type_bouteille,
            "verdict":         verdict,
            "services_evalues": evalues_noms,
            "services_ignores": ignores_noms,
            "details":         details,
            "error":           raison_ng,
            "timestamp":       datetime.utcnow().isoformat() + "Z"
        }

        # ── 1. Publication MQTT ───────────────────────────────────────
        self.mqtt.publish(TOPIC_SORTIE_FINAL, json.dumps(payload_final))
        print(f"   📤 Publié sur {TOPIC_SORTIE_FINAL}")

        # ── 2. PLC (non bloquant) ─────────────────────────────────────
        threading.Thread(
            target=envoyer_verdict_plc,
            args=(id_bouteille, verdict),
            daemon=True
        ).start()

        # ── 3. Base de données ────────────────────────────────────────
        self.bdd.sauvegarder(payload_final)

    # ------------------------------------------------------------------
    def run(self):
        self.mqtt.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        self.mqtt.loop_forever()


# =====================================================================
# 6. POINT D'ENTRÉE
# =====================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("⚖️  MICRO-SERVICE : DÉCISION FINALE OK/NG")
    print("=" * 60)
    print(f"   Timeout décision : {TIMEOUT_DECISION_SEC}s")
    print(f"   Recettes         : {CHEMIN_RECETTES}")
    print(f"   PostgreSQL       : {'✅ disponible' if PSYCOPG2_AVAILABLE else '❌ psycopg2 manquant'}")
    print(f"   OPC UA           : {'✅ disponible' if OPCUA_AVAILABLE else '❌ asyncua manquant'}")
    service = DecisionFinaleService()
    service.run()