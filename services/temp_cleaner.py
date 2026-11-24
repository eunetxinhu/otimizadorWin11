"""
Limpeza de arquivos temporários e caches, por categorias.

Regras de segurança:
- Nunca segue links simbólicos, junctions nem outros "reparse points": uma
  junction dentro do %TEMP% apontando para Documentos NÃO faz o app apagar
  seus documentos (os.walk entraria nela).
- Por padrão ignora arquivos mexidos nas últimas 24 h - instaladores e
  programas abertos costumam usar o %TEMP% enquanto rodam.
- Arquivo em uso/sem permissão é só pulado; um erro nunca interrompe o resto.
- A pasta temporária do próprio app (.exe do PyInstaller) é sempre ignorada.
- Nunca lança exceção para o chamador.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import stat
import sys
import threading
import time
from dataclasses import dataclass, replace
from collections.abc import Callable, Iterator

from models import CleanupResult, ScanResult
from services.recycle_bin import RecycleBin

log = logging.getLogger(__name__)

FILE_ATTRIBUTE_READONLY = 0x0001
FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
RECENT_FILE_HOURS = 24
_MAX_ERROR_SAMPLES = 20
_PROGRESS_EVERY = 250

ProgressCallback = Callable[[str, int], None]


@dataclass(frozen=True)
class CleanupCategory:
    key: str
    title: str
    description: str
    folders: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()   # se definido, só arquivos com esses nomes (ex: "*.pf")
    recursive: bool = True
    use_age_filter: bool = True      # respeita a opção "ignorar arquivos recentes"
    default_selected: bool = True
    warning: str = ""
    is_recycle_bin: bool = False


@dataclass
class _Entry:
    path: str
    is_dir: bool
    size: int
    newest: float      # mais recente entre modificação e criação
    readonly: bool = False


def _env(env: dict[str, str], name: str) -> str:
    lowered = name.lower()
    for key, value in env.items():
        if key.lower() == lowered:
            return value
    return ""


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def build_default_categories(env: dict[str, str] | None = None,
                             include_recycle_bin: bool | None = None) -> list[CleanupCategory]:
    env = dict(os.environ) if env is None else env
    local = _env(env, "LOCALAPPDATA")
    windir = _env(env, "SystemRoot") or _env(env, "WINDIR") or r"C:\Windows"
    programdata = _env(env, "ProgramData") or _env(env, "ALLUSERSPROFILE")

    def join(base: str, *parts: str) -> str:
        return os.path.join(base, *parts) if base else ""

    raw = [
        CleanupCategory(
            "user_temp", "Temporários do usuário",
            "Arquivos que programas e instaladores deixam para trás no %TEMP%.",
            folders=(_env(env, "TEMP"), _env(env, "TMP"), join(local, "Temp")),
        ),
        CleanupCategory(
            "windows_temp", "Temporários do Windows",
            "Pasta Temp do sistema (C:\\Windows\\Temp).",
            folders=(join(windir, "Temp"),),
        ),
        CleanupCategory(
            "error_reports", "Relatórios de erro",
            "Relatórios de travamentos já enviados ou na fila (Relatório de Erros do Windows).",
            folders=(
                join(local, "Microsoft", "Windows", "WER", "ReportArchive"),
                join(local, "Microsoft", "Windows", "WER", "ReportQueue"),
                join(programdata, "Microsoft", "Windows", "WER", "ReportArchive"),
                join(programdata, "Microsoft", "Windows", "WER", "ReportQueue"),
            ),
            use_age_filter=False,
        ),
        CleanupCategory(
            "thumbnails", "Cache de miniaturas",
            "Miniaturas de fotos e vídeos do Explorer. O Windows recria quando precisar; "
            "arquivos em uso pelo Explorer são pulados.",
            folders=(join(local, "Microsoft", "Windows", "Explorer"),),
            patterns=("thumbcache_*.db",), recursive=False, use_age_filter=False,
        ),
        CleanupCategory(
            "windows_update", "Downloads do Windows Update",
            "Instaladores de atualizações já baixados. O Windows baixa de novo se precisar.",
            folders=(join(windir, "SoftwareDistribution", "Download"),),
            default_selected=False,
        ),
        CleanupCategory(
            "recycle_bin", "Lixeira",
            "Esvazia a Lixeira de todas as unidades. Não dá para desfazer.",
            default_selected=False, use_age_filter=False, is_recycle_bin=True,
        ),
        CleanupCategory(
            "prefetch", "Prefetch",
            "Arquivos que o Windows usa para abrir programas mais rápido.",
            folders=(join(windir, "Prefetch"),), patterns=("*.pf",), recursive=False,
            use_age_filter=False, default_selected=False,
            warning="Não recomendado: apagar deixa o próximo boot e a abertura dos programas "
                    "MAIS LENTOS até o Windows reconstruir esses arquivos.",
        ),
    ]

    if include_recycle_bin is None:
        include_recycle_bin = RecycleBin().available()

    seen: set[str] = set()
    categories: list[CleanupCategory] = []
    for cat in raw:
        if cat.is_recycle_bin:
            if include_recycle_bin:
                categories.append(cat)
            continue
        folders = []
        for folder in cat.folders:
            if not folder or not os.path.isdir(folder):
                continue
            key = _norm(folder)
            if key in seen:  # ex: %TEMP% e %LOCALAPPDATA%\Temp costumam ser a mesma pasta
                continue
            seen.add(key)
            folders.append(folder)
        if folders:
            categories.append(replace(cat, folders=tuple(folders)))
    return categories


def _is_link(entry: os.DirEntry, st: os.stat_result) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    if getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
        return True  # junctions, links, arquivos "na nuvem" do OneDrive...
    is_junction = getattr(entry, "is_junction", None)  # Python 3.12+
    if is_junction is not None:
        try:
            return is_junction()
        except OSError:
            return True
    return False


def _newest(st: os.stat_result) -> float:
    birth = getattr(st, "st_birthtime", None)  # criação (Windows, Python 3.12+)
    second = birth if birth is not None else st.st_ctime  # no Windows antigo, ctime = criação
    return max(st.st_mtime, second)


def _walk(root: str, recursive: bool, patterns: tuple[str, ...],
          excluded: set[str], cancel: threading.Event | None) -> Iterator[_Entry]:
    """Percorre a pasta sem seguir links. Pastas vêm antes do conteúdo delas."""
    stack = [root]
    while stack:
        if cancel is not None and cancel.is_set():
            return
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if _is_link(entry, st):
                continue
            if stat.S_ISDIR(st.st_mode):
                if recursive and _norm(entry.path) not in excluded:
                    stack.append(entry.path)
                    yield _Entry(entry.path, True, 0, _newest(st))
            elif stat.S_ISREG(st.st_mode):
                if patterns and not any(fnmatch.fnmatch(entry.name.lower(), p) for p in patterns):
                    continue
                readonly = bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_READONLY)
                yield _Entry(entry.path, False, st.st_size, _newest(st), readonly)


def _own_runtime_dirs() -> set[str]:
    """Pasta onde o .exe do PyInstaller se extrai - apagar isso quebraria o app aberto."""
    meipass = getattr(sys, "_MEIPASS", None)
    return {_norm(meipass)} if meipass else set()


class TempCleanerService:

    def __init__(self, categories: list[CleanupCategory] | None = None,
                 recycle_bin: RecycleBin | None = None, clock=time.time,
                 excluded_dirs: set[str] | None = None):
        self._recycle_bin = recycle_bin if recycle_bin is not None else RecycleBin()
        self._categories = (categories if categories is not None
                            else build_default_categories(include_recycle_bin=self._recycle_bin.available()))
        self._clock = clock
        self._excluded = {_norm(p) for p in (excluded_dirs or set())} | _own_runtime_dirs()

    @property
    def categories(self) -> list[CleanupCategory]:
        return list(self._categories)

    def get_category(self, key: str) -> CleanupCategory | None:
        return next((c for c in self._categories if c.key == key), None)

    # ================================================================ Prévia

    def scan(self, keys: list[str], skip_recent: bool = True,
             cancel: threading.Event | None = None,
             progress: ProgressCallback | None = None) -> dict[str, ScanResult]:
        """Calcula quanto seria liberado, sem apagar nada."""
        now = self._clock()
        results: dict[str, ScanResult] = {}
        for cat in self._selected(keys):
            result = ScanResult(cat.key)
            results[cat.key] = result
            if cat.is_recycle_bin:
                info = self._recycle_bin.query()
                if info:
                    result.bytes, result.files = info
                continue
            min_age = self._min_age(cat, skip_recent)
            for folder in cat.folders:
                for entry in _walk(folder, cat.recursive, cat.patterns, self._excluded, cancel):
                    if entry.is_dir:
                        continue
                    if now - entry.newest < min_age:
                        result.skipped_recent += 1
                        continue
                    result.files += 1
                    result.bytes += entry.size
                    if progress and result.files % _PROGRESS_EVERY == 0:
                        progress(cat.title, result.files)
            if cancel is not None and cancel.is_set():
                break
        return results

    # ================================================================ Limpeza

    def clean(self, keys: list[str], skip_recent: bool = True,
              cancel: threading.Event | None = None,
              progress: ProgressCallback | None = None) -> list[CleanupResult]:
        """Apaga de fato. Um erro em um arquivo não interrompe os demais."""
        now = self._clock()
        results: list[CleanupResult] = []
        for cat in self._selected(keys):
            if cancel is not None and cancel.is_set():
                break
            result = CleanupResult(cat.key, cat.title)
            results.append(result)
            if cat.is_recycle_bin:
                self._empty_recycle_bin(result)
                continue
            min_age = self._min_age(cat, skip_recent)
            processed = 0
            for folder in cat.folders:
                old_dirs: list[str] = []
                for entry in _walk(folder, cat.recursive, cat.patterns, self._excluded, cancel):
                    old_enough = now - entry.newest >= min_age
                    if entry.is_dir:
                        if old_enough:
                            old_dirs.append(entry.path)
                        continue
                    if not old_enough:
                        result.skipped_recent += 1
                        continue
                    self._delete_file(entry, result)
                    processed += 1
                    if progress and processed % _PROGRESS_EVERY == 0:
                        progress(cat.title, processed)
                # Remove pastas que ficaram vazias, das mais fundas para as de cima.
                # A raiz da categoria nunca é removida.
                for path in reversed(old_dirs):
                    if cancel is not None and cancel.is_set():
                        break
                    try:
                        os.rmdir(path)
                        result.dirs_removed += 1
                    except OSError:
                        pass
            log.info("Limpeza %s: %d arquivos, %d bytes, %d pastas, %d em uso, %d recentes",
                     cat.key, result.files_deleted, result.bytes_freed, result.dirs_removed,
                     result.skipped_in_use, result.skipped_recent)
        return results

    # ================================================================ Interno

    def _selected(self, keys: list[str]) -> list[CleanupCategory]:
        wanted = set(keys)
        return [c for c in self._categories if c.key in wanted]

    @staticmethod
    def _min_age(cat: CleanupCategory, skip_recent: bool) -> float:
        return RECENT_FILE_HOURS * 3600 if (skip_recent and cat.use_age_filter) else 0.0

    @staticmethod
    def _delete_file(entry: _Entry, result: CleanupResult) -> None:
        try:
            if entry.readonly:
                os.chmod(entry.path, stat.S_IWRITE)  # tira o "somente leitura" do Windows
            os.remove(entry.path)
        except FileNotFoundError:
            return  # outro processo já apagou
        except PermissionError:
            result.skipped_in_use += 1
            if len(result.errors) < _MAX_ERROR_SAMPLES:
                result.errors.append(f"Sem permissão ou em uso: {os.path.basename(entry.path)}")
            return
        except OSError:
            # Cobre "arquivo em uso por outro processo" (WinError 32) e afins.
            result.skipped_in_use += 1
            if len(result.errors) < _MAX_ERROR_SAMPLES:
                result.errors.append(f"Em uso: {os.path.basename(entry.path)}")
            return
        result.files_deleted += 1
        result.bytes_freed += entry.size

    def _empty_recycle_bin(self, result: CleanupResult) -> None:
        before = self._recycle_bin.query()
        if before is None:
            result.errors.append("Não foi possível ler a Lixeira.")
            return
        if before[1] == 0:
            return
        if self._recycle_bin.empty():
            result.bytes_freed, result.files_deleted = before
            log.info("Lixeira esvaziada: %d itens, %d bytes", before[1], before[0])
        else:
            result.errors.append("Não foi possível esvaziar a Lixeira.")
