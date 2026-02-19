"""
🧹 Script de nettoyage de doublons Immich
-----------------------------------------

Ce script a été développé par Sébastien Castermans, aidé par l'IA, pour identifier et conserver
la meilleure version de fichiers doublons (photos/vidéos) sur un serveur Immich via son API.
Il permet de supprimer efficacement les doublons en se basant sur des critères tels que la date
de création, le format HEIC (original d'Apple), la taille du fichier et les métadonnées EXIF.
Le paramètre de détection des doublons est propre à votre installation Immich et peut être
modifié dans les paramètres d'administration du serveur.

💡 Fonctionnalités :
- Tri intelligent pour conserver la meilleure version d’un fichier, d'abord les plus anciens puis 
priorité aux fichiers HEIC (originaux d'apple), sinon selon la taille et enfin les métadonnées EXIF
- Option de simulation (dry-run) pour tester sans supprimer
- Suppression vers corbeille ou définitive
- Journalisation détaillée dans un fichier .log si activée
- Possibilité de visualiser les fichiers avec leur URL dans les logs

Configuration via variables d'environnement :
  IMMICH_SERVER, IMMICH_API_KEY, IMMICH_ENABLE_LOG, IMMICH_DRY_RUN, IMMICH_DEFINITELY,
  IMMICH_ONLY_PAIRS, IMMICH_KEEP_METADATA, IMMICH_TRANSFER_METADATA, IMMICH_CONFIRM,
  IMMICH_REQUEST_TIMEOUT, IMMICH_DELETE_BATCH_SIZE

Améliorations bienvenues ! Partage libre avec attribution.
"""


import os
import requests
import json
from datetime import datetime
import sys

# Load .env file if python-dotenv is installed (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def get_env_bool(name: str, default: bool) -> bool:
    """Parse boolean from environment variable."""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in ('true', '1', 'yes', 'on')


# Configuration (variables d'environnement, avec valeurs par défaut) :
ENABLE_LOG_FILE = get_env_bool('IMMICH_ENABLE_LOG', True)
SERVER = os.environ.get('IMMICH_SERVER', 'https://immich.example.com')
API_KEY = os.environ.get('IMMICH_API_KEY', 'ENTER_YOUR_API_KEY_HERE')
DRY_RUN = get_env_bool('IMMICH_DRY_RUN', True)
DEFINITELY = get_env_bool('IMMICH_DEFINITELY', False)
ONLY_PAIRS = get_env_bool('IMMICH_ONLY_PAIRS', False)
KEEP_METADATA = get_env_bool('IMMICH_KEEP_METADATA', True)
TRANSFER_METADATA = get_env_bool('IMMICH_TRANSFER_METADATA', True)
CONFIRM = get_env_bool('IMMICH_CONFIRM', False)
REQUEST_TIMEOUT = max(1, int(os.environ.get('IMMICH_REQUEST_TIMEOUT', 5)))
DELETE_BATCH_SIZE = max(1, int(os.environ.get('IMMICH_DELETE_BATCH_SIZE', 500)))


if ENABLE_LOG_FILE:
    log_filename = f"immich_duplicates_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    class Tee:
        def __init__(self, *streams):
            self.streams = streams
        def write(self, message):
            for stream in self.streams:
                stream.write(message)
                stream.flush()
        def flush(self):
            for stream in self.streams:
                stream.flush()
    logfile = open(log_filename, 'w', encoding='utf-8')
    sys.stdout = Tee(sys.stdout, logfile)
    sys.stderr = Tee(sys.stderr, logfile)

# Étape 1 : Récupérer les doublons
HEADERS = {
    'Accept': 'application/json',
    'x-api-key': API_KEY
}
try:
    response = requests.get(
        f"{SERVER}/api/duplicates", headers=HEADERS, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    duplicates = response.json()
except requests.RequestException:
    print(f"[ERROR] Échec lors de la récupération des doublons, serveur {SERVER} injoignable ou clé API invalide.")
    exit(1)
if not duplicates:
    print("[INFO] Aucun doublon trouvé. Rien à supprimer.")
    exit(0)
print(f"[INFO] {len(duplicates)} groupes de doublons trouvés.")


# Étape 2 : Préparer les fichiers à supprimer
def get_asset_info(asset):
    exif = asset.get('exifInfo', {})
    try:
        date = datetime.fromisoformat(exif.get('dateTimeOriginal'))
    except (ValueError, TypeError):
        date = datetime.max  # Pire date si absente
    is_heic = 1 if asset['originalFileName'].lower().endswith('.heic') else 0
    size = exif.get('fileSizeInByte')
    exif_count = sum(1 for v in exif.values() if v is not None and (not isinstance(v, str) or v.strip() != ""))
    return (date, is_heic, size, exif_count)

def select_best_asset(assets):
    remaining = assets[:]
    length = len(remaining)
    reason = "fichiers identiques avec les critères (date, heic, taille, exif)"

    # Étape 1 : date la plus ancienne
    min_date = min(get_asset_info(a)[0] for a in remaining)
    remaining = [a for a in remaining if get_asset_info(a)[0] == min_date]
    if len(remaining) == 1:
        reason = "plus ancien"
        return remaining[0], reason
    if length != len(remaining):
        reason = "plus ancien"
        length = len(remaining)

    # Étape 2 : priorité au .heic
    heic = max(get_asset_info(a)[1] for a in remaining)
    remaining = [a for a in remaining if get_asset_info(a)[1] == heic]
    if len(remaining) == 1:
        reason = "extension heic"
        return remaining[0], reason
    if length != len(remaining):
        reason = "extension heic"
        length = len(remaining)

    # Étape 3 : plus grande taille
    max_size = max(get_asset_info(a)[2] for a in remaining)
    remaining = [a for a in remaining if get_asset_info(a)[2] == max_size]
    if len(remaining) == 1:
        reason = "taille plus grande"
        return remaining[0], reason
    if length != len(remaining):
        reason = "taille plus grande"
        length = len(remaining)

    # Étape 4 : plus de champs EXIF
    max_exif = max(get_asset_info(a)[3] for a in remaining)
    remaining = [a for a in remaining if get_asset_info(a)[3] == max_exif]
    if len(remaining) == 1:
        reason = "exif en plus grand nombre"
        return remaining[0], reason
    if length != len(remaining):
        reason = "exif en plus grand nombre"
        length = len(remaining)

    # Égalité finale
    return remaining[0], reason


def _has_exif_value(asset, key):
    """Vérifie si l'asset a une valeur EXIF non vide."""
    exif = asset.get('exifInfo') or {}
    val = exif.get(key)
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    return True


def _get_kept_tags_ids(kept):
    """Retourne l'ensemble des IDs de tags de l'asset gardé."""
    tags = kept.get('tags') or []
    return {t['id'] for t in tags if t.get('id')}


def remove_kept_metadata(kept, headers_get, headers_json):
    """Supprime albums et tags de l'asset gardé quand KEEP_METADATA=false."""
    kept_id = kept['id']
    try:
        albums_resp = requests.get(
            f"{SERVER}/api/albums", params={"assetId": kept_id}, headers=headers_get,
            timeout=REQUEST_TIMEOUT
        )
        albums_resp.raise_for_status()
        albums = albums_resp.json()
        for album in albums:
            try:
                del_resp = requests.delete(
                    f"{SERVER}/api/albums/{album['id']}/assets",
                    headers=headers_json,
                    data=json.dumps({"ids": [kept_id]}),
                    timeout=REQUEST_TIMEOUT,
                )
                if del_resp.status_code != 200:
                    print(f"[WARN] Impossible de retirer le gardé de l'album {album.get('albumName', album['id'])} : {del_resp.status_code}")
            except requests.RequestException as e:
                print(f"[WARN] Erreur lors du retrait de l'album : {e}")
        for tag in (kept.get('tags') or []):
            tag_id = tag.get('id')
            if not tag_id:
                continue
            try:
                del_resp = requests.delete(
                    f"{SERVER}/api/tags/{tag_id}/assets",
                    headers=headers_json,
                    data=json.dumps({"ids": [kept_id]}),
                    timeout=REQUEST_TIMEOUT,
                )
                if del_resp.status_code != 200:
                    print(f"[WARN] Impossible de retirer le tag {tag.get('name', tag_id)} du gardé : {del_resp.status_code}")
            except requests.RequestException as e:
                print(f"[WARN] Erreur lors du retrait du tag : {e}")
    except requests.RequestException as e:
        print(f"[WARN] Erreur lors de la récupération des albums du gardé : {e}")


def transfer_metadata_to_kept(kept, to_delete_assets, headers_get, headers_json):
    """Transfère les métadonnées des assets à supprimer vers le gardé (augmentation uniquement)."""
    kept_id = kept['id']
    original_kept_tags = _get_kept_tags_ids(kept)
    tags_to_add = set()
    exif_to_set = {}

    for to_del in to_delete_assets:
        try:
            albums_resp = requests.get(
                f"{SERVER}/api/albums", params={"assetId": to_del['id']}, headers=headers_get,
                timeout=REQUEST_TIMEOUT
            )
            albums_resp.raise_for_status()
            for album in albums_resp.json():
                try:
                    add_resp = requests.put(
                        f"{SERVER}/api/albums/{album['id']}/assets",
                        headers=headers_json,
                        data=json.dumps({"ids": [kept_id]}),
                        timeout=REQUEST_TIMEOUT,
                    )
                    if add_resp.status_code not in (200, 201):
                        err_info = add_resp.json() if add_resp.text else {}
                        if err_info and isinstance(err_info, list) and len(err_info) > 0 and err_info[0].get('error') == 'duplicate':
                            pass
                        else:
                            print(f"[WARN] Impossible d'ajouter le gardé à l'album : {add_resp.status_code}")
                except requests.RequestException as e:
                    print(f"[WARN] Erreur lors de l'ajout à l'album : {e}")
        except requests.RequestException as e:
            print(f"[WARN] Erreur lors de la récupération des albums du to_delete {to_del['id']} : {e}")

        for tag in (to_del.get('tags') or []):
            tag_id = tag.get('id')
            if tag_id and tag_id not in original_kept_tags and tag_id not in tags_to_add:
                tags_to_add.add(tag_id)
        exif = to_del.get('exifInfo') or {}
        for key in ('latitude', 'longitude', 'description', 'dateTimeOriginal', 'rating'):
            if key in exif_to_set:
                continue
            if _has_exif_value(to_del, key) and not _has_exif_value(kept, key):
                raw = exif.get(key)
                if raw is not None:
                    exif_to_set[key] = raw

    new_tag_ids = list(tags_to_add)
    if new_tag_ids:
        try:
            tag_resp = requests.put(
                f"{SERVER}/api/tags/assets",
                headers=headers_json,
                data=json.dumps({"assetIds": [kept_id], "tagIds": new_tag_ids}),
                timeout=REQUEST_TIMEOUT,
            )
            if tag_resp.status_code not in (200, 201):
                print(f"[WARN] Impossible d'ajouter les tags au gardé : {tag_resp.status_code}")
        except requests.RequestException as e:
            print(f"[WARN] Erreur lors de l'ajout des tags : {e}")

    if exif_to_set:
        payload = {"ids": [kept_id], **{k: v for k, v in exif_to_set.items()}}
        try:
            update_resp = requests.put(
                f"{SERVER}/api/assets", headers=headers_json, data=json.dumps(payload),
                timeout=REQUEST_TIMEOUT
            )
            if update_resp.status_code not in (200, 204):
                print(f"[WARN] Impossible de mettre à jour l'EXIF du gardé : {update_resp.status_code}")
        except requests.RequestException as e:
            print(f"[WARN] Erreur lors de la mise à jour de l'EXIF : {e}")


HEADERS_JSON = {
    'Content-Type': 'application/json',
    'x-api-key': API_KEY
}
HEADERS_GET = {'Accept': 'application/json', 'x-api-key': API_KEY}

ids_to_delete = []
processed_groups = []

i = 0
for group in duplicates:
    i = i + 1
    assets = group.get('assets')
    if ONLY_PAIRS and len(assets) != 2:
        print(f"[IGNORÉ] Doublons n°{i} ({len(assets)} fichiers) - mode paires uniquement, sélection manuelle recommandée")
        continue
    kept, reason = select_best_asset(assets)
    to_delete_assets = [a for a in assets if a['id'] != kept['id']]
    to_delete_ids = [a['id'] for a in to_delete_assets]
    date, is_heic, size, exif_count = get_asset_info(kept)
    date_str = date.strftime('%d/%m/%y - %H:%M:%S') if date != datetime.max else "??/??/??"
    print(f"\n[INFO] Doublons n°{i} ({len(assets)} fichiers), raison de conservation : '{reason}'")
    print(f"[GARDÉ]\t\tDate : {date_str}\tTaille : {round(size/1024/1024,2)}MB\t\tNombre d'exif : {exif_count}\t{kept['originalFileName']} --> {SERVER}/api/assets/{kept['id']}/thumbnail?size=preview")
    for asset in to_delete_assets:
        date, is_heic, size, exif_count = get_asset_info(asset)
        date_str = date.strftime('%d/%m/%y - %H:%M:%S') if date != datetime.max else "??/??/??"
        print(f"[SUPPRIMÉ]\tDate : {date_str}\tTaille : {round(size/1024/1024,2)}MB\t\tNombre d'exif : {exif_count}\t{asset['originalFileName']} --> {SERVER}/api/assets/{asset['id']}/thumbnail?size=preview")

    if CONFIRM:
        reply = input("Traiter ce groupe ? [O/n] ").strip().lower()
        if reply == 'n':
            continue
        if DRY_RUN:
            print(f"[INFO] Groupe {i} serait traité (mode simulation).")
        else:
            if not KEEP_METADATA:
                remove_kept_metadata(kept, HEADERS_GET, HEADERS_JSON)
            if TRANSFER_METADATA and to_delete_assets:
                transfer_metadata_to_kept(kept, to_delete_assets, HEADERS_GET, HEADERS_JSON)
            delete_response = None
            try:
                delete_response = requests.delete(
                    f"{SERVER}/api/assets", headers=HEADERS_JSON,
                    data=json.dumps({"force": DEFINITELY, "ids": to_delete_ids}),
                    timeout=REQUEST_TIMEOUT,
                )
                delete_response.raise_for_status()
                print(f"[SUCCESS] Groupe {i} traité ({len(to_delete_ids)} asset(s) supprimé(s)).")
            except requests.RequestException:
                status = delete_response.status_code if delete_response is not None else "N/A"
                text = delete_response.text if delete_response is not None else "N/A"
                print(f"[ERROR] Échec de la suppression pour le groupe {i} : {status}")
                print(f"[DEBUG] Réponse API : {text}")
    else:
        ids_to_delete.extend(to_delete_ids)
        processed_groups.append((kept, to_delete_assets))
        if i % 500 == 0:
            print(f"[INFO] Groupes traités 1-{i} / {len(duplicates)}...")


# Étape 3 : Mode non-CONFIRM – métadonnées puis suppression en bloc
if DRY_RUN:
    print("\n[INFO] Mode simulation activé. Aucune suppression réelle effectuée.")
    exit(0)

if not CONFIRM:
    total_groups = len(processed_groups)
    if total_groups > 0:
        print(f"[INFO] Transfert des métadonnées pour {total_groups} groupes...")
    for idx, (kept, to_delete_assets) in enumerate(processed_groups):
        if (idx + 1) % 100 == 0:
            print(f"[INFO] Progression métadonnées : {idx + 1}/{total_groups} groupes...")
        if not KEEP_METADATA:
            remove_kept_metadata(kept, HEADERS_GET, HEADERS_JSON)
        if TRANSFER_METADATA and to_delete_assets:
            transfer_metadata_to_kept(kept, to_delete_assets, HEADERS_GET, HEADERS_JSON)

    total = len(ids_to_delete)
    num_batches = (total + DELETE_BATCH_SIZE - 1) // DELETE_BATCH_SIZE
    print(f"[INFO] Suppression de {total} assets en {num_batches} lots (taille du lot : {DELETE_BATCH_SIZE})...")
    delete_response = None
    failed_batches = 0
    for batch_idx in range(0, total, DELETE_BATCH_SIZE):
        batch_ids = ids_to_delete[batch_idx : batch_idx + DELETE_BATCH_SIZE]
        batch_num = batch_idx // DELETE_BATCH_SIZE + 1
        try:
            delete_response = requests.delete(
                f"{SERVER}/api/assets", headers=HEADERS_JSON,
                data=json.dumps({"force": DEFINITELY, "ids": batch_ids}),
                timeout=REQUEST_TIMEOUT,
            )
            delete_response.raise_for_status()
            print(f"[INFO] Lot {batch_num}/{num_batches} : {len(batch_ids)} assets supprimés.")
        except requests.RequestException as e:
            failed_batches += 1
            text = delete_response.text if delete_response is not None else str(e)
            print(f"[ERROR] Lot {batch_num} échoué : {e}")
            print(f"[DEBUG] Réponse API : {text}")
    if failed_batches == 0:
        print(f"\n[SUCCESS] Suppression terminée. {total} assets supprimés.")
    else:
        print(f"\n[WARN] Suppression terminée avec {failed_batches} lot(s) en échec. Vérifiez les erreurs ci-dessus.")
