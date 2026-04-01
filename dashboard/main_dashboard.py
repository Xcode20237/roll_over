"""
main_dashboard.py
-----------------
Point d'entrée Flask + Flask-SocketIO.
"""
from __future__ import annotations
import json
import os
from datetime import datetime

from flask import Flask, render_template, request, jsonify, Response
from flask_socketio import SocketIO, emit

from config import DASHBOARD_HOST, DASHBOARD_PORT
from state_manager import state
from mqtt_listener import MQTTListener
from db_reader import db
from minio_reader import get_image_b64

app = Flask(__name__)
app.config["SECRET_KEY"] = "qc_dashboard_secret_2024"
sio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

mqtt_l = MQTTListener(sio)

# ══════════════════════════════════════════════════════════════════
# ROUTES HTML
# ══════════════════════════════════════════════════════════════════

@app.route("/")
def vue_operateur():
    return render_template("index.html")

@app.route("/technique")
def vue_technique():
    return render_template("technical.html")

@app.route("/historique")
def vue_historique():
    return render_template("history.html")

# ══════════════════════════════════════════════════════════════════
# API REST
# ══════════════════════════════════════════════════════════════════

@app.route("/api/init")
def api_init():
    return jsonify({
        "bouteille_active" : state.get_bouteille_active(),
        "verdicts"         : state.get_verdicts(),
        "services"         : state.get_services_snapshot(),
        "stats"            : state.get_stats_snapshot(),
        "alertes"          : state.get_alertes_actives(),
        "config_alertes"   : state.config_alertes,
        "db_disponible"    : db.disponible,
        "check_position"   : state.get_check_position(),
    })

@app.route("/api/historique")
def api_historique():
    def p(key, default=None):
        v = request.args.get(key, "").strip()
        return v if v else default

    return jsonify(db.rechercher(
        id_bouteille   = p("id"),
        type_bouteille = p("type"),
        verdict        = p("verdict"),
        defaut         = p("defaut"),
        date_debut     = p("debut"),
        date_fin       = p("fin"),
        limite         = int(request.args.get("limite", 50)),
        offset         = int(request.args.get("offset", 0)),
    ))

@app.route("/api/verdict/<int:verdict_id>")
def api_verdict_detail(verdict_id: int):
    v = db.get_verdict(verdict_id)
    if v is None:
        return jsonify({"erreur": "Verdict introuvable"}), 404
    return jsonify(v)

@app.route("/api/export/csv")
def api_export_csv():
    def p(key):
        v = request.args.get(key, "").strip()
        return v or None

    csv_data = db.export_csv(
        id_bouteille   = p("id"),
        type_bouteille = p("type"),
        verdict        = p("verdict"),
        defaut         = p("defaut"),
        date_debut     = p("debut"),
        date_fin       = p("fin"),
    )
    nom = f"verdicts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        "\ufeff" + csv_data,          # BOM UTF-8 pour Excel
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={nom}"}
    )

@app.route("/api/image")
def api_image():
    bucket = request.args.get("bucket", "")
    chemin = request.args.get("chemin", "")
    if not bucket or not chemin:
        return jsonify({"erreur": "bucket et chemin requis"}), 400
    img = get_image_b64(bucket, chemin)
    if img is None:
        return jsonify({"erreur": "Image indisponible"}), 404
    return jsonify({"image": img})

@app.route("/api/alertes/config", methods=["GET", "POST"])
def api_alertes_config():
    if request.method == "POST":
        state.update_config_alertes(request.get_json() or {})
        return jsonify({"ok": True})
    return jsonify(state.config_alertes)

@app.route("/api/alertes/acquitter/<int:alerte_id>", methods=["POST"])
def api_acquitter(alerte_id: int):
    state.acquitter_alerte(alerte_id)
    sio.emit("alertes_update", state.get_alertes_actives())
    return jsonify({"ok": True})

@app.route("/api/status")
def api_status():
    """Endpoint de santé — vérifie les libs JS locales."""
    js_dir = os.path.join(os.path.dirname(__file__), "static", "js")
    libs_ok = {}
    for lib in ("socket.io.min.js", "chart.min.js"):
        path = os.path.join(js_dir, lib)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        libs_ok[lib] = size > 10000   # Un vrai fichier fait >10Ko
    return jsonify({
        "dashboard" : "ok",
        "db"        : db.disponible,
        "libs_js"   : libs_ok,
        "timestamp" : datetime.now().isoformat(),
    })

# ══════════════════════════════════════════════════════════════════
# SOCKET IO
# ══════════════════════════════════════════════════════════════════

@sio.on("connect")
def on_connect():
    emit("init", {
        "bouteille_active" : state.get_bouteille_active(),
        "verdicts"         : state.get_verdicts(),
        "services"         : state.get_services_snapshot(),
        "stats"            : state.get_stats_snapshot(),
        "alertes"          : state.get_alertes_actives(),
        "config_alertes"   : state.config_alertes,
        "db_disponible"    : db.disponible,
        "check_position"   : state.get_check_position(),
    })

@sio.on("acquitter_alerte")
def on_acquitter(data):
    state.acquitter_alerte(data.get("id"))
    sio.emit("alertes_update", state.get_alertes_actives())

@sio.on("update_config_alertes")
def on_config_alertes(data):
    state.update_config_alertes(data)
    emit("config_alertes_ok", state.config_alertes)

# ══════════════════════════════════════════════════════════════════
# DÉMARRAGE
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Vérifier les libs JS
    js_dir = os.path.join(os.path.dirname(__file__), "static", "js")
    libs_manquantes = []
    for lib in ("socket.io.min.js", "chart.min.js"):
        path = os.path.join(js_dir, lib)
        if not os.path.exists(path) or os.path.getsize(path) < 10000:
            libs_manquantes.append(lib)

    print("=" * 60)
    print("  Roll-over QC — Dashboard de Supervision")
    print(f"  Accès : http://localhost:{DASHBOARD_PORT}")
    print(f"  DB    : {'✅ connectée' if db.disponible else '⚠️  non disponible'}")
    if libs_manquantes:
        print(f"  ⚠️  Libs JS locales manquantes : {libs_manquantes}")
        print(f"     → Exécuter : python download_libs.py")
        print(f"     → Ou le dashboard utilisera les CDN si internet disponible")
    else:
        print(f"  JS    : ✅ libs locales OK")
    print("=" * 60)

    mqtt_l.start()

    sio.run(
        app,
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        debug=False,
        allow_unsafe_werkzeug=True,
        log_output=False,
    )
