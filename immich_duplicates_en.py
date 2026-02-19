"""
🧹 Immich duplicate cleanup script
-----------------------------------------

This script was developed by Sébastien Castermans, with the help of AI, to identify and retain
the best version of duplicate files (photos/videos) on an Immich server via its API.
It allows you to efficiently delete duplicates based on criteria such as creation date, HEIC
format (Apple original), file size, and EXIF metadata.
The duplicate detection setting is specific to your Immich installation and can be modified
in the server's administration settings.

💡 Features :
- Intelligent sorting to keep the best version of a file, first the oldest, then priority to
HEIC files (Apple originals), otherwise according to size, and finally EXIF metadata.
- Simulation option (dry run) to test without deleting
- Delete to recycle bin or permanently delete
- Detailed logging to a .log file if enabled
- Ability to view files with their URLs in the logs

Configuration can be provided via environment variables:
  IMMICH_SERVER, IMMICH_API_KEY, IMMICH_ENABLE_LOG, IMMICH_DRY_RUN, IMMICH_DEFINITELY,
  IMMICH_ONLY_PAIRS, IMMICH_KEEP_METADATA, IMMICH_TRANSFER_METADATA, IMMICH_CONFIRM,
  IMMICH_REQUEST_TIMEOUT, IMMICH_DELETE_BATCH_SIZE

Improvements welcome! Feel free to share with attribution.
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


# User configuration (from env vars, with fallbacks):
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

# Step 1: Retrieve duplicates
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
    print(f"[ERROR] Failed to retrieve duplicates, server {SERVER} unreachable or invalid API key.")
    exit(1)
if not duplicates:
    print("[INFO] No duplicates found. Nothing to delete.")
    exit(0)
print(f"[INFO] Found {len(duplicates)} duplicate groups.")


# Step 2: Prepare the files to be deleted
def get_asset_info(asset):
    exif = asset.get('exifInfo', {})
    try:
        date = datetime.fromisoformat(exif.get('dateTimeOriginal'))
    except (ValueError, TypeError):
        date = datetime.max  # Worst date if empty
    is_heic = 1 if asset['originalFileName'].lower().endswith('.heic') else 0
    size = exif.get('fileSizeInByte')
    exif_count = sum(1 for v in exif.values() if v is not None and (not isinstance(v, str) or v.strip() != ""))
    return (date, is_heic, size, exif_count)

def select_best_asset(assets):
    remaining = assets[:]
    length = len(remaining)
    reason = "identical files with the criteria (date, heic, size, exif)"

    # Step 1: Earliest date
    min_date = min(get_asset_info(a)[0] for a in remaining)
    remaining = [a for a in remaining if get_asset_info(a)[0] == min_date]
    if len(remaining) == 1:
        reason = "older"
        return remaining[0], reason
    if length != len(remaining):
        reason = "older"
        length = len(remaining)

    # Step 2: Priority to .heic
    heic = max(get_asset_info(a)[1] for a in remaining)
    remaining = [a for a in remaining if get_asset_info(a)[1] == heic]
    if len(remaining) == 1:
        reason = "heic extension"
        return remaining[0], reason
    if length != len(remaining):
        reason = "heic extension"
        length = len(remaining)

    # Step 3: larger size
    max_size = max(get_asset_info(a)[2] for a in remaining)
    remaining = [a for a in remaining if get_asset_info(a)[2] == max_size]
    if len(remaining) == 1:
        reason = "larger size"
        return remaining[0], reason
    if length != len(remaining):
        reason = "larger size"
        length = len(remaining)

    # Step 4: More EXIF fields
    max_exif = max(get_asset_info(a)[3] for a in remaining)
    remaining = [a for a in remaining if get_asset_info(a)[3] == max_exif]
    if len(remaining) == 1:
        reason = "more exif data"
        return remaining[0], reason
    if length != len(remaining):
        reason = "more exif data"
        length = len(remaining)

    # Final equality
    return remaining[0], reason


def _has_exif_value(asset, key):
    """Check if asset has a non-empty EXIF value."""
    exif = asset.get('exifInfo') or {}
    val = exif.get(key)
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    return True


def _get_kept_tags_ids(kept):
    """Return set of tag IDs the kept asset has."""
    tags = kept.get('tags') or []
    return {t['id'] for t in tags if t.get('id')}


def remove_kept_metadata(kept, headers_get, headers_json):
    """Remove albums and tags from kept asset when KEEP_METADATA=false."""
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
                    print(f"[WARN] Could not remove kept from album {album.get('albumName', album['id'])}: {del_resp.status_code}")
            except requests.RequestException as e:
                print(f"[WARN] Error removing kept from album: {e}")
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
                    print(f"[WARN] Could not remove tag {tag.get('name', tag_id)} from kept: {del_resp.status_code}")
            except requests.RequestException as e:
                print(f"[WARN] Error removing tag from kept: {e}")
    except requests.RequestException as e:
        print(f"[WARN] Error fetching kept albums: {e}")


def transfer_metadata_to_kept(kept, to_delete_assets, headers_get, headers_json):
    """Transfer metadata from to_delete assets to kept (augment only, never overwrite)."""
    kept_id = kept['id']
    original_kept_tags = _get_kept_tags_ids(kept)
    tags_to_add = set()
    exif_to_set = {}  # fields to transfer: only where kept has none and to_delete has value

    for to_del in to_delete_assets:
        # Albums: add kept to each album to_delete is in
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
                            pass  # already in album
                        else:
                            print(f"[WARN] Could not add kept to album: {add_resp.status_code}")
                except requests.RequestException as e:
                    print(f"[WARN] Error adding kept to album: {e}")
        except requests.RequestException as e:
            print(f"[WARN] Error fetching albums for to_delete {to_del['id']}: {e}")

        # Tags: add only tags kept doesn't have
        for tag in (to_del.get('tags') or []):
            tag_id = tag.get('id')
            if tag_id and tag_id not in original_kept_tags and tag_id not in tags_to_add:
                tags_to_add.add(tag_id)
        # EXIF: only fill gaps (to_delete has, kept doesn't)
        exif = to_del.get('exifInfo') or {}
        for key in ('latitude', 'longitude', 'description', 'dateTimeOriginal', 'rating'):
            if key in exif_to_set:
                continue  # already set from earlier to_delete
            if _has_exif_value(to_del, key) and not _has_exif_value(kept, key):
                raw = exif.get(key)
                if raw is not None:
                    exif_to_set[key] = raw

    # Apply tags in one call (only new ones)
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
                print(f"[WARN] Could not add tags to kept: {tag_resp.status_code}")
        except requests.RequestException as e:
            print(f"[WARN] Error adding tags to kept: {e}")

    # Apply EXIF in one call (only fields we're filling)
    if exif_to_set:
        payload = {"ids": [kept_id], **{k: v for k, v in exif_to_set.items()}}
        try:
            update_resp = requests.put(
                f"{SERVER}/api/assets", headers=headers_json, data=json.dumps(payload),
                timeout=REQUEST_TIMEOUT
            )
            if update_resp.status_code not in (200, 204):
                print(f"[WARN] Could not update EXIF on kept: {update_resp.status_code}")
        except requests.RequestException as e:
            print(f"[WARN] Error updating EXIF on kept: {e}")


HEADERS_JSON = {
    'Content-Type': 'application/json',
    'x-api-key': API_KEY
}
HEADERS_GET = {'Accept': 'application/json', 'x-api-key': API_KEY}

ids_to_delete = []
processed_groups = []  # (kept, to_delete_assets) for metadata ops when not CONFIRM

i = 0
for group in duplicates:
    i = i + 1
    assets = group.get('assets')
    if ONLY_PAIRS and len(assets) != 2:
        print(f"[SKIPPED] Duplicates n°{i} ({len(assets)} files) - only pairs mode, manual selection recommended")
        continue
    kept, reason = select_best_asset(assets)
    to_delete_assets = [a for a in assets if a['id'] != kept['id']]
    to_delete_ids = [a['id'] for a in to_delete_assets]
    date, is_heic, size, exif_count = get_asset_info(kept)
    date_str = date.strftime('%d/%m/%y - %H:%M:%S') if date != datetime.max else "??/??/??"
    print(f"\n[INFO] Duplicates n°{i} ({len(assets)} files), conservation reason : '{reason}'")
    print(f"[KEPT]\t\tDate : {date_str}\tSize : {round(size/1024/1024,2)}MB\t\tNumber of EXIF : {exif_count}\t{kept['originalFileName']} --> {SERVER}/api/assets/{kept['id']}/thumbnail?size=preview")
    for asset in to_delete_assets:
        date, is_heic, size, exif_count = get_asset_info(asset)
        date_str = date.strftime('%d/%m/%y - %H:%M:%S') if date != datetime.max else "??/??/??"
        print(f"[DELETED]\tDate : {date_str}\tSize : {round(size/1024/1024,2)}MB\t\tNumber of EXIF : {exif_count}\t{asset['originalFileName']} --> {SERVER}/api/assets/{asset['id']}/thumbnail?size=preview")

    if CONFIRM:
        reply = input("Process this group? [Y/n] ").strip().lower()
        if reply == 'n':
            continue
        if DRY_RUN:
            print(f"[INFO] Group {i} would be processed (dry run).")
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
                print(f"[SUCCESS] Group {i} processed ({len(to_delete_ids)} asset(s) deleted).")
            except requests.RequestException:
                status = delete_response.status_code if delete_response is not None else "N/A"
                text = delete_response.text if delete_response is not None else "N/A"
                print(f"[ERROR] Deletion failed for group {i}: {status}")
                print(f"[DEBUG] API response: {text}")
    else:
        ids_to_delete.extend(to_delete_ids)
        processed_groups.append((kept, to_delete_assets))
        if i % 500 == 0:
            print(f"[INFO] Processed groups 1-{i} / {len(duplicates)}...")

# Step 3: Non-CONFIRM path – metadata operations then bulk delete (only when not dry run)
if DRY_RUN:
    print("\n[INFO] Simulation mode enabled. No actual deletion performed.")
    exit(0)

if not CONFIRM:
    total_groups = len(processed_groups)
    if total_groups > 0:
        print(f"[INFO] Transferring metadata for {total_groups} groups...")
    for idx, (kept, to_delete_assets) in enumerate(processed_groups):
        if (idx + 1) % 100 == 0:
            print(f"[INFO] Metadata progress: {idx + 1}/{total_groups} groups...")
        if not KEEP_METADATA:
            remove_kept_metadata(kept, HEADERS_GET, HEADERS_JSON)
        if TRANSFER_METADATA and to_delete_assets:
            transfer_metadata_to_kept(kept, to_delete_assets, HEADERS_GET, HEADERS_JSON)

    total = len(ids_to_delete)
    num_batches = (total + DELETE_BATCH_SIZE - 1) // DELETE_BATCH_SIZE
    print(f"[INFO] Deleting {total} assets in {num_batches} batches (batch size: {DELETE_BATCH_SIZE})...")
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
            print(f"[INFO] Batch {batch_num}/{num_batches}: {len(batch_ids)} assets deleted.")
        except requests.RequestException as e:
            failed_batches += 1
            text = delete_response.text if delete_response is not None else str(e)
            print(f"[ERROR] Batch {batch_num} failed: {e}")
            print(f"[DEBUG] API response: {text}")
    if failed_batches == 0:
        print(f"\n[SUCCESS] Deletion complete. {total} assets removed.")
    else:
        print(f"\n[WARN] Deletion finished with {failed_batches} failed batch(es). Check errors above.")
