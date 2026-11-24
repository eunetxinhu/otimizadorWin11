"""
Guarda, em um JSON local, o estado original do que o app altera - hoje, o tipo
de inicialização dos serviços antes de serem desativados. É isso que permite
o botão "Reativar" devolver o serviço exatamente como estava.

Arquivo: %LOCALAPPDATA%\\EunetxinhuOtimizacoes\\backup.json
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, UTC
from pathlib import Path

log = logging.getLogger(__name__)


class BackupStore:

    def __init__(self, path: Path | str | None = None):
        if path is None:
            from app_info import data_dir
            path = data_dir() / "backup.json"
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    # ---------- Serviços

    def get_service_original(self, service_name: str) -> str | None:
        entry = self._load().get("services", {}).get(service_name)
        return entry.get("start_type") if isinstance(entry, dict) else None

    def save_service_original(self, service_name: str, start_type: str) -> None:
        """Salva o tipo original - só na primeira vez, para nunca sobrescrever com 'desativado'."""
        with self._lock:
            data = self._load()
            services = data.setdefault("services", {})
            if service_name in services:
                return
            services[service_name] = {
                "start_type": start_type,
                "saved_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            self._save(data)

    def remove_service_original(self, service_name: str) -> None:
        with self._lock:
            data = self._load()
            if data.get("services", {}).pop(service_name, None) is not None:
                self._save(data)

    # ---------- Interno

    def _load(self) -> dict:
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            log.exception("Backup ilegível em %s - ignorando", self._path)
            return {}

    def _save(self, data: dict) -> None:
        # Escrita atômica: grava num .tmp e troca - um crash no meio nunca
        # deixa o backup corrompido pela metade.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)
