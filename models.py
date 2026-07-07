"""
Modelos de dados usados pelo eunetxinhu otimizações.
Usamos dataclasses simples em vez de classes complexas - é o suficiente
pra representar os itens que a UI mostra e os managers manipulam.
"""

from dataclasses import dataclass, field
from enum import Enum


class ServiceRisk(str, Enum):
    """Nível de risco de desativar um serviço do Windows."""
    SAFE = "Seguro"
    CAUTION = "Cautela"
    CRITICAL = "Crítico"  # nunca oferecido na UI


@dataclass
class StartupItem:
    name: str
    command: str
    location: str          # "HKCU\\...\\Run" ou "HKLM\\...\\Run"
    is_machine_wide: bool  # True = HKEY_LOCAL_MACHINE (precisa admin)
    is_enabled: bool = True  # controlado pelo checkbox na UI


@dataclass
class ServiceItem:
    service_name: str      # nome interno, ex: "Fax"
    display_name: str
    status: str             # Running, Stopped...
    start_type: str          # Automatic, Manual, Disabled
    risk: ServiceRisk
    explanation: str


@dataclass
class CleanupResult:
    folder_path: str
    files_deleted: int
    bytes_freed: int
    errors: list[str] = field(default_factory=list)
