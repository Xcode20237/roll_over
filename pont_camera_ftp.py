import os
import time
import shutil

# =====================================================================
# CONFIGURATION
# =====================================================================
# Dossier où la vraie caméra dépose ses images (via le serveur FTP)
DOSSIER_SOURCE_CAMERA = "./dossier_reception_ftp"

# Dossier où le service 'service_acquisition_test' écoute
DOSSIER_DESTINATION_SYSTEME = "./Reception_ftp_file"

# Paramètres de la grille de capture (pour la simulation sans PLC)
NB_ETAGES = 3       # Combien de caméras en hauteur ? (Modifié à 3)
ANGLES_PAR_TOUR = 8 # Combien d'images la caméra prend par bouteille ?

# Délai de surveillance en secondes
INTERVALLE_CHECK = 1.0

# =====================================================================

def is_file_ready(path: str) -> bool:
    """
    Détecte si le fichier est encore verrouillé par le client FTP (Windows).

    Sous Windows, le client FTP (FileZilla, etc.) maintient un verrou exclusif
    sur le fichier pendant tout le transfert. Tenter de l'ouvrir en mode
    ajout ('a+b') est la méthode la plus fiable pour détecter ce verrou :
    - Si le client FTP écrit encore  → PermissionError (WinError 32) → False
    - Si le transfert est terminé    → ouverture réussie               → True

    Cette approche est instantanée (pas de boucle d'attente) et sans risque :
    le mode 'a+b' n'écrase ni ne tronque le fichier.
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    try:
        with open(path, 'a+b'):
            return True
    except (PermissionError, OSError):
        return False

def main():
    print("=" * 60)
    print("📷 SCRIPT PONTON : VRAIE CAMÉRA -> FORMAT BLENDER")
    print("=" * 60)
    print(f"📥 Source      : {os.path.abspath(DOSSIER_SOURCE_CAMERA)}")
    print(f"📤 Destination : {os.path.abspath(DOSSIER_DESTINATION_SYSTEME)}")
    print(f"⚙️ Paramètres  : {NB_ETAGES} Étage(s), {ANGLES_PAR_TOUR} Angles/bouteille")
    print("=" * 60)

    # Création des dossiers si inexistants
    os.makedirs(DOSSIER_SOURCE_CAMERA, exist_ok=True)
    os.makedirs(DOSSIER_DESTINATION_SYSTEME, exist_ok=True)

    # Compteurs pour simuler l'automate
    compteur_image_globale = 0

    print(f"\n👀 Surveillance du dossier FTP activée...")

    while True:
        # Récupérer les nouvelles images triées par date de création (la plus ancienne d'abord)
        fichiers = [f for f in os.listdir(DOSSIER_SOURCE_CAMERA) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp'))]
        fichiers_avec_temps = [(f, os.path.getmtime(os.path.join(DOSSIER_SOURCE_CAMERA, f))) for f in fichiers]
        fichiers_tries = sorted(fichiers_avec_temps, key=lambda x: x[1])

        for nom_fichier, _ in fichiers_tries:
            chemin_source = os.path.join(DOSSIER_SOURCE_CAMERA, nom_fichier)

            # Vérification : fichier non verrouillé par le client FTP (Windows)
            if not is_file_ready(chemin_source):
                print(f"   ⏳ Transfert en cours, fichier ignoré : {nom_fichier}")
                continue

            # --- Calcul dynamique Etage et Angle ---
            # Ex avec 2 étages et 8 angles (16 images par bouteille) :
            # Image 0 à 7   -> Etage 1, Angle 1 à 8
            # Image 8 à 15  -> Etage 2, Angle 1 à 8
            # Image 16      -> Nouvelle bouteille, Etage 1, Angle 1

            images_par_bouteille = NB_ETAGES * ANGLES_PAR_TOUR
            index_dans_bouteille = compteur_image_globale % images_par_bouteille

            num_etage = (index_dans_bouteille // ANGLES_PAR_TOUR) + 1
            num_angle = (index_dans_bouteille % ANGLES_PAR_TOUR) + 1

            extension = os.path.splitext(nom_fichier)[1].lower()

            # Nouveau nom format Blender
            nouveau_nom = f"Img_Etage{num_etage}_Angle{num_angle:03d}{extension}"
            chemin_dest = os.path.join(DOSSIER_DESTINATION_SYSTEME, nouveau_nom)

            try:
                # Déplacement du fichier
                shutil.move(chemin_source, chemin_dest)
                # IMPORTANT : on n'incrémente QUE si le déplacement a réussi.
                # Sans ça, un échec consomme un slot d'angle et décale tous
                # les fichiers suivants (ex: 00196 raté → 00197 prend Angle007
                # à la place de 00196, et 00196 finit en Angle008).
                compteur_image_globale += 1
                print(f"📸 Transfert : {nom_fichier}  -->  {nouveau_nom}")

            except PermissionError:
                # Verrou FTP encore actif malgré la vérification (race condition rare)
                print(f"   ⏳ Verrou persistant, retry au prochain cycle : {nom_fichier}")
            except Exception as e:
                print(f"❌ Erreur lors du déplacement de {nom_fichier} : {e}")

            # Condition d'arrêt : on a fait un cycle complet (1 bouteille = NB_ETAGES * ANGLES_PAR_TOUR images)
            images_par_bouteille = NB_ETAGES * ANGLES_PAR_TOUR
            if compteur_image_globale >= images_par_bouteille:
                print(f"\n🏁 Terminé ! {compteur_image_globale} images (1 bouteille complète sur {NB_ETAGES} étages) transmises avec succès.")
                print("🛑 Arrêt automatique du script ponton.")
                return  # Quitte proprement le script

        time.sleep(INTERVALLE_CHECK)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du script ponton FTP.")