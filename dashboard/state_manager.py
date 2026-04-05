"""
state_manager.py
----------------
État global thread-safe du dashboard.
Centralise toutes les données partagées entre le listener MQTT,
le serveur Flask et les WebSockets.
"""
from __future__ import annotations
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from config import MAX_VERDICTS, SERVICE_TIMEOUT, DEFAULT_ALERT_NG_PCT, DEFAULT_ALERT_WINDOW


class StateManager:

    def __init__(self):
        self._lock = threading.Lock()

        # ── Bouteille en cours ────────────────────────────────────────
        # Une seule bouteille à la fois
        self.bouteille_active : Optional[Dict] = None
        # {
        #   "id"         : "BTL_001",
        #   "type"       : "Type_A",
        #   "timestamp"  : float,
        #   "services"   : {
        #       "colorimetrique": "en_attente"|"recu"|"non_concerne",
        #       "gradient"      : ...,
        #       "geometrique"   : ...,
        #       "ia"            : ...,
        #   },
        #   "resultats_services": {
        #       "colorimetrique": {...payload...},
        #   }
        # }

        # ── Verdicts (50 derniers) ────────────────────────────────────
        self.verdicts : deque = deque(maxlen=MAX_VERDICTS)
        # Chaque verdict = payload final enrichi

        # ── État des services ─────────────────────────────────────────
        self.services : Dict[str, Dict] = {
            "colorimetrique" : {"statut": "inconnu", "derniere_activite": 0.0, "latences": deque(maxlen=20)},
            "gradient"       : {"statut": "inconnu", "derniere_activite": 0.0, "latences": deque(maxlen=20)},
            "geometrique"    : {"statut": "inconnu", "derniere_activite": 0.0, "latences": deque(maxlen=20)},
            "ia"             : {"statut": "inconnu", "derniere_activite": 0.0, "latences": deque(maxlen=20)},
            "orchestrateur"  : {"statut": "inconnu", "derniere_activite": 0.0, "latences": deque(maxlen=20)},
            "decision"       : {"statut": "inconnu", "derniere_activite": 0.0, "latences": deque(maxlen=20)},
            "check_position" : {"statut": "inconnu", "derniere_activite": 0.0, "latences": deque(maxlen=20)},
        }

        # ── Dernier verdict check_position ────────────────────────────
        # Stocké séparément car il n'entre pas dans le verdict qualité
        self.last_check_position: Dict = {
            "verdict"  : None,    # "OK" | "NG" | None
            "ecart_px" : 0.0,
            "timestamp": None,
            "id_bouteille": None,
        }

        # ── Statistiques du jour ──────────────────────────────────────
        self.stats = {
            "total"          : 0,
            "ok"             : 0,
            "ng"             : 0,
            "temps_traitement": deque(maxlen=100),   # derniers temps
            "par_type"       : {},   # {Type_A: {total, ok, ng}}
            "par_defaut"     : {},   # {D2.1: {total, ng}}
            "historique_taux": deque(maxlen=96),     # 24h par tranches 15min
            "debut_journee"  : datetime.now().replace(
                                   hour=0, minute=0, second=0, microsecond=0
                               ).isoformat(),
        }

        # ── Alertes actives ───────────────────────────────────────────
        self.alertes : List[Dict] = []
        # {id, type, message, timestamp, acquittee}

        # ── Config alertes (modifiable depuis UI) ─────────────────────
        self.config_alertes = {
            "ng_seuil_pct" : DEFAULT_ALERT_NG_PCT,
            "ng_fenetre"   : DEFAULT_ALERT_WINDOW,
            "son_actif"    : True,
        }

        # ── Compteur alertes pour IDs uniques ─────────────────────────
        self._alerte_counter = 0

        # ── Visualisations temps réel par service ─────────────────────
        # Stocke pour chaque service :
        #   - la dernière session complète (traitement reçu)
        #   - les images brutes en cours (avant traitement)
        # Clé = SERVICE_NAME
        self.visualisations : Dict[str, Optional[Dict]] = {
            "colorimetrique" : None,
            "gradient"       : None,
            "geometrique"    : None,
            "check_position" : None,
            "fusion"         : None,
            "ia"             : None,
        }
        # Buffer images brutes en cours d'accumulation par service
        # { service: { id_bouteille: { id_defaut: { angle: payload_image_brute } } } }
        self.visu_buffer_brut : Dict[str, Dict] = {
            svc: {} for svc in self.visualisations
        }

        # Thread watchdog services
        threading.Thread(target=self._watchdog_services,
                         daemon=True).start()
        # Thread stats toutes les 15min
        threading.Thread(target=self._archiver_taux,
                         daemon=True).start()

    # ──────────────────────────────────────────────────────────────────
    # Bouteille active
    # ──────────────────────────────────────────────────────────────────

    def nouvelle_bouteille(self, id_btl: str, type_btl: str,
                            services_attendus: List[str]):
        with self._lock:
            self.bouteille_active = {
                "id"                  : id_btl,
                "type"                : type_btl,
                "timestamp"           : time.time(),
                "services_attendus"   : services_attendus,
                "services"            : {s: "en_attente" for s in services_attendus},
                "resultats_services"  : {},
            }

    def service_recu(self, service: str, payload: dict):
        """Marque un service comme reçu pour la bouteille active."""
        with self._lock:
            if self.bouteille_active is None:
                return
            if service in self.bouteille_active["services"]:
                self.bouteille_active["services"][service] = "recu"
                self.bouteille_active["resultats_services"][service] = payload

            # Mise à jour latence service
            if service in self.services:
                debut = self.bouteille_active["timestamp"]
                latence_ms = (time.time() - debut) * 1000
                self.services[service]["latences"].append(latence_ms)
                self.services[service]["derniere_activite"] = time.time()
                self.services[service]["statut"] = "connecte"

    def check_position_recu(self, payload: dict):
        """
        Enregistre le verdict check_position.
        Crée une alerte spécifique si NG — distincte des alertes qualité.
        """
        verdict      = payload.get("verdict_global", payload.get("status", "NG"))
        ecart_px     = float(payload.get("ecart_position_px", 0.0))
        id_bouteille = str(payload.get("id_bouteille", "?"))

        with self._lock:
            self.last_check_position = {
                "verdict"     : verdict,
                "ecart_px"    : ecart_px,
                "timestamp"   : datetime.now().strftime("%H:%M:%S"),
                "id_bouteille": id_bouteille,
            }
            self.services["check_position"]["derniere_activite"] = time.time()
            self.services["check_position"]["statut"] = "connecte"

            if verdict == "NG":
                # Alerte positionnement — type distinct pour affichage spécifique
                existe = any(
                    a["type"] == "position_ng" and not a["acquittee"]
                    for a in self.alertes
                )
                if not existe:
                    self._creer_alerte(
                        "position_ng",
                        f"⚠️ Mauvais positionnement bouteille {id_bouteille} "
                        f"— Écart : {ecart_px:+.1f} px",
                    )

    def get_check_position(self) -> Dict:
        """Retourne le dernier verdict check_position."""
        with self._lock:
            return dict(self.last_check_position)

    # ──────────────────────────────────────────────────────────────────
    # Visualisations temps réel
    # ──────────────────────────────────────────────────────────────────

    def visu_image_brute_recu(self, service: str, payload: dict):
        """
        Stocke une image brute reçue dans le buffer de visualisation.
        Appelé dès qu'une image entre dans le garbage du service.
        """
        with self._lock:
            if service not in self.visu_buffer_brut:
                return
            id_btl    = str(payload.get("id_bouteille", "?"))
            id_defaut = payload.get("id_defaut", "?")
            angle     = payload.get("angle")

            if id_btl not in self.visu_buffer_brut[service]:
                self.visu_buffer_brut[service][id_btl] = {}
            if id_defaut not in self.visu_buffer_brut[service][id_btl]:
                self.visu_buffer_brut[service][id_btl][id_defaut] = {}
            if angle is not None:
                self.visu_buffer_brut[service][id_btl][id_defaut][str(angle)] = {
                    "chemin_brute"  : payload.get("chemin_brute", ""),
                    "angles_requis" : payload.get("angles_requis", []),
                    "angles_recus"  : payload.get("angles_recus", []),
                }

    def visu_recu(self, service: str, payload: dict):
        """
        Stocke le résultat traitement complet pour un service.
        Réinitialise le buffer brut de cette bouteille.
        """
        with self._lock:
            if service not in self.visualisations:
                return
            id_btl = str(payload.get("id_bouteille", "?"))
            self.visualisations[service] = {
                "id_bouteille"  : id_btl,
                "type_bouteille": payload.get("type_bouteille"),
                "timestamp"     : payload.get("timestamp"),
                "verdict_global": payload.get("verdict_global"),
                "service"       : service,
                "defauts"       : payload.get("defauts", []),
                # Pour fusion et IA
                "chemin_brute"  : payload.get("chemin_brute"),
                "chemin_fusion" : payload.get("chemin_fusion"),
                "chemins_sources": payload.get("chemins_sources", []),
                "chemin_annote" : payload.get("chemin_annote"),
                "detections"    : payload.get("detections", []),
                "nb_images"     : payload.get("nb_images"),
            }
            # Nettoyer le buffer brut de cette bouteille
            if service in self.visu_buffer_brut:
                self.visu_buffer_brut[service].pop(id_btl, None)

    def get_derniere_visu(self, service: str) -> Optional[Dict]:
        """Retourne la dernière visualisation traitement pour un service."""
        with self._lock:
            return self.visualisations.get(service)

    def get_visu_buffer_brut(self, service: str,
                              id_bouteille: str) -> Optional[Dict]:
        """Retourne le buffer d'images brutes en cours pour un service/bouteille."""
        with self._lock:
            return self.visu_buffer_brut.get(service, {}).get(id_bouteille)
        """Enregistre le verdict final et met à jour les stats."""
        with self._lock:
            # Enrichir avec temps de traitement
            if self.bouteille_active:
                duree = round(time.time() - self.bouteille_active["timestamp"], 2)
                payload["duree_s"] = duree
                self.stats["temps_traitement"].append(duree)
            else:
                payload["duree_s"] = None

            # Ajouter timestamp lisible
            payload["timestamp_display"] = datetime.now().strftime("%H:%M:%S")

            # Stocker dans les verdicts récents
            self.verdicts.appendleft(payload)

            # Mise à jour stats
            self._update_stats(payload)

            # Mise à jour service decision
            self.services["decision"]["derniere_activite"] = time.time()
            self.services["decision"]["statut"] = "connecte"

            # Réinitialiser la bouteille active
            self.bouteille_active = None

        # Vérifier alertes (hors lock)
        self._verifier_alertes()

    # ──────────────────────────────────────────────────────────────────
    # Statistiques
    # ──────────────────────────────────────────────────────────────────

    def verdict_final(self, payload: dict):
        """Enregistre le verdict final et met à jour les stats."""
        with self._lock:
            if self.bouteille_active:
                duree = round(time.time() - self.bouteille_active["timestamp"], 2)
                payload["duree_s"] = duree
                self.stats["temps_traitement"].append(duree)
            else:
                payload["duree_s"] = None

            payload["timestamp_display"] = datetime.now().strftime("%H:%M:%S")
            self.verdicts.appendleft(payload)
            self._update_stats(payload)
            self.services["decision"]["derniere_activite"] = time.time()
            self.services["decision"]["statut"] = "connecte"
            self.bouteille_active = None

        self._verifier_alertes()

    def _update_stats(self, payload: dict):
        """Met à jour les stats globales. Appelé sous _lock."""
        verdict  = payload.get("verdict", payload.get("verdict_global", "NG"))
        type_btl = payload.get("type_bouteille", "?")

        self.stats["total"] += 1
        if verdict == "OK":
            self.stats["ok"] += 1
        else:
            self.stats["ng"] += 1

        # Par type
        if type_btl not in self.stats["par_type"]:
            self.stats["par_type"][type_btl] = {"total": 0, "ok": 0, "ng": 0}
        self.stats["par_type"][type_btl]["total"] += 1
        self.stats["par_type"][type_btl]["ok" if verdict == "OK" else "ng"] += 1

        # Par défaut (si NG)
        if verdict == "NG":
            defauts = payload.get("defauts", [])
            for d in defauts:
                if isinstance(d, dict) and d.get("verdict") == "NG":
                    did = d.get("id_defaut", "?")
                    if did not in self.stats["par_defaut"]:
                        self.stats["par_defaut"][did] = {
                            "label": d.get("label", did), "ng": 0
                        }
                    self.stats["par_defaut"][did]["ng"] += 1

    def get_stats_snapshot(self) -> dict:
        """Retourne une copie thread-safe des stats."""
        with self._lock:
            total = self.stats["total"]
            ok    = self.stats["ok"]
            ng    = self.stats["ng"]
            taux_ok = round(100 * ok / total, 1) if total > 0 else 0.0
            taux_ng = round(100 * ng / total, 1) if total > 0 else 0.0

            temps = list(self.stats["temps_traitement"])
            tps_moyen = round(sum(temps) / len(temps), 2) if temps else 0.0

            cadence = 0.0
            if len(self.verdicts) >= 2:
                t_recent = [v for v in self.verdicts
                            if "duree_s" in v][:10]
                if len(t_recent) >= 2:
                    # Approximation cadence sur les 10 derniers
                    cadence = round(60 / tps_moyen, 1) if tps_moyen > 0 else 0.0

            return {
                "total"         : total,
                "ok"            : ok,
                "ng"            : ng,
                "taux_ok"       : taux_ok,
                "taux_ng"       : taux_ng,
                "tps_moyen"     : tps_moyen,
                "cadence"       : cadence,
                "par_type"      : dict(self.stats["par_type"]),
                "par_defaut"    : dict(self.stats["par_defaut"]),
                "historique_taux": list(self.stats["historique_taux"]),
                "debut_journee" : self.stats["debut_journee"],
            }

    def _archiver_taux(self):
        """Archive le taux NG toutes les 15 minutes pour le graphique."""
        while True:
            time.sleep(900)  # 15 min
            with self._lock:
                total = self.stats["total"]
                ng    = self.stats["ng"]
                taux  = round(100 * ng / total, 1) if total > 0 else 0.0
                self.stats["historique_taux"].append({
                    "heure": datetime.now().strftime("%H:%M"),
                    "taux_ng": taux,
                    "total"  : total,
                })

    # ──────────────────────────────────────────────────────────────────
    # État des services
    # ──────────────────────────────────────────────────────────────────

    def marquer_activite(self, service: str):
        with self._lock:
            if service in self.services:
                self.services[service]["derniere_activite"] = time.time()
                self.services[service]["statut"] = "connecte"

    def get_services_snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            result = {}
            for nom, data in self.services.items():
                latences = list(data["latences"])
                lat_moy  = round(sum(latences)/len(latences), 0) \
                           if latences else None
                derniere = data["derniere_activite"]
                if derniere == 0:
                    statut = "inconnu"
                elif now - derniere > SERVICE_TIMEOUT:
                    statut = "deconnecte"
                else:
                    statut = "connecte"
                result[nom] = {
                    "statut"         : statut,
                    "latence_moy_ms" : lat_moy,
                    "derniere_activite": derniere,
                }
            return result

    def _watchdog_services(self):
        """Détecte les services déconnectés et crée des alertes."""
        while True:
            time.sleep(10)
            now = time.time()
            with self._lock:
                for nom, data in self.services.items():
                    derniere = data["derniere_activite"]
                    if derniere == 0:
                        continue
                    etait_connecte = data["statut"] == "connecte"
                    if etait_connecte and now - derniere > SERVICE_TIMEOUT:
                        data["statut"] = "deconnecte"
                        self._creer_alerte(
                            "service_deconnecte",
                            f"Service '{nom}' injoignable depuis "
                            f"{int(now - derniere)}s",
                        )

    # ──────────────────────────────────────────────────────────────────
    # Alertes
    # ──────────────────────────────────────────────────────────────────

    def _verifier_alertes(self):
        """Vérifie si le taux NG dépasse le seuil configuré."""
        with self._lock:
            seuil   = self.config_alertes["ng_seuil_pct"]
            fenetre = self.config_alertes["ng_fenetre"]

            # Taux NG sur les N derniers verdicts
            recents = list(self.verdicts)[:fenetre]
            if len(recents) < fenetre:
                return
            nb_ng = sum(
                1 for v in recents
                if v.get("verdict", v.get("verdict_global")) == "NG"
            )
            taux = 100 * nb_ng / fenetre

            if taux >= seuil:
                # Vérifier si une alerte du même type est déjà active
                existe = any(
                    a["type"] == "taux_ng" and not a["acquittee"]
                    for a in self.alertes
                )
                if not existe:
                    self._creer_alerte(
                        "taux_ng",
                        f"Taux NG {taux:.1f}% ≥ seuil {seuil}% "
                        f"(sur {fenetre} dernières bouteilles)",
                    )

    def _creer_alerte(self, type_alerte: str, message: str):
        """Crée une alerte. Appelé sous _lock."""
        self._alerte_counter += 1
        self.alertes.append({
            "id"        : self._alerte_counter,
            "type"      : type_alerte,
            "message"   : message,
            "timestamp" : datetime.now().strftime("%H:%M:%S"),
            "acquittee" : False,
        })

    def acquitter_alerte(self, alerte_id: int):
        with self._lock:
            for a in self.alertes:
                if a["id"] == alerte_id:
                    a["acquittee"] = True
                    break

    def get_alertes_actives(self) -> List[Dict]:
        with self._lock:
            return [a for a in self.alertes if not a["acquittee"]]

    def update_config_alertes(self, config: dict):
        with self._lock:
            self.config_alertes.update(config)

    # ──────────────────────────────────────────────────────────────────
    # Snapshot bouteille active
    # ──────────────────────────────────────────────────────────────────

    def get_bouteille_active(self) -> Optional[Dict]:
        with self._lock:
            if self.bouteille_active is None:
                return None
            b = dict(self.bouteille_active)
            b["duree_s"] = round(time.time() - b["timestamp"], 1)
            return b

    def get_verdicts(self, n: int = 50) -> List[Dict]:
        with self._lock:
            return list(self.verdicts)[:n]


# Singleton
state = StateManager()