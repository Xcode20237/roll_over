"""
minio_reader.py — Récupération d'images depuis MinIO en base64 pour l'UI web.
"""
from __future__ import annotations
import base64
from typing import Optional

from config import MINIO_ENDPOINT, MINIO_USER, MINIO_PASS

try:
    from minio import Minio
    _client = Minio(MINIO_ENDPOINT, access_key=MINIO_USER,
                    secret_key=MINIO_PASS, secure=False)
    MINIO_OK = True
except Exception:
    MINIO_OK = False


def get_image_b64(bucket: str, chemin: str) -> Optional[str]:
    """
    Retourne l'image MinIO encodée en base64 pour affichage dans <img src=...>.
    Retourne None si indisponible.
    """
    if not MINIO_OK:
        return None
    try:
        resp = _client.get_object(bucket, chemin)
        data = resp.read()
        resp.close()
        resp.release_conn()
        return "data:image/jpeg;base64," + base64.b64encode(data).decode()
    except Exception as e:
        print(f"[MinIO] Erreur {bucket}/{chemin}: {e}")
        return None
