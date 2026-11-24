"""
Informações do PC para a tela "Visão geral" e recomendações simples.
Tudo com fallback: se algo não puder ser lido, o campo fica None.
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import shutil
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class SystemInfo:
    os_name: str = "Windows"
    cpu_name: str | None = None
    cpu_count: int | None = None
    ram_total: int | None = None
    ram_available: int | None = None
    disk_drive: str = "C:\\"
    disk_total: int | None = None
    disk_free: int | None = None
    uptime_seconds: float | None = None

    @property
    def ram_used_percent(self) -> float | None:
        if not self.ram_total or self.ram_available is None:
            return None
        return 100.0 * (self.ram_total - self.ram_available) / self.ram_total

    @property
    def disk_free_percent(self) -> float | None:
        if not self.disk_total or self.disk_free is None:
            return None
        return 100.0 * self.disk_free / self.disk_total


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def _read_reg(path: str, name: str):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return winreg.QueryValueEx(key, name)[0]
    except (ImportError, OSError):
        return None


def _windows_name() -> str:
    path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    product = _read_reg(path, "ProductName") or "Windows"
    display_version = _read_reg(path, "DisplayVersion")
    build = _read_reg(path, "CurrentBuildNumber") or _read_reg(path, "CurrentBuild")
    try:
        build_number = int(build) if build else 0
    except (TypeError, ValueError):
        build_number = 0
    # O registro do Windows 11 ainda diz "Windows 10" no ProductName.
    if build_number >= 22000 and "Windows 10" in product:
        product = product.replace("Windows 10", "Windows 11")
    parts = [product]
    if display_version:
        parts.append(str(display_version))
    if build_number:
        parts.append(f"(build {build_number})")
    return " ".join(parts)


def get_system_info() -> SystemInfo:
    info = SystemInfo(cpu_count=os.cpu_count())

    if sys.platform != "win32":
        info.os_name = f"{platform.system()} {platform.release()}"
        info.cpu_name = platform.processor() or None
        info.disk_drive = "/"
    else:
        info.os_name = _windows_name()
        cpu = _read_reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")
        info.cpu_name = " ".join(str(cpu).split()) if cpu else None
        info.disk_drive = os.environ.get("SystemDrive", "C:") + "\\"

        try:
            mem = _MEMORYSTATUSEX()
            mem.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
                info.ram_total = int(mem.ullTotalPhys)
                info.ram_available = int(mem.ullAvailPhys)
        except Exception:
            log.exception("GlobalMemoryStatusEx falhou")

        try:
            get_tick = ctypes.windll.kernel32.GetTickCount64
            get_tick.restype = ctypes.c_uint64
            info.uptime_seconds = get_tick() / 1000.0
        except Exception:
            log.exception("GetTickCount64 falhou")

    try:
        usage = shutil.disk_usage(info.disk_drive)
        info.disk_total, info.disk_free = usage.total, usage.free
    except OSError:
        pass

    return info


def build_recommendations(info: SystemInfo, startup_enabled: int | None = None,
                          damaged_services: int = 0, legacy_backups: int = 0) -> list[tuple[str, str]]:
    """
    Dicas a partir do estado do PC. Retorna (nível, texto), nível em
    "danger" | "warning" | "info" | "ok".
    """
    tips: list[tuple[str, str]] = []

    if damaged_services:
        tips.append(("danger", f"{damaged_services} serviço(s) do Windows foram danificados pela versão "
                               "anterior deste app. Abra 'Serviços' e clique em 'Reparar todos'."))
    if legacy_backups:
        tips.append(("info", f"{legacy_backups} programa(s) removidos da inicialização pela versão anterior "
                             "podem ser restaurados em 'Inicialização'."))

    free_pct = info.disk_free_percent
    if free_pct is not None and free_pct < 15:
        tips.append(("warning", f"Pouco espaço livre no disco do sistema ({free_pct:.0f}%). "
                                "Use a Limpeza - o Windows fica lento com o disco quase cheio."))

    ram_pct = info.ram_used_percent
    if ram_pct is not None and ram_pct >= 85:
        tips.append(("warning", f"Memória RAM em {ram_pct:.0f}% de uso. Feche programas que não está "
                                "usando ou desative itens da inicialização."))

    if startup_enabled is not None and startup_enabled > 8:
        tips.append(("warning", f"{startup_enabled} programas iniciam junto com o Windows. Desativar os "
                                "que você não usa todo dia deixa o boot bem mais rápido."))

    if info.uptime_seconds is not None and info.uptime_seconds > 3 * 86400:
        days = int(info.uptime_seconds // 86400)
        tips.append(("info", f"O PC está ligado há {days} dias. Use 'Reiniciar' de vez em quando: com a "
                             "Inicialização Rápida, 'Desligar' não limpa a memória do Windows."))

    if info.ram_total is not None and info.ram_total < 6 * 1024 ** 3:
        tips.append(("info", "Pouca memória RAM instalada. Manter poucos programas na inicialização "
                             "e poucas abas abertas no navegador faz bastante diferença."))

    if not tips:
        tips.append(("ok", "Tudo certo por aqui. Nenhum problema encontrado."))
    return tips
