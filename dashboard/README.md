# Roll-over QC — Dashboard de Supervision

Interface web temps réel pour la supervision du système de contrôle qualité.

## Structure

```
dashboard/
├── main_dashboard.py       ← Point d'entrée Flask
├── config.py               ← Configuration (.env)
├── state_manager.py        ← État global thread-safe
├── mqtt_listener.py        ← Thread MQTT → SocketIO
├── db_reader.py            ← Lecture PostgreSQL
├── minio_reader.py         ← Images MinIO → base64
├── get_libs.py             ← Téléchargement libs JS
├── requirements.txt        ← Dépendances Python
├── .env.example            ← Template configuration
├── static/
│   ├── css/style.css
│   ├── js/
│   │   ├── app.js          ← Logique commune
│   │   ├── technical.js    ← Vue technique
│   │   ├── history.js      ← Historique
│   │   ├── chart.min.js    ← À télécharger (get_libs.py)
│   │   └── socket.io.min.js← À télécharger (get_libs.py)
│   └── sounds/alert.wav    ← Son d'alerte
└── templates/
    ├── base.html
    ├── index.html          ← Vue Opérateur (/)
    ├── technical.html      ← Vue Technique (/technique)
    └── history.html        ← Historique (/historique)
```

## Installation

### 1. Dépendances Python

```bash
pip install -r requirements.txt
```

### 2. Librairies JavaScript (une seule fois, poste connecté)

```bash
python get_libs.py
```

### 3. Configuration

```bash
cp .env.example .env
# Éditer .env avec vos valeurs
```

### 4. Lancement

```bash
python main_dashboard.py
```

Accès : **http://localhost:5000**

---

## Pages

| URL | Description |
|---|---|
| `/` | Vue Opérateur — verdict en grand, stats rapides |
| `/technique` | Vue Technique — pipeline, graphiques, config alertes |
| `/historique` | Historique — recherche multicritère, export CSV |

## Alertes

Les alertes se déclenchent sur :
- Taux NG ≥ seuil configuré (sur N dernières bouteilles)
- Service injoignable depuis > 30 secondes

Configuration depuis `/technique` → "Configuration alertes".
Chaque alerte doit être **acquittée manuellement** par l'opérateur.

## Topics MQTT écoutés

```
vision/images/new                    ← Nouvelle bouteille
vision/classique/colorimetrique      ← Image routée
vision/classique/gradient
vision/classique/geometrique
vision/ia/pretraitement
vision/resultats/colorimetrique      ← Résultat service
vision/resultats/gradient
vision/resultats/geometrique
vision/resultats/ia
vision/resultats/final               ← Verdict final
vision/filtre/status                 ← Heartbeat orchestrateur
```
