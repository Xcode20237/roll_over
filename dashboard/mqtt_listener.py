"""
mqtt_listener.py
----------------
Thread MQTT qui écoute tous les topics du système et met à jour
le StateManager. Émet des événements SocketIO vers les clients web.
"""
from __future__ import annotations
import json
import threading
import time
from typing import TYPE_CHECKING

import paho.mqtt.client as mqtt

from config import (MQTT_BROKER, MQTT_PORT, TOPICS_ECOUTE, TOPIC_NOMS,
                   TOPIC_STATUS_COLORIMETRIQUE, TOPIC_STATUS_GRADIENT,
                   TOPIC_STATUS_GEOMETRIQUE, TOPIC_STATUS_DECISION,
                   TOPIC_STATUS_IA, TOPIC_STATUS_CHECK_POSITION,
                   TOPIC_SORTIE_CHECK_POSITION,
                   TOPICS_VISU, TOPIC_VISU_SERVICE)
from state_manager import state

if TYPE_CHECKING:
    from flask_socketio import SocketIO


class MQTTListener:

    def __init__(self, socketio=None):
        self._sio    = socketio
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id="DashboardListener",
        )
        self._client.on_connect    = self._on_connect
        self._client.on_message    = self._on_message
        self._client.on_disconnect = self._on_disconnect
        self._connected = False

    def set_socketio(self, socketio):
        self._sio = socketio

    # ──────────────────────────────────────────────────────────────────
    # MQTT callbacks
    # ──────────────────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            print(f"[MQTT] Connecté au broker {MQTT_BROKER}:{MQTT_PORT}")
            for topic in TOPICS_ECOUTE:
                client.subscribe(topic, qos=0)
            self._emit("mqtt_status", {"connecte": True})
        else:
            print(f"[MQTT] Echec connexion broker (code {rc})")
            self._emit("mqtt_status", {"connecte": False})

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        print(f"[MQTT] Déconnecté du broker (code {rc})")
        self._emit("mqtt_status", {"connecte": False})

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            topic   = msg.topic
            self._router(topic, payload)
        except Exception as e:
            print(f"[MQTT] Erreur traitement message sur {msg.topic}: {e}")

    # ──────────────────────────────────────────────────────────────────
    # Routage des messages
    # ──────────────────────────────────────────────────────────────────

    def _router(self, topic: str, payload: dict):
        """Dispatche chaque message selon son topic."""

        # ── Nouvelle bouteille (orchestrateur) ────────────────────────
        if topic == "vision/images/new":
            id_btl   = str(payload.get("id_bouteille", "?"))
            type_btl = str(payload.get("type_bouteille", "?"))
            state.marquer_activite("orchestrateur")
            state.nouvelle_bouteille(
                id_btl, type_btl,
                ["colorimetrique", "gradient", "geometrique", "ia"]
            )
            self._emit("bouteille_active", state.get_bouteille_active())
            self._emit("services_update", state.get_services_snapshot())

        # ── Résultat d'un service classique ───────────────────────────
        elif topic.startswith("vision/resultats/") and topic != "vision/resultats/final":
            service = TOPIC_NOMS.get(topic, topic.split("/")[-1])
            state.service_recu(service, payload)
            state.marquer_activite(service)
            # On ne stocke dans visu_recu que si aucune visu traitement
            # n'a déjà été reçue pour cette bouteille (la visu traitement
            # contient les chemins d'images — le topic resultats non)
            current_visu = state.get_derniere_visu(service)
            id_btl = str(payload.get("id_bouteille", "?"))
            if current_visu is None or current_visu.get("id_bouteille") != id_btl:
                state.visu_recu(service, payload)
            self._emit("service_recu", {
                "service"     : service,
                "id_bouteille": id_btl,
                "verdict"     : payload.get("verdict_global", "?"),
            })
            # Émettre l'événement visualisation vers le dashboard
            self._emit("visu_update", {
                "service"       : service,
                "id_bouteille"  : id_btl,
                "type_bouteille": payload.get("type_bouteille", "?"),
                "verdict_global": payload.get("verdict_global", "?"),
                "timestamp"     : payload.get("timestamp", ""),
                "defauts"       : [
                    {
                        "id_defaut"    : d.get("id_defaut"),
                        "label"        : d.get("label"),
                        "verdict"      : d.get("verdict"),
                        "mesure"       : d.get("mesure"),
                        "reference"    : d.get("reference"),
                        "tolerance"    : d.get("tolerance"),
                        "ecart"        : d.get("ecart"),
                        "details"      : d.get("details", {}),
                        "visualisation": d.get("visualisation", {}),
                    }
                    for d in payload.get("defauts", [])
                ],
            })
            self._emit("bouteille_active", state.get_bouteille_active())
            self._emit("services_update",  state.get_services_snapshot())

        # ── Verdict final ─────────────────────────────────────────────
        elif topic == "vision/resultats/final":
            state.verdict_final(payload)
            state.marquer_activite("decision")
            self._emit("verdict_final",    payload)
            self._emit("bouteille_active", None)
            self._emit("verdicts_update",  state.get_verdicts())
            self._emit("stats_update",     state.get_stats_snapshot())
            self._emit("services_update",  state.get_services_snapshot())
            # Envoyer les alertes actives
            alertes = state.get_alertes_actives()
            self._emit("alertes_update", alertes)

        # ── Heartbeat orchestrateur ───────────────────────────────────
        elif topic == "vision/filtre/status":
            state.marquer_activite("orchestrateur")
            self._emit("services_update", state.get_services_snapshot())

        # ── Verdict check_position ────────────────────────────────────
        elif topic == TOPIC_SORTIE_CHECK_POSITION:
            state.check_position_recu(payload)
            verdict_check = payload.get("verdict_global",
                                        payload.get("status", "NG"))
            self._emit("check_position_update", {
                "verdict"     : verdict_check,
                "ecart_px"    : payload.get("ecart_position_px", 0.0),
                "id_bouteille": payload.get("id_bouteille", "?"),
                "timestamp"   : payload.get("timestamp", ""),
            })
            self._emit("services_update", state.get_services_snapshot())
            # Si NG → envoyer aussi une alerte immédiate
            if verdict_check == "NG":
                self._emit("alertes_update", state.get_alertes_actives())

        # ── Topics visualisation temps réel ──────────────────────────
        elif topic in TOPIC_VISU_SERVICE:
            service = TOPIC_VISU_SERVICE[topic]
            phase   = payload.get("phase", "")

            if phase == "image_brute":
                # Image reçue dans le buffer — remplace le spinner
                state.visu_image_brute_recu(service, payload)
                self._emit("visu_image_brute", {
                    "service"       : service,
                    "id_bouteille"  : payload.get("id_bouteille"),
                    "type_bouteille": payload.get("type_bouteille"),
                    "id_defaut"     : payload.get("id_defaut"),
                    "label_defaut"  : payload.get("label_defaut"),
                    "algo"          : payload.get("algo"),
                    "etage"         : payload.get("etage"),
                    "angle"         : payload.get("angle"),
                    "angles_requis" : payload.get("angles_requis", []),
                    "angles_recus"  : payload.get("angles_recus", []),
                    "chemin_brute"  : payload.get("chemin_brute", ""),
                    # fusion spécifique
                    "nb_images_recues"   : payload.get("nb_images_recues"),
                    "nb_images_attendues": payload.get("nb_images_attendues"),
                    "timestamp"     : payload.get("timestamp"),
                })

            elif phase == "traitement":
                # Inspection terminée — afficher les steps + verdict
                state.visu_recu(service, payload)
                if service in ("fusion", "ia"):
                    # Payload simplifié pour fusion/IA
                    self._emit("visu_traitement", {
                        "service"       : service,
                        "id_bouteille"  : payload.get("id_bouteille"),
                        "type_bouteille": payload.get("type_bouteille"),
                        "verdict_global": payload.get("verdict_global"),
                        "chemin_fusion" : payload.get("chemin_fusion"),
                        "chemin_brute"  : payload.get("chemin_brute"),
                        "chemin_annote" : payload.get("chemin_annote"),
                        "detections"    : payload.get("detections", []),
                        "nb_images"     : payload.get("nb_images"),
                        "timestamp"     : payload.get("timestamp"),
                    })
                else:
                    # Services classiques — defauts avec angles_visu
                    self._emit("visu_traitement", {
                        "service"       : service,
                        "id_bouteille"  : payload.get("id_bouteille"),
                        "type_bouteille": payload.get("type_bouteille"),
                        "verdict_global": payload.get("verdict_global"),
                        "defauts"       : payload.get("defauts", []),
                        "timestamp"     : payload.get("timestamp"),
                    })

        # ── Heartbeats des services ───────────────────────────────────
        elif topic in (TOPIC_STATUS_COLORIMETRIQUE, TOPIC_STATUS_GRADIENT,
                       TOPIC_STATUS_GEOMETRIQUE, TOPIC_STATUS_DECISION,
                       TOPIC_STATUS_IA, TOPIC_STATUS_CHECK_POSITION):
            service = payload.get("service") or topic.rsplit("/", 1)[-1]
            state.marquer_activite(service)
            self._emit("services_update", state.get_services_snapshot())

        # ── Images routées vers services (activité) ───────────────────
        elif topic.startswith("vision/classique/") or \
             topic.startswith("vision/ia/"):
            service = TOPIC_NOMS.get(topic, topic.split("/")[-1])
            state.marquer_activite(service)
            self._emit("services_update", state.get_services_snapshot())

    # ──────────────────────────────────────────────────────────────────
    # Émission SocketIO (thread-safe)
    # ──────────────────────────────────────────────────────────────────

    def _emit(self, event: str, data):
        if self._sio is not None:
            try:
                self._sio.emit(event, data)
            except Exception:
                pass  # Client déconnecté — non bloquant

    # ──────────────────────────────────────────────────────────────────
    # Démarrage
    # ──────────────────────────────────────────────────────────────────

    def start(self):
        """Démarre le listener MQTT dans un thread daemon."""
        def _run():
            while True:
                try:
                    self._client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                    self._client.loop_forever()
                except Exception as e:
                    print(f"[MQTT] Reconnexion dans 5s... ({e})")
                    self._connected = False
                    time.sleep(5)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        print(f"[MQTT] Listener démarré → {MQTT_BROKER}:{MQTT_PORT}")