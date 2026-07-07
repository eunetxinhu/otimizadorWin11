"""
Gerencia serviços do Windows via pywin32. Por segurança, o app NUNCA deixa o
usuário desativar um serviço que não esteja na whitelist abaixo - mesmo que a
UI tente chamar, disable_service() recusa qualquer coisa fora da lista.

Requer: pip install pywin32
"""

import win32service
import win32serviceutil
from models import ServiceItem, ServiceRisk

# Mapeamento dos códigos de start type do Windows para texto legível.
_START_TYPE_MAP = {
    win32service.SERVICE_AUTO_START: "Automatic",
    win32service.SERVICE_DEMAND_START: "Manual",
    win32service.SERVICE_DISABLED: "Disabled",
    win32service.SERVICE_BOOT_START: "Boot",
    win32service.SERVICE_SYSTEM_START: "System",
}

_STATUS_MAP = {
    win32service.SERVICE_RUNNING: "Running",
    win32service.SERVICE_STOPPED: "Stopped",
    win32service.SERVICE_PAUSED: "Paused",
    win32service.SERVICE_START_PENDING: "Starting",
    win32service.SERVICE_STOP_PENDING: "Stopping",
}

# Whitelist curada: nome interno do serviço -> (risco, explicação).
# Qualquer serviço fora dessa lista é tratado como Critical por padrão -
# a UI nem deve oferecer a opção de desativar.
WHITELIST: dict[str, tuple[ServiceRisk, str]] = {
    "Fax": (ServiceRisk.SAFE, "Serviço de fax. Praticamente ninguém usa em 2026."),
    "WSearch": (ServiceRisk.CAUTION, "Windows Search. Economiza recursos, mas a busca do menu Iniciar fica mais lenta."),
    "XblAuthManager": (ServiceRisk.SAFE, "Autenticação Xbox Live. Só necessário se você joga com conta Xbox."),
    "XblGameSave": (ServiceRisk.SAFE, "Sincronização de saves do Xbox Live."),
    "XboxNetApiSvc": (ServiceRisk.SAFE, "Serviço de rede do Xbox."),
    "DiagTrack": (ServiceRisk.CAUTION, "Telemetria da Microsoft. Reduz coleta de dados, não afeta uso normal."),
    "MapsBroker": (ServiceRisk.SAFE, "Atualização de mapas offline do app Mapas."),
    "RetailDemo": (ServiceRisk.SAFE, "Modo demonstração de loja. Inútil em PC pessoal."),
    "WMPNetworkSvc": (ServiceRisk.SAFE, "Compartilhamento de rede do Windows Media Player."),
    "PrintNotify": (ServiceRisk.CAUTION, "Notificações de impressão. Só desative se não usa impressora."),
}


class ServiceManager:

    def get_manageable_services(self) -> list[ServiceItem]:
        """Retorna apenas os serviços presentes na whitelist, com status atual."""
        result: list[ServiceItem] = []

        for service_name, (risk, explanation) in WHITELIST.items():
            info = self._query_service(service_name)
            if info is None:
                continue  # serviço não existe nesta instalação do Windows

            status, start_type, display_name = info
            result.append(ServiceItem(
                service_name=service_name,
                display_name=display_name,
                status=status,
                start_type=start_type,
                risk=risk,
                explanation=explanation,
            ))

        return result

    def disable_service(self, service_name: str) -> bool:
        """
        Desativa um serviço (para e configura como Disabled).
        Recusa qualquer serviço fora da whitelist - segunda camada de proteção
        além da checagem feita na UI.
        """
        if service_name not in WHITELIST:
            return False

        try:
            win32serviceutil.ChangeServiceConfig(
                None, service_name, startType=win32service.SERVICE_DISABLED
            )
            self._stop_if_running(service_name)
            return True
        except Exception:
            return False

    def restore_service(self, service_name: str, original_start_type: str) -> bool:
        """Reverte um serviço para seu tipo de inicialização original."""
        reverse_map = {v: k for k, v in _START_TYPE_MAP.items()}
        start_code = reverse_map.get(original_start_type, win32service.SERVICE_AUTO_START)

        try:
            win32serviceutil.ChangeServiceConfig(None, service_name, startType=start_code)
            return True
        except Exception:
            return False

    @staticmethod
    def _stop_if_running(service_name: str) -> None:
        try:
            if win32serviceutil.QueryServiceStatus(service_name)[1] == win32service.SERVICE_RUNNING:
                win32serviceutil.StopService(service_name)
        except Exception:
            pass  # serviço pode já estar parado, ou não aceitar parada - não é fatal

    @staticmethod
    def _query_service(service_name: str):
        """Retorna (status, start_type, display_name) ou None se o serviço não existir."""
        try:
            handle_scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)
            handle_svc = win32service.OpenService(
                handle_scm, service_name, win32service.SERVICE_QUERY_CONFIG | win32service.SERVICE_QUERY_STATUS
            )

            config = win32service.QueryServiceConfig(handle_svc)
            status = win32service.QueryServiceStatus(handle_svc)

            start_type = _START_TYPE_MAP.get(config[1], "Desconhecido")
            status_text = _STATUS_MAP.get(status[1], "Desconhecido")
            display_name = config[8] if len(config) > 8 else service_name

            win32service.CloseServiceHandle(handle_svc)
            win32service.CloseServiceHandle(handle_scm)

            return status_text, start_type, display_name
        except Exception:
            return None
