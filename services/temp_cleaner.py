"""
Varre pastas de temporários/cache conhecidas e remove arquivos com segurança,
pulando qualquer coisa em uso ou protegida. Nunca lança exceção para o chamador.
"""

import os
import tempfile
from models import CleanupResult


class TempCleanerService:

    @staticmethod
    def get_default_target_folders() -> list[str]:
        """
        Pastas seguras para limpeza. Evitamos deliberadamente pastas de sistema
        mais sensíveis (ex: %WINDIR%\\Temp completo) para reduzir risco de quebrar algo.
        """
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        windir = os.environ.get("WINDIR", r"C:\Windows")

        candidates = [
            tempfile.gettempdir(),                                    # %TEMP% do usuário
            os.path.join(local_appdata, "Temp"),
            os.path.join(windir, "Prefetch"),
            os.path.join(local_appdata, "Microsoft", "Windows", "Explorer"),  # cache de thumbnails
        ]

        return [f for f in dict.fromkeys(candidates) if os.path.isdir(f)]

    def calculate_potential_space_freed(self, folders: list[str]) -> int:
        """Calcula quanto espaço seria liberado, sem apagar nada (modo preview)."""
        total = 0
        for folder in folders:
            for file_path in self._safe_walk_files(folder):
                total += self._safe_get_size(file_path)
        return total

    def clean(self, folders: list[str]) -> list[CleanupResult]:
        """Executa a limpeza de fato. Um erro em um arquivo não interrompe os demais."""
        results: list[CleanupResult] = []

        for folder in folders:
            deleted = 0
            freed = 0
            errors: list[str] = []

            for file_path in self._safe_walk_files(folder):
                try:
                    size = self._safe_get_size(file_path)
                    os.remove(file_path)
                    deleted += 1
                    freed += size
                except PermissionError:
                    errors.append(f"Sem permissão: {os.path.basename(file_path)}")
                except OSError:
                    # Cobre "arquivo em uso" (WinError 32) e outros erros de I/O.
                    errors.append(f"Em uso: {os.path.basename(file_path)}")

            results.append(CleanupResult(folder, deleted, freed, errors))

        return results

    @staticmethod
    def _safe_walk_files(folder: str):
        try:
            for root, _dirs, files in os.walk(folder):
                for name in files:
                    yield os.path.join(root, name)
        except OSError:
            return

    @staticmethod
    def _safe_get_size(path: str) -> int:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
