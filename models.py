"""
Modelos de dados usados pelo eunetxinhu otimizações.
Dataclasses e enums simples - o suficiente para representar o que a UI
mostra e o que os managers manipulam.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass
class ActionResult:
    """Resultado de uma ação feita pelo usuário (desativar, restaurar...)."""
    ok: bool
    message: str

    def __bool__(self) -> bool:
        return self.ok


# ---------------------------------------------------------------- Serviços

class ServiceRisk(str, Enum):
    """Nível de risco de desativar um serviço do Windows."""
    SAFE = "Seguro"
    CAUTION = "Cautela"
    CRITICAL = "Crítico"  # nunca oferecido na UI


class StartType(str, Enum):
    """Tipo de inicialização de um serviço."""
    BOOT = "boot"
    SYSTEM = "system"
    AUTOMATIC = "auto"
    AUTOMATIC_DELAYED = "auto_delayed"
    MANUAL = "manual"
    DISABLED = "disabled"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return _START_TYPE_LABELS[self]


_START_TYPE_LABELS = {
    StartType.BOOT: "Boot",
    StartType.SYSTEM: "Sistema",
    StartType.AUTOMATIC: "Automático",
    StartType.AUTOMATIC_DELAYED: "Automático (atraso)",
    StartType.MANUAL: "Manual",
    StartType.DISABLED: "Desativado",
    StartType.UNKNOWN: "Desconhecido",
}


class ServiceState(str, Enum):
    """Estado atual de execução de um serviço."""
    RUNNING = "running"
    STOPPED = "stopped"
    PAUSED = "paused"
    STARTING = "starting"
    STOPPING = "stopping"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return _STATE_LABELS[self]


_STATE_LABELS = {
    ServiceState.RUNNING: "Em execução",
    ServiceState.STOPPED: "Parado",
    ServiceState.PAUSED: "Pausado",
    ServiceState.STARTING: "Iniciando",
    ServiceState.STOPPING: "Parando",
    ServiceState.UNKNOWN: "Desconhecido",
}


@dataclass
class ServiceItem:
    service_name: str          # nome interno, ex: "Fax"
    display_name: str
    state: ServiceState
    start_type: StartType
    risk: ServiceRisk
    explanation: str
    binary_path: str = ""
    is_damaged: bool = False   # executável trocado pela v1.0 do app (ver service_manager)
    has_backup: bool = False   # sabemos o tipo de inicialização original

    @property
    def is_disabled(self) -> bool:
        return self.start_type == StartType.DISABLED


# ---------------------------------------------------------- Inicialização

class StartupSource(str, Enum):
    """De onde vem um item de inicialização."""
    HKCU_RUN = "HKCU Run"
    HKLM_RUN = "HKLM Run"
    HKLM_RUN32 = "HKLM Run (32 bits)"
    USER_FOLDER = "Pasta Inicializar"
    COMMON_FOLDER = "Pasta Inicializar (todos)"

    @property
    def is_machine_wide(self) -> bool:
        return self in (StartupSource.HKLM_RUN, StartupSource.HKLM_RUN32, StartupSource.COMMON_FOLDER)

    @property
    def is_folder(self) -> bool:
        return self in (StartupSource.USER_FOLDER, StartupSource.COMMON_FOLDER)


@dataclass
class StartupItem:
    name: str              # nome do valor no registro, ou nome do arquivo na pasta Inicializar
    command: str           # linha de comando (ou caminho do atalho)
    source: StartupSource
    is_enabled: bool = True
    target_missing: bool = False  # o executável apontado não existe mais

    @property
    def location(self) -> str:
        return self.source.value

    @property
    def is_machine_wide(self) -> bool:
        return self.source.is_machine_wide


@dataclass
class LegacyStartupBackup:
    """Item que a versão 1.0 removeu do registro (e guardou em backup)."""
    name: str
    command: str


# ----------------------------------------------------------------- Limpeza

@dataclass
class ScanResult:
    """Prévia de uma categoria de limpeza (nada é apagado)."""
    category_key: str
    files: int = 0
    bytes: int = 0
    skipped_recent: int = 0


@dataclass
class CleanupResult:
    category_key: str
    title: str
    files_deleted: int = 0
    bytes_freed: int = 0
    dirs_removed: int = 0
    skipped_in_use: int = 0
    skipped_recent: int = 0
    errors: list[str] = field(default_factory=list)  # amostra (limitada) dos erros
