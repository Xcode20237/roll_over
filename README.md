# Roll Over Vision 🏭👁️

> Système d'inspection qualité par vision industrielle, orchestré par microservices (MQTT, MinIO, PostgreSQL, IA, Traitement Classique).

Bienvenue dans la documentation complète du projet **Roll Over Vision**. Ce guide explique pas à pas comment installer, configurer et lancer le projet depuis zéro sur une machine Windows (et/ou industrielle).

---

## 🛠️ 1. Prérequis Système

Avant de commencer, assurez-vous que les logiciels suivants sont installés sur la machine :

1. **Python (version 3.10 ou supérieure)** :
   - [Télécharger Python](https://www.python.org/downloads/)
   - ⚠️ **Important :** Lors de l'installation de Python, assurez-vous de cocher la case *"Add python.exe to PATH"*.

2. **Docker Desktop** :
   - [Télécharger Docker Desktop](https://www.docker.com/products/docker-desktop/)
   - Sert à héberger les bases de données et le routeur de messages. L'application doit être lancée et le moteur Docker doit tourner (l'icône baleine en bas à droite doit être verte).

3. *(Optionnel)* **Git** : Si vous récupérez le projet avec la commande `git clone`. Vous pouvez aussi simplement télécharger le `.zip`.

---

## 🚀 2. Premier Lancement (Initialisation Automatique)

L'installation est automatisée via un script PowerShell. Ce script va :
- Vérifier les prérequis (Python, Docker).
- Créer l'environnement virtuel `.venv`.
- Installer toutes les dépendances listées dans `requirements.txt` (y compris le module partagé `shared` en mode `-e .`).

### Étape 2.1 — Lancer le Setup
1. Ouvrez le dossier du projet dans l'Explorateur Windows.
2. Faites un clic-droit sur le fichier **`setup_projet.ps1`**.
3. Choisissez **"Exécuter avec PowerShell"**.

*(Si PowerShell bloque l'exécution, ouvrez PowerShell en Administrateur et tapez : `Set-ExecutionPolicy Unrestricted`, répondez 'Oui', puis relancez le script).*

### Étape 2.2 — Configuration (`.env`)
Le script vérifiera s'il trouve un fichier `.env`.  
Si ce n'est pas le cas, faites une copie du fichier `env.example.txt` et renommez-la en `.env` à la racine du projet. Ce fichier contient les identifiants et routes des différentes briques. Les valeurs par défaut fonctionnent pour un usage local.

---

## 🐳 3. Démarrage de l'Infrastructure (Docker)

Le système repose sur 4 conteneurs Docker pour sa mémoire et sa communication :
- **Mosquitto** (Broker MQTT) : Le système nerveux (messages temps réel).
- **MinIO** : Le stockage objet (images des bouteilles).
- **PostgreSQL** : La base de données métier (historique des contrôles NG/OK).
- **pgAdmin** : L'interface visuelle pour explorer PostgreSQL.

### Étape 3.1 — Lancement
Ouvrez un terminal (PowerShell ou Invite de commandes) dans le dossier du projet et tapez :
```bash
docker-compose up -d
```
*(L'option `-d` lance l'infrastructure en tâche de fond).*

> **Mots de passe par défaut :**
> - **MinIO** (http://localhost:9001) : `admin_vision` / `password123`
> - **PostgreSQL** (port 5432) : `admin_bdd` / `password123`
> - **pgAdmin** (http://localhost:8080) : `admin@vision.com` / `admin`

---

## 🖥️ 4. Configuration pour Ordinateur Hors-Ligne (Dashboard)

Le tableau de bord (Dashboard) utilise des graphiques et des icônes. Pour qu'il fonctionne dans une usine sans connexion internet, il faut télécharger les librairies de ces outils **une seule fois** pendant que le poste possède le réseau.

1. Ouvrez un terminal dans le dossier du projet.
2. Activez l'environnement Python :
   ```bash
   .\.venv\Scripts\Activate.ps1
   ```
3. Lancez le script de téléchargement :
   ```bash
   python dashboard/get_libs.py
   ```
*Le script téléchargera `Chart.js`, `Socket.IO` et `Lucide Icons` en local dans le dossier `dashboard/static/js/`.*

---

## ⚙️ 5. Lancement des Microservices Python

Le projet est divisé en microservices indépendants qui communiquent via MQTT. **L'idéal est de les exécuter simultanément**, chacun dans un terminal, ou d'utiliser le script de lancement centralisé du projet.

### Méthode A — Lancement Automatique (Recommandé)
Faites simplement un **double-clic** sur le fichier **`demarrer_services.bat`**. 
Ce script va automatiquement ouvrir plusieurs terminaux (le bon vieux CMD noir de Windows), activer Python, et lancer chaque service ainsi que le Dashboard web en parallèle. C'est la méthode de production standard.

### Méthode B — Lancement manuel (Pour le debug et développement)

Ouvrez plusieurs Terminaux dans le dossier racine. Dans **chaque terminal**, n'oubliez pas d'activer l'environnement virtuel (`.\.venv\Scripts\Activate.ps1`), puis tapez les commandes suivantes selon vos besoins :

#### 1. L'acquisition (Le Pont FTP depuis la vraie Caméra)
Simule le protocole de communication de l'automate pour l'ingestion d'images de production.
```bash
python pont_camera_ftp.py
```

#### 2. L'Orchestrateur (Service de Tri - Optionnel selon version)
Rote dynamiquement les images vers les bons moteurs d'algorithme.
```bash
python services/service_switch_orchestrateur.py
```

#### 3. Les Moteurs de Calcul / Services (Au choix selon les défauts testés)
Lancez ceux dont vous avez besoin :
```bash
python services/service_colorimetrique.py
python services/service_gradient.py
python services/service_geometrique.py
python services/service_check_position.py
python services/service_fusion_ia.py
python services/service_ia.py
```

#### 4. Le Juge (Décision Finale)
Celui qui consolide tous les rapports en un seul verdict OK/NG et stocke en base.
```bash
python services/service_decision_finale.py
```

---

## 📺 6. Lancement du Dashboard Web et Utilitaires

Pour consulter les rendements en direct, visualisez le résultat des algorithmes et configurez le système :

#### Lancer le Dashboard d'Opération (Vue de Supervision Usine)
Ouvrez un terminal, activez le `.venv` et lancez :
```bash
python dashboard/main_dashboard.py
```
👉 Accédez ensuite à l'adresse : **http://localhost:5000** depuis n'importe quel navigateur web.

#### Lancer les Utilitaires de Paramétrage
Si vous voulez changer les recettes (tolérances, zones de scan, algorithmes) de l'Outil Industriel :
```bash
# Interface Graphique Visuelle de Configuration (Recettes)
python utilitaire/configuration/main.py

# Interface Graphique de Test unitaire et Debogage
python utilitaire/inspection/main_inspection.py
```

---

## 🛑 7. Arrêt du système
1. Pour couper Python : Naviguez sur les fenêtres terminales ouvertes et appuyez sur `CTRL + C`.
2. Pour stopper la mémoire infra :
   ```bash
   docker-compose down
   ```

*Félicitations ! Votre usine Roll Over Vision est pleinement fonctionnelle.* 🚀
