"""
Gerencia programas que iniciam com o Windows.

Desativar/ativar usa o MESMO mecanismo do Gerenciador de Tarefas e de
Configurações > Apps > Inicialização: os valores binários em
  ...\\Explorer\\StartupApproved\\{Run, Run32, StartupFolder}
Nada é apagado do registro nem das pastas - o item continua listado e pode ser
reativado a qualquer momento (aqui ou pelo próprio Gerenciador de Tarefas).

Fontes lidas:
- HKCU\\...\\Run                          (programas do usuário)
- HKLM\\...\\Run   (visão 64 bits)          (programas de todos os usuários)
- HKLM\\...\\Run   (visão 32 bits / WOW6432Node)
- Pasta Inicializar do usuário e a comum (atalhos .lnk etc.)

A versão 1.0 do app APAGAVA o valor do Run e guardava uma cópia em
HKCU\\SOFTWARE\\EunetxinhuOtimizacoes\\StartupBackup; esses itens podem ser
restaurados por get_legacy_backups()/restore_legacy_backup().
"""

from __future__ import annotations

import logging
import ntpath
import os
import struct
import time
from dataclasses import dataclass

from models import ActionResult, LegacyStartupBackup, StartupItem, StartupSource
from services.cmdline import executable_path

log = logging.getLogger(__name__)

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
LEGACY_BACKUP_KEY_PATH = r"SOFTWARE\EunetxinhuOtimizacoes\StartupBackup"

# Formato dos valores em StartupApproved (12 bytes): o 1º byte par = ativo
# (02/06), ímpar = desativado (03/07); quando desativado, os 8 últimos bytes
# guardam a data/hora (FILETIME) em que foi desativado.
_ENABLED_VALUE = bytes([0x02] + [0x00] * 11)
_FILETIME_EPOCH_OFFSET = 11644473600  # segundos entre 1601-01-01 e 1970-01-01


@dataclass(frozen=True)
class _RegistrySource:
    source: StartupSource
    hive_name: str       # nome do atributo no winreg (HKEY_CURRENT_USER...)
    view_flag_name: str  # "" ou KEY_WOW64_64KEY / KEY_WOW64_32KEY
    approved_subkey: str


_REGISTRY_SOURCES = (
    _RegistrySource(StartupSource.HKCU_RUN, "HKEY_CURRENT_USER", "", "Run"),
    _RegistrySource(StartupSource.HKLM_RUN, "HKEY_LOCAL_MACHINE", "KEY_WOW64_64KEY", "Run"),
    _RegistrySource(StartupSource.HKLM_RUN32, "HKEY_LOCAL_MACHINE", "KEY_WOW64_32KEY", "Run32"),
)


def _default_startup_folders() -> dict[StartupSource, str]:
    appdata = os.environ.get("APPDATA", "")
    programdata = os.environ.get("PROGRAMDATA", os.environ.get("ALLUSERSPROFILE", ""))
    folders = {}
    if appdata:
        folders[StartupSource.USER_FOLDER] = os.path.join(
            appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    if programdata:
        folders[StartupSource.COMMON_FOLDER] = os.path.join(
            programdata, "Microsoft", "Windows", "Start Menu", "Programs", "StartUp")
    return folders


def is_enabled_value(data) -> bool:
    """Interpreta um valor de StartupApproved. Valor ausente/estranho = ativo."""
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        return True
    return data[0] & 0x01 == 0


def disabled_value(timestamp: float) -> bytes:
    filetime = int((timestamp + _FILETIME_EPOCH_OFFSET) * 10_000_000)
    return bytes([0x03, 0x00, 0x00, 0x00]) + struct.pack("<Q", filetime)


class StartupManager:

    def __init__(self, reg=None, startup_folders: dict[StartupSource, str] | None = None,
                 path_exists=os.path.exists, clock=time.time):
        if reg is None:
            import winreg as reg  # import tardio: só existe no Windows
        self._reg = reg
        self._folders = startup_folders if startup_folders is not None else _default_startup_folders()
        self._path_exists = path_exists
        self._clock = clock

    # ================================================================ Leitura

    def get_startup_items(self) -> list[StartupItem]:
        """Lista todos os itens de inicialização, com o estado real (ativo/desativado)."""
        items: list[StartupItem] = []
        seen_machine: set[tuple[str, str]] = set()

        for src in _REGISTRY_SOURCES:
            approved = self._read_approved(src.hive_name, src.approved_subkey)
            for name, command in self._read_values(src.hive_name, RUN_KEY_PATH, src.view_flag_name):
                if src.source.is_machine_wide:
                    # Em sistemas sem WOW64 as duas visões são a mesma chave.
                    key = (name.lower(), command.lower())
                    if key in seen_machine:
                        continue
                    seen_machine.add(key)
                items.append(StartupItem(
                    name=name,
                    command=command,
                    source=src.source,
                    is_enabled=is_enabled_value(approved.get(name.lower())),
                    target_missing=self._target_missing(command),
                ))

        for source, folder in self._folders.items():
            approved_hive = "HKEY_LOCAL_MACHINE" if source.is_machine_wide else "HKEY_CURRENT_USER"
            approved = self._read_approved(approved_hive, "StartupFolder")
            for file_name in self._list_folder(folder):
                items.append(StartupItem(
                    name=file_name,
                    command=os.path.join(folder, file_name),
                    source=source,
                    is_enabled=is_enabled_value(approved.get(file_name.lower())),
                ))

        return items

    # ================================================================ Ações

    def set_enabled(self, item: StartupItem, enabled: bool) -> ActionResult:
        """Ativa/desativa um item do jeito do Gerenciador de Tarefas (reversível)."""
        hive_name, subkey = self._approved_location(item.source)
        value = _ENABLED_VALUE if enabled else disabled_value(self._clock())
        try:
            with self._create_key(hive_name, f"{APPROVED_KEY_PATH}\\{subkey}") as key:
                self._reg.SetValueEx(key, item.name, 0, self._reg.REG_BINARY, value)
        except PermissionError:
            return ActionResult(False, "Sem permissão (o app precisa estar rodando como administrador).")
        except OSError as exc:
            log.exception("Falha ao alterar inicialização de %s", item.name)
            return ActionResult(False, f"Erro do Windows: {exc}")

        item.is_enabled = enabled
        log.info("Inicialização %s: %s (%s)", "ativada" if enabled else "desativada",
                 item.name, item.location)
        return ActionResult(True, "Ativado." if enabled else "Desativado.")

    def disable_startup_item(self, item: StartupItem) -> ActionResult:
        return self.set_enabled(item, False)

    def enable_startup_item(self, item: StartupItem) -> ActionResult:
        return self.set_enabled(item, True)

    # ================================================= Backups da versão 1.0

    def get_legacy_backups(self) -> list[LegacyStartupBackup]:
        return [LegacyStartupBackup(name, command)
                for name, command in self._read_values("HKEY_CURRENT_USER", LEGACY_BACKUP_KEY_PATH, "")]

    def restore_legacy_backup(self, entry: LegacyStartupBackup) -> ActionResult:
        """
        Devolve à inicialização um item que a v1.0 apagou. Como a v1.0 não
        guardava se o item era do usuário ou da máquina, ele volta para o
        HKCU\\...\\Run (inicia para este usuário).
        """
        reg = self._reg
        existing = {n.lower() for n, _ in self._read_values("HKEY_CURRENT_USER", RUN_KEY_PATH, "")}
        try:
            if entry.name.lower() not in existing:
                value_type = reg.REG_EXPAND_SZ if "%" in entry.command else reg.REG_SZ
                with self._create_key("HKEY_CURRENT_USER", RUN_KEY_PATH) as key:
                    reg.SetValueEx(key, entry.name, 0, value_type, entry.command)
            self._delete_legacy_value(entry.name)
        except OSError as exc:
            log.exception("Falha ao restaurar backup legado %s", entry.name)
            return ActionResult(False, f"Não foi possível restaurar: {exc}")

        log.info("Item legado restaurado: %s", entry.name)
        if entry.name.lower() in existing:
            return ActionResult(True, "O programa já estava na inicialização; backup removido.")
        return ActionResult(True, "Restaurado na inicialização.")

    def discard_legacy_backup(self, entry: LegacyStartupBackup) -> ActionResult:
        try:
            self._delete_legacy_value(entry.name)
        except OSError as exc:
            return ActionResult(False, f"Não foi possível descartar: {exc}")
        log.info("Backup legado descartado: %s", entry.name)
        return ActionResult(True, "Backup descartado.")

    # ================================================================ Interno

    @staticmethod
    def _approved_location(source: StartupSource) -> tuple[str, str]:
        return {
            StartupSource.HKCU_RUN: ("HKEY_CURRENT_USER", "Run"),
            StartupSource.HKLM_RUN: ("HKEY_LOCAL_MACHINE", "Run"),
            StartupSource.HKLM_RUN32: ("HKEY_LOCAL_MACHINE", "Run32"),
            StartupSource.USER_FOLDER: ("HKEY_CURRENT_USER", "StartupFolder"),
            StartupSource.COMMON_FOLDER: ("HKEY_LOCAL_MACHINE", "StartupFolder"),
        }[source]

    def _access(self, base: int, hive_name: str, view_flag_name: str = "") -> int:
        reg = self._reg
        access = base
        if view_flag_name:
            access |= getattr(reg, view_flag_name)
        elif hive_name == "HKEY_LOCAL_MACHINE":
            # StartupApproved da máquina sempre na visão nativa de 64 bits.
            access |= reg.KEY_WOW64_64KEY
        return access

    def _create_key(self, hive_name: str, path: str):
        reg = self._reg
        return reg.CreateKeyEx(getattr(reg, hive_name), path, 0,
                               self._access(reg.KEY_SET_VALUE | reg.KEY_QUERY_VALUE, hive_name))

    def _read_values(self, hive_name: str, path: str, view_flag_name: str) -> list[tuple[str, str]]:
        reg = self._reg
        result: list[tuple[str, str]] = []
        try:
            with reg.OpenKey(getattr(reg, hive_name), path, 0,
                             self._access(reg.KEY_READ, hive_name, view_flag_name)) as key:
                index = 0
                while True:
                    try:
                        name, data, _type = reg.EnumValue(key, index)
                    except OSError:
                        break  # fim da lista (é assim que o winreg sinaliza)
                    index += 1
                    if not name:
                        continue  # valor "(Padrão)" não é item de inicialização
                    result.append((name, data if isinstance(data, str) else str(data)))
        except FileNotFoundError:
            pass  # a chave não existe neste sistema
        except OSError as exc:
            log.warning("Não foi possível ler %s\\%s: %s", hive_name, path, exc)
        return result

    def _read_approved(self, hive_name: str, subkey: str) -> dict[str, bytes]:
        reg = self._reg
        result: dict[str, bytes] = {}
        try:
            with reg.OpenKey(getattr(reg, hive_name), f"{APPROVED_KEY_PATH}\\{subkey}", 0,
                             self._access(reg.KEY_READ, hive_name)) as key:
                index = 0
                while True:
                    try:
                        name, data, _type = reg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    result[name.lower()] = data
        except OSError:
            pass
        return result

    def _delete_legacy_value(self, name: str) -> None:
        reg = self._reg
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, LEGACY_BACKUP_KEY_PATH, 0, reg.KEY_SET_VALUE) as key:
                reg.DeleteValue(key, name)
        except FileNotFoundError:
            pass

    @staticmethod
    def _list_folder(folder: str) -> list[str]:
        try:
            with os.scandir(folder) as entries:
                return sorted(
                    e.name for e in entries
                    if e.is_file() and e.name.lower() != "desktop.ini"
                )
        except OSError:
            return []

    def _target_missing(self, command: str) -> bool:
        path = ntpath.expandvars(executable_path(command))
        if not path or not ntpath.isabs(path):
            return False  # ex: "rundll32.exe ..." - resolvido pelo PATH, não dá pra afirmar
        return not self._path_exists(path)
