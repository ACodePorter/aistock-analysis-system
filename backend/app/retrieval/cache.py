import hashlib
import json
import os
import time
from typing import Any, Optional


class TTLFileCache:
    """Small file-based TTL cache for search/fetch/read stages."""

    def __init__(self, root_dir: str, default_ttl_seconds: int):
        self.root_dir = root_dir
        self.default_ttl_seconds = max(1, int(default_ttl_seconds))
        os.makedirs(self.root_dir, exist_ok=True)

    def _path(self, namespace: str, key: str) -> str:
        ns = namespace.strip().lower() or "default"
        ns_dir = os.path.join(self.root_dir, ns)
        os.makedirs(ns_dir, exist_ok=True)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return os.path.join(ns_dir, f"{digest}.json")

    def get(self, namespace: str, key: str) -> Optional[Any]:
        path = self._path(namespace, key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            expires_at = float(payload.get("expires_at", 0))
            if expires_at and expires_at < time.time():
                try:
                    os.remove(path)
                except OSError:
                    pass
                return None
            return payload.get("value")
        except Exception:
            return None

    def set(self, namespace: str, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        path = self._path(namespace, key)
        ttl = self.default_ttl_seconds if ttl_seconds is None else max(1, int(ttl_seconds))
        payload = {
            "expires_at": time.time() + ttl,
            "value": value,
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception:
            return
