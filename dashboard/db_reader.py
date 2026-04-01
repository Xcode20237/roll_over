"""
db_reader.py
------------
Lecture de l'historique depuis PostgreSQL.
Toutes les requêtes sont paramétrées (protection injection SQL).
Retourne None si PostgreSQL n'est pas disponible.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Any
import json

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_OK = True
except ImportError:
    PSYCOPG2_OK = False


class DBReader:

    def __init__(self):
        self._conn = None
        if PSYCOPG2_OK:
            self._connect()

    def _connect(self):
        try:
            self._conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT,
                dbname=DB_NAME, user=DB_USER,
                password=DB_PASSWORD,
                connect_timeout=5,
            )
            self._conn.autocommit = True
            print("[DB] PostgreSQL connecté")
        except Exception as e:
            print(f"[DB] PostgreSQL non disponible : {e}")
            self._conn = None

    @property
    def disponible(self) -> bool:
        return self._conn is not None

    def _cursor(self):
        if self._conn is None:
            return None
        try:
            # Reconnecter si nécessaire
            if self._conn.closed:
                self._connect()
            return self._conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            )
        except Exception:
            self._connect()
            return None

    # ──────────────────────────────────────────────────────────────────
    # Recherche multicritère
    # ──────────────────────────────────────────────────────────────────

    def rechercher(
        self,
        id_bouteille   : Optional[str]  = None,
        type_bouteille : Optional[str]  = None,
        verdict        : Optional[str]  = None,
        defaut         : Optional[str]  = None,
        date_debut     : Optional[str]  = None,
        date_fin       : Optional[str]  = None,
        limite         : int            = 50,
        offset         : int            = 0,
    ) -> Dict:
        """
        Recherche multicritère dans l'historique.
        Retourne {"resultats": [...], "total": int}.
        """
        cur = self._cursor()
        if cur is None:
            return {"resultats": [], "total": 0, "erreur": "BDD non disponible"}

        conditions = ["1=1"]
        params     = []

        if id_bouteille:
            conditions.append("id_bouteille ILIKE %s")
            params.append(f"%{id_bouteille}%")
        if type_bouteille:
            conditions.append("type_bouteille = %s")
            params.append(type_bouteille)
        if verdict:
            conditions.append("verdict = %s")
            params.append(verdict)
        if defaut:
            conditions.append("details_json::text ILIKE %s")
            params.append(f"%{defaut}%")
        if date_debut:
            conditions.append("timestamp_utc >= %s")
            params.append(date_debut)
        if date_fin:
            conditions.append("timestamp_utc <= %s")
            params.append(date_fin)

        where = " AND ".join(conditions)

        try:
            # Compter le total
            cur.execute(
                f"SELECT COUNT(*) as total FROM resultats_inspection WHERE {where}",
                params
            )
            total = cur.fetchone()["total"]

            # Récupérer les résultats paginés
            cur.execute(
                f"""SELECT id, id_bouteille, type_bouteille, verdict,
                           services_evalues, services_ignores,
                           details_json, raison_ng,
                           to_char(timestamp_utc, 'DD/MM/YYYY HH24:MI:SS') as timestamp_display,
                           EXTRACT(EPOCH FROM timestamp_utc) as timestamp_epoch
                    FROM resultats_inspection
                    WHERE {where}
                    ORDER BY timestamp_utc DESC
                    LIMIT %s OFFSET %s""",
                params + [limite, offset]
            )
            rows = cur.fetchall()

            resultats = []
            for row in rows:
                r = dict(row)
                # Parser details_json
                try:
                    if isinstance(r.get("details_json"), str):
                        r["details_json"] = json.loads(r["details_json"])
                    if isinstance(r.get("services_evalues"), str):
                        r["services_evalues"] = json.loads(r["services_evalues"])
                    if isinstance(r.get("services_ignores"), str):
                        r["services_ignores"] = json.loads(r["services_ignores"])
                except Exception:
                    pass
                resultats.append(r)

            return {"resultats": resultats, "total": total}

        except Exception as e:
            print(f"[DB] Erreur recherche : {e}")
            return {"resultats": [], "total": 0, "erreur": str(e)}

    # ──────────────────────────────────────────────────────────────────
    # Détail d'un verdict par ID base de données
    # ──────────────────────────────────────────────────────────────────

    def get_verdict(self, verdict_id: int) -> Optional[Dict]:
        cur = self._cursor()
        if cur is None:
            return None
        try:
            cur.execute(
                """SELECT *, to_char(timestamp_utc, 'DD/MM/YYYY HH24:MI:SS')
                          as timestamp_display
                   FROM resultats_inspection WHERE id = %s""",
                (verdict_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            r = dict(row)
            for key in ("details_json", "services_evalues", "services_ignores"):
                if isinstance(r.get(key), str):
                    try:
                        r[key] = json.loads(r[key])
                    except Exception:
                        pass
            return r
        except Exception as e:
            print(f"[DB] Erreur get_verdict({verdict_id}) : {e}")
            return None

    # ──────────────────────────────────────────────────────────────────
    # Stats du jour depuis la BDD
    # ──────────────────────────────────────────────────────────────────

    def stats_journee(self) -> Dict:
        """Stats agrégées de la journée courante."""
        cur = self._cursor()
        if cur is None:
            return {}
        try:
            cur.execute("""
                SELECT
                    COUNT(*)                                    as total,
                    SUM(CASE WHEN verdict='OK' THEN 1 ELSE 0 END) as ok,
                    SUM(CASE WHEN verdict='NG' THEN 1 ELSE 0 END) as ng,
                    type_bouteille
                FROM resultats_inspection
                WHERE timestamp_utc >= CURRENT_DATE
                GROUP BY type_bouteille
                ORDER BY total DESC
            """)
            rows = cur.fetchall()
            return {"par_type": [dict(r) for r in rows]}
        except Exception as e:
            print(f"[DB] Erreur stats_journee : {e}")
            return {}

    # ──────────────────────────────────────────────────────────────────
    # Export CSV
    # ──────────────────────────────────────────────────────────────────

    def export_csv(self, **kwargs) -> str:
        """Retourne les résultats filtrés sous forme de CSV string."""
        import csv, io
        kwargs["limite"] = 10000
        kwargs["offset"] = 0
        data = self.rechercher(**kwargs)
        rows = data.get("resultats", [])

        output = io.StringIO()
        if not rows:
            return ""

        writer = csv.writer(output, delimiter=";")
        writer.writerow([
            "ID", "ID_Bouteille", "Type", "Verdict",
            "Services_Evalues", "Raison_NG", "Timestamp"
        ])
        for r in rows:
            writer.writerow([
                r.get("id", ""),
                r.get("id_bouteille", ""),
                r.get("type_bouteille", ""),
                r.get("verdict", ""),
                ", ".join(r.get("services_evalues", [])
                          if isinstance(r.get("services_evalues"), list) else []),
                r.get("raison_ng", ""),
                r.get("timestamp_display", ""),
            ])
        return output.getvalue()


# Singleton
db = DBReader()
