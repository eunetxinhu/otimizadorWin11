"""
Gerencia serviços do Windows pela API do Service Control Manager (pywin32,
módulo win32service).

Segurança:
- Só serviços da WHITELIST abaixo podem ser alterados; qualquer outro nome é
  recusado aqui mesmo, independente do que a UI pedir.
- Antes de desativar, o tipo de inicialização original é salvo em backup.json,
  para o botão "Reativar" devolver exatamente como estava.
- Só o TIPO DE INICIALIZAÇÃO é alterado. Executável, tipo de processo, conta
  e dependências são passados como "sem alteração" para a API.

Por que isso importa (bug da v1.0): a versão anterior usava
win32serviceutil.ChangeServiceConfig, que é feito para serviços escritos em
Python - além de mudar a inicialização ele TROCA o executável do serviço pelo
pythonservice.exe (ou pelo próprio .exe do otimizador, quando empacotado) e
força o tipo para "processo próprio". Serviços desativados pela v1.0 ficaram
quebrados. Este módulo detecta isso (is_damaged) e repara (repair_service),
gravando de volta o executável e o tipo padrão do Windows 11.

Requer: pip install pywin32
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass

from models import ActionResult, ServiceItem, ServiceRisk, ServiceState, StartType
from services.backup_store import BackupStore
from services.cmdline import executable_name, expand_windows_vars

log = logging.getLogger(__name__)

# Tipos de processo (winnt.h) - valores fixos do Windows.
SERVICE_WIN32_OWN_PROCESS = 0x10
SERVICE_WIN32_SHARE_PROCESS = 0x20

# Códigos de erro Win32 relevantes.
ERROR_ACCESS_DENIED = 5
ERROR_DEPENDENT_SERVICES_RUNNING = 1051
ERROR_SERVICE_ALREADY_RUNNING = 1056
ERROR_SERVICE_DOES_NOT_EXIST = 1060
ERROR_SERVICE_NOT_ACTIVE = 1062

_SVCHOST_NETSVCS = r"%SystemRoot%\system32\svchost.exe -k netsvcs -p"


@dataclass(frozen=True)
class ServiceSpec:
    risk: ServiceRisk
    explanation: str
    default_image: str        # ImagePath padrão do Windows 11 (usado no reparo)
    default_type: int         # tipo de processo padrão (usado no reparo)
    default_start: StartType  # inicialização padrão (usada no "Reativar" sem backup)


# Whitelist curada. Qualquer serviço fora dela é tratado como crítico:
# não aparece na UI e não pode ser alterado.
WHITELIST: dict[str, ServiceSpec] = {
    "Fax": ServiceSpec(
        ServiceRisk.SAFE, "Serviço de fax. Praticamente ninguém usa hoje em dia.",
        r"%SystemRoot%\system32\fxssvc.exe", SERVICE_WIN32_OWN_PROCESS, StartType.MANUAL),
    "WSearch": ServiceSpec(
        ServiceRisk.CAUTION,
        "Windows Search (indexação). Economiza disco e CPU, mas a busca do menu Iniciar "
        "e do Explorer fica mais lenta.",
        r"%SystemRoot%\system32\SearchIndexer.exe /Embedding", SERVICE_WIN32_OWN_PROCESS,
        StartType.AUTOMATIC_DELAYED),
    "XblAuthManager": ServiceSpec(
        ServiceRisk.SAFE, "Autenticação Xbox Live. Só necessário se você joga com conta Xbox.",
        _SVCHOST_NETSVCS, SERVICE_WIN32_SHARE_PROCESS, StartType.MANUAL),
    "XblGameSave": ServiceSpec(
        ServiceRisk.SAFE, "Sincronização de saves do Xbox Live.",
        _SVCHOST_NETSVCS, SERVICE_WIN32_SHARE_PROCESS, StartType.MANUAL),
    "XboxNetApiSvc": ServiceSpec(
        ServiceRisk.SAFE, "Serviço de rede do Xbox.",
        _SVCHOST_NETSVCS, SERVICE_WIN32_SHARE_PROCESS, StartType.MANUAL),
    "DiagTrack": ServiceSpec(
        ServiceRisk.CAUTION, "Telemetria da Microsoft. Reduz coleta de dados, não afeta o uso normal.",
        r"%SystemRoot%\system32\svchost.exe -k utcsvc -p", SERVICE_WIN32_OWN_PROCESS,
        StartType.AUTOMATIC),
    "MapsBroker": ServiceSpec(
        ServiceRisk.SAFE, "Atualização de mapas offline do app Mapas.",
        r"%SystemRoot%\System32\svchost.exe -k NetworkService -p", SERVICE_WIN32_SHARE_PROCESS,
        StartType.AUTOMATIC_DELAYED),
    "RetailDemo": ServiceSpec(
        ServiceRisk.SAFE, "Modo demonstração de loja. Inútil em PC pessoal.",
        r"%SystemRoot%\System32\svchost.exe -k rdxgroup", SERVICE_WIN32_SHARE_PROCESS,
        StartType.MANUAL),
    "WMPNetworkSvc": ServiceSpec(
        ServiceRisk.SAFE, "Compartilhamento de rede do Windows Media Player.",
        r'"%ProgramFiles%\Windows Media Player\wmpnetwk.exe"', SERVICE_WIN32_OWN_PROCESS,
        StartType.MANUAL),
    "PrintNotify": ServiceSpec(
        ServiceRisk.CAUTION, "Notificações de impressão. Só desative se não usa impressora.",
        r"%SystemRoot%\system32\svchost.exe -k print", SERVICE_WIN32_SHARE_PROCESS,
        StartType.MANUAL),
}


@dataclass
class _ServiceInfo:
    service_type: int
    start_type: StartType
    binary_path: str
    display_name: str
    state: ServiceState


def _winerror(exc: BaseException) -> int | None:
    code = getattr(exc, "winerror", None)
    if code is None and exc.args and isinstance(exc.args[0], int):
        code = exc.args[0]
    return code


def _describe_error(exc: BaseException) -> str:
    code = _winerror(exc)
    if code == ERROR_ACCESS_DENIED:
        return "acesso negado (o app precisa estar rodando como administrador)"
    if code == ERROR_SERVICE_DOES_NOT_EXIST:
        return "o serviço não existe neste Windows"
    text = getattr(exc, "strerror", None) or str(exc)
    return f"{text} (código {code})" if code is not None else text


def _env_get(env: dict[str, str], name: str) -> str | None:
    """Busca sem diferenciar maiúsculas/minúsculas (como o Windows faz)."""
    lowered = name.lower()
    for key, value in env.items():
        if key.lower() == lowered and value:
            return value
    return None


class ServiceManager:

    def __init__(self, api=None, backup: BackupStore | None = None,
                 whitelist: dict[str, ServiceSpec] | None = None,
                 env: dict[str, str] | None = None,
                 sleep=time.sleep, stop_timeout: float = 15.0):
        if api is None:
            import win32service as api  # import tardio: só existe no Windows
        self._api = api
        self._backup = backup if backup is not None else BackupStore()
        self._whitelist = whitelist if whitelist is not None else WHITELIST
        self._env = env if env is not None else dict(os.environ)
        self._sleep = sleep
        self._stop_timeout = stop_timeout

        a = api
        self._start_code_map = {
            a.SERVICE_BOOT_START: StartType.BOOT,
            a.SERVICE_SYSTEM_START: StartType.SYSTEM,
            a.SERVICE_AUTO_START: StartType.AUTOMATIC,
            a.SERVICE_DEMAND_START: StartType.MANUAL,
            a.SERVICE_DISABLED: StartType.DISABLED,
        }
        self._state_map = {
            a.SERVICE_RUNNING: ServiceState.RUNNING,
            a.SERVICE_STOPPED: ServiceState.STOPPED,
            a.SERVICE_PAUSED: ServiceState.PAUSED,
            a.SERVICE_START_PENDING: ServiceState.STARTING,
            a.SERVICE_STOP_PENDING: ServiceState.STOPPING,
        }

    @property
    def whitelist(self) -> dict[str, ServiceSpec]:
        return self._whitelist

    # ================================================================ Leitura

    def get_manageable_services(self) -> list[ServiceItem]:
        """Retorna apenas os serviços da whitelist que existem neste PC, com estado atual."""
        result: list[ServiceItem] = []
        for name, spec in self._whitelist.items():
            info = self._query(name)
            if info is None:
                continue  # serviço não existe nesta instalação do Windows
            result.append(ServiceItem(
                service_name=name,
                display_name=info.display_name or name,
                state=info.state,
                start_type=info.start_type,
                risk=spec.risk,
                explanation=spec.explanation,
                binary_path=info.binary_path,
                is_damaged=self._is_damaged(spec, info.binary_path),
                has_backup=self._backup.get_service_original(name) is not None,
            ))
        return result

    def get_damaged_services(self) -> list[ServiceItem]:
        return [s for s in self.get_manageable_services() if s.is_damaged]

    # ================================================================ Ações

    def disable_service(self, service_name: str) -> ActionResult:
        """Configura o serviço como Desativado e para ele se estiver rodando."""
        if service_name not in self._whitelist:
            log.warning("Recusado desativar serviço fora da whitelist: %s", service_name)
            return ActionResult(False, "Este serviço não está na lista de serviços seguros.")

        info = self._query(service_name)
        if info is None:
            return ActionResult(False, "Serviço não encontrado neste Windows.")

        if info.start_type != StartType.DISABLED:
            self._backup.save_service_original(service_name, info.start_type.value)

        try:
            self._change_start_type(service_name, StartType.DISABLED)
        except Exception as exc:
            log.exception("Falha ao desativar %s", service_name)
            return ActionResult(False, f"Não foi possível desativar: {_describe_error(exc)}.")

        # Conferência de segurança: o executável tem que continuar o mesmo.
        after = self._query(service_name)
        if after is not None and after.binary_path != info.binary_path:
            log.error("Executável de %s mudou inesperadamente: %r -> %r",
                      service_name, info.binary_path, after.binary_path)

        state = self._stop(service_name)
        log.info("Serviço %s desativado (antes: %s; estado agora: %s)",
                 service_name, info.start_type.value, state.value)
        if state in (ServiceState.STOPPED, ServiceState.STOPPING):
            return ActionResult(True, "Serviço desativado e parado.")
        return ActionResult(True, "Serviço desativado. Ele vai parar de vez na próxima reinicialização.")

    def restore_service(self, service_name: str) -> ActionResult:
        """
        Reativa o serviço com o tipo de inicialização original (do backup) ou,
        se não houver backup, com o padrão do Windows 11.
        """
        spec = self._whitelist.get(service_name)
        if spec is None:
            return ActionResult(False, "Este serviço não está na lista de serviços seguros.")

        info = self._query(service_name)
        if info is None:
            return ActionResult(False, "Serviço não encontrado neste Windows.")
        if self._is_damaged(spec, info.binary_path):
            # Reativar um serviço danificado faria o Windows executar o
            # executável errado como serviço. Tem que reparar antes.
            return ActionResult(False, "Este serviço está danificado. Use 'Reparar' antes de reativar.")
        if info.start_type != StartType.DISABLED:
            self._backup.remove_service_original(service_name)
            return ActionResult(True, "O serviço já está ativo.")

        target = self._resolve_original_start(service_name, spec)
        try:
            self._change_start_type(service_name, target)
        except Exception as exc:
            log.exception("Falha ao reativar %s", service_name)
            return ActionResult(False, f"Não foi possível reativar: {_describe_error(exc)}.")

        self._backup.remove_service_original(service_name)
        if target in (StartType.AUTOMATIC, StartType.AUTOMATIC_DELAYED):
            self._start(service_name)
        log.info("Serviço %s reativado como %s", service_name, target.value)
        return ActionResult(True, f"Serviço reativado ({target.label}).")

    def repair_service(self, service_name: str) -> ActionResult:
        """Devolve o executável e o tipo de processo padrão a um serviço danificado pela v1.0."""
        spec = self._whitelist.get(service_name)
        if spec is None:
            return ActionResult(False, "Este serviço não está na lista de serviços seguros.")

        info = self._query(service_name)
        if info is None:
            return ActionResult(False, "Serviço não encontrado neste Windows.")
        if not self._is_damaged(spec, info.binary_path):
            return ActionResult(True, "Serviço íntegro, não precisa de reparo.")

        image = self._expand_default_image(spec.default_image)
        api = self._api
        try:
            with self._open_service(service_name, api.SERVICE_CHANGE_CONFIG | api.SERVICE_QUERY_CONFIG) as svc:
                api.ChangeServiceConfig(
                    svc,
                    spec.default_type,       # tipo de processo original
                    api.SERVICE_NO_CHANGE,   # mantém a inicialização atual
                    api.SERVICE_NO_CHANGE,
                    image,                   # executável original
                    None, 0, None, None, None, None,
                )
        except Exception as exc:
            log.exception("Falha ao reparar %s", service_name)
            return ActionResult(False, f"Não foi possível reparar: {_describe_error(exc)}.")

        after = self._query(service_name)
        if after is None or self._is_damaged(spec, after.binary_path):
            return ActionResult(False, "O reparo não foi confirmado. Tente de novo como administrador.")

        log.info("Serviço %s reparado: %r -> %r", service_name, info.binary_path, image)
        return ActionResult(True, "Serviço reparado. Use 'Reativar' se quiser ligá-lo de novo.")

    def repair_all_damaged(self) -> dict[str, ActionResult]:
        return {s.service_name: self.repair_service(s.service_name) for s in self.get_damaged_services()}

    # ================================================================ Interno

    def _resolve_original_start(self, service_name: str, spec: ServiceSpec) -> StartType:
        saved = self._backup.get_service_original(service_name)
        try:
            target = StartType(saved) if saved else spec.default_start
        except ValueError:
            target = spec.default_start
        if target in (StartType.DISABLED, StartType.UNKNOWN, StartType.BOOT, StartType.SYSTEM):
            target = spec.default_start
        return target

    @staticmethod
    def _is_damaged(spec: ServiceSpec, binary_path: str) -> bool:
        if not binary_path:
            return False
        return executable_name(binary_path) != executable_name(spec.default_image)

    def _expand_default_image(self, template: str) -> str:
        system_root = (_env_get(self._env, "SystemRoot") or _env_get(self._env, "WINDIR")
                       or r"C:\Windows")
        # ProgramW6432 aponta para "Program Files" de 64 bits mesmo num Python 32 bits.
        program_files = (_env_get(self._env, "ProgramW6432") or _env_get(self._env, "ProgramFiles")
                         or r"C:\Program Files")
        return expand_windows_vars(template, {"SystemRoot": system_root, "ProgramFiles": program_files})

    @contextmanager
    def _open_service(self, service_name: str, access: int):
        api = self._api
        scm = api.OpenSCManager(None, None, api.SC_MANAGER_CONNECT)
        try:
            svc = api.OpenService(scm, service_name, access)
            try:
                yield svc
            finally:
                api.CloseServiceHandle(svc)
        finally:
            api.CloseServiceHandle(scm)

    def _query(self, service_name: str) -> _ServiceInfo | None:
        api = self._api
        try:
            with self._open_service(service_name, api.SERVICE_QUERY_CONFIG | api.SERVICE_QUERY_STATUS) as svc:
                config = api.QueryServiceConfig(svc)
                status = api.QueryServiceStatus(svc)
                start_type = self._start_code_map.get(config[1], StartType.UNKNOWN)
                if start_type == StartType.AUTOMATIC:
                    try:
                        if api.QueryServiceConfig2(svc, api.SERVICE_CONFIG_DELAYED_AUTO_START_INFO):
                            start_type = StartType.AUTOMATIC_DELAYED
                    except Exception:
                        pass
        except Exception as exc:
            if _winerror(exc) != ERROR_SERVICE_DOES_NOT_EXIST:
                log.warning("Não foi possível consultar o serviço %s: %s", service_name, exc)
            return None

        return _ServiceInfo(
            service_type=config[0],
            start_type=start_type,
            binary_path=config[3] or "",
            display_name=config[8] if len(config) > 8 else service_name,
            state=self._state_map.get(status[1], ServiceState.UNKNOWN),
        )

    def _change_start_type(self, service_name: str, start: StartType) -> None:
        api = self._api
        code = {
            StartType.AUTOMATIC: api.SERVICE_AUTO_START,
            StartType.AUTOMATIC_DELAYED: api.SERVICE_AUTO_START,
            StartType.MANUAL: api.SERVICE_DEMAND_START,
            StartType.DISABLED: api.SERVICE_DISABLED,
        }[start]

        with self._open_service(service_name, api.SERVICE_CHANGE_CONFIG | api.SERVICE_QUERY_CONFIG) as svc:
            # Tudo além da inicialização vai como "sem alteração" (SERVICE_NO_CHANGE / None).
            api.ChangeServiceConfig(
                svc,
                api.SERVICE_NO_CHANGE,  # tipo de processo
                code,                   # inicialização
                api.SERVICE_NO_CHANGE,  # controle de erro
                None,                   # executável
                None, 0, None,          # grupo, tag, dependências
                None, None, None,       # conta, senha, nome de exibição
            )
            if start in (StartType.AUTOMATIC, StartType.AUTOMATIC_DELAYED):
                try:
                    api.ChangeServiceConfig2(
                        svc, api.SERVICE_CONFIG_DELAYED_AUTO_START_INFO,
                        start == StartType.AUTOMATIC_DELAYED,
                    )
                except Exception:
                    log.warning("Não foi possível ajustar o início atrasado de %s", service_name)

    def _stop(self, service_name: str) -> ServiceState:
        api = self._api
        try:
            with self._open_service(service_name, api.SERVICE_STOP | api.SERVICE_QUERY_STATUS) as svc:
                state = api.QueryServiceStatus(svc)[1]
                if state == api.SERVICE_STOPPED:
                    return ServiceState.STOPPED
                try:
                    api.ControlService(svc, api.SERVICE_CONTROL_STOP)
                except Exception as exc:
                    if _winerror(exc) == ERROR_SERVICE_NOT_ACTIVE:
                        return ServiceState.STOPPED
                    if _winerror(exc) == ERROR_DEPENDENT_SERVICES_RUNNING:
                        log.info("%s tem dependentes rodando; para no próximo boot", service_name)
                    else:
                        log.warning("Não foi possível parar %s: %s", service_name, exc)
                    return self._state_map.get(state, ServiceState.UNKNOWN)

                waited = 0.0
                while waited < self._stop_timeout:
                    state = api.QueryServiceStatus(svc)[1]
                    if state == api.SERVICE_STOPPED:
                        break
                    self._sleep(0.25)
                    waited += 0.25
                return self._state_map.get(state, ServiceState.UNKNOWN)
        except Exception as exc:
            log.warning("Não foi possível parar %s: %s", service_name, exc)
            return ServiceState.UNKNOWN

    def _start(self, service_name: str) -> None:
        api = self._api
        try:
            with self._open_service(service_name, api.SERVICE_START) as svc:
                api.StartService(svc, None)
        except Exception as exc:
            if _winerror(exc) != ERROR_SERVICE_ALREADY_RUNNING:
                log.info("Serviço %s reativado, mas não iniciou agora: %s", service_name, exc)
