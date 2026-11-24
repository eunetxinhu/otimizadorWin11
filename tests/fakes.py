"""
Implementações falsas (em memória) de winreg e win32service, fiéis o bastante
para testar a lógica dos managers em qualquer sistema operacional.

O FakeWin32Service confere os direitos de acesso de cada handle como o Service
Control Manager real faz, registra todas as chamadas de ChangeServiceConfig e
detecta handles não fechados.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ======================================================================= winreg

class _FakeKey:
    def __init__(self, reg: FakeWinreg, hive: int, path: str, access: int):
        self.reg = reg
        self.hive = hive
        self.path = path
        self.access = access

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.Close()
        return False

    def Close(self):
        pass


class FakeWinreg:
    HKEY_CURRENT_USER = 0x80000001
    HKEY_LOCAL_MACHINE = 0x80000002

    KEY_QUERY_VALUE = 0x0001
    KEY_SET_VALUE = 0x0002
    KEY_CREATE_SUB_KEY = 0x0004
    KEY_ENUMERATE_SUB_KEYS = 0x0008
    KEY_READ = 0x20019
    KEY_WRITE = 0x20006
    KEY_WOW64_64KEY = 0x0100
    KEY_WOW64_32KEY = 0x0200

    REG_SZ = 1
    REG_EXPAND_SZ = 2
    REG_BINARY = 3
    REG_DWORD = 4

    def __init__(self):
        # (hive, caminho em minúsculas) -> {nome em minúsculas: (nome, dado, tipo)}
        self.keys: dict[tuple[int, str], dict[str, tuple[str, object, int]]] = {}
        self.readonly: set[tuple[int, str]] = set()

    # ---------- helpers de teste

    def _resolve(self, hive: int, path: str, access: int) -> str:
        norm = path.strip("\\").lower()
        if (hive == self.HKEY_LOCAL_MACHINE and access & self.KEY_WOW64_32KEY
                and norm.startswith("software\\") and not norm.startswith("software\\wow6432node")):
            norm = "software\\wow6432node\\" + norm[len("software\\"):]
        return norm

    def set_value(self, hive, path, name, data, value_type=REG_SZ, wow32=False):
        norm = self._resolve(hive, path, self.KEY_WOW64_32KEY if wow32 else 0)
        self.keys.setdefault((hive, norm), {})[name.lower()] = (name, data, value_type)

    def get_value(self, hive, path, name, wow32=False):
        norm = self._resolve(hive, path, self.KEY_WOW64_32KEY if wow32 else 0)
        entry = self.keys.get((hive, norm), {}).get(name.lower())
        return None if entry is None else (entry[1], entry[2])

    def values(self, hive, path):
        return {v[0]: v[1] for v in self.keys.get((hive, self._resolve(hive, path, 0)), {}).values()}

    def make_readonly(self, hive, path):
        self.readonly.add((hive, self._resolve(hive, path, 0)))

    # ---------- API do winreg

    def OpenKey(self, key, sub_key, reserved=0, access=KEY_READ):
        norm = self._resolve(key, sub_key, access)
        if (key, norm) not in self.keys:
            raise FileNotFoundError(2, "O sistema não pode encontrar o arquivo especificado")
        return _FakeKey(self, key, norm, access)

    def CreateKeyEx(self, key, sub_key, reserved=0, access=KEY_WRITE):
        norm = self._resolve(key, sub_key, access)
        if (key, norm) in self.readonly:
            raise PermissionError(5, "Acesso negado")
        self.keys.setdefault((key, norm), {})
        return _FakeKey(self, key, norm, access)

    def EnumValue(self, key: _FakeKey, index: int):
        values = list(self.keys.get((key.hive, key.path), {}).values())
        if index >= len(values):
            raise OSError(259, "Não há mais dados disponíveis")
        return values[index]

    def QueryValueEx(self, key: _FakeKey, name: str):
        entry = self.keys.get((key.hive, key.path), {}).get(name.lower())
        if entry is None:
            raise FileNotFoundError(2, "não encontrado")
        return entry[1], entry[2]

    def SetValueEx(self, key: _FakeKey, name, reserved, value_type, value):
        if not key.access & self.KEY_SET_VALUE:
            raise PermissionError(5, "Acesso negado (handle sem KEY_SET_VALUE)")
        if (key.hive, key.path) in self.readonly:
            raise PermissionError(5, "Acesso negado")
        self.keys.setdefault((key.hive, key.path), {})[name.lower()] = (name, value, value_type)

    def DeleteValue(self, key: _FakeKey, name):
        if not key.access & self.KEY_SET_VALUE:
            raise PermissionError(5, "Acesso negado (handle sem KEY_SET_VALUE)")
        values = self.keys.get((key.hive, key.path), {})
        if name.lower() not in values:
            raise FileNotFoundError(2, "não encontrado")
        del values[name.lower()]


# ================================================================ win32service

class FakeServiceError(Exception):
    """Imita pywintypes.error (args = (winerror, funcname, strerror))."""

    def __init__(self, winerror, funcname="", strerror=""):
        super().__init__(winerror, funcname, strerror)
        self.winerror = winerror
        self.funcname = funcname
        self.strerror = strerror


@dataclass
class FakeService:
    name: str
    display_name: str
    service_type: int
    start: int
    binary_path: str
    state: int = 4  # SERVICE_RUNNING
    delayed: bool = False
    dependents_running: bool = False
    deny_change: bool = False
    stop_polls_needed: int = 2  # quantas consultas até STOP_PENDING virar STOPPED
    _pending_polls: int = field(default=0, repr=False)


class FakeWin32Service:
    SC_MANAGER_CONNECT = 0x0001
    SC_MANAGER_ENUMERATE_SERVICE = 0x0004
    SC_MANAGER_ALL_ACCESS = 0xF003F

    SERVICE_QUERY_CONFIG = 0x0001
    SERVICE_CHANGE_CONFIG = 0x0002
    SERVICE_QUERY_STATUS = 0x0004
    SERVICE_START = 0x0010
    SERVICE_STOP = 0x0020
    SERVICE_ALL_ACCESS = 0xF01FF

    SERVICE_BOOT_START = 0
    SERVICE_SYSTEM_START = 1
    SERVICE_AUTO_START = 2
    SERVICE_DEMAND_START = 3
    SERVICE_DISABLED = 4
    SERVICE_NO_CHANGE = 0xFFFFFFFF

    SERVICE_STOPPED = 1
    SERVICE_START_PENDING = 2
    SERVICE_STOP_PENDING = 3
    SERVICE_RUNNING = 4
    SERVICE_PAUSED = 7

    SERVICE_CONTROL_STOP = 1
    SERVICE_CONFIG_DELAYED_AUTO_START_INFO = 3

    error = FakeServiceError

    def __init__(self, services: list[FakeService]):
        self.services = {s.name.lower(): s for s in services}
        self.open_handles: dict[int, tuple] = {}
        self.change_calls: list[tuple] = []
        self._next_handle = 1

    # ---------- helpers

    def _new_handle(self, payload) -> int:
        handle = self._next_handle
        self._next_handle += 1
        self.open_handles[handle] = payload
        return handle

    def _svc(self, handle, needed_access) -> FakeService:
        kind, service, access = self.open_handles[handle]
        assert kind == "svc"
        if access & needed_access != needed_access:
            raise FakeServiceError(5, "access", "Acesso negado")
        return service

    # ---------- API

    def OpenSCManager(self, machine, database, access):
        return self._new_handle(("scm", None, access))

    def OpenService(self, scm, name, access):
        assert self.open_handles[scm][0] == "scm"
        service = self.services.get(name.lower())
        if service is None:
            raise FakeServiceError(1060, "OpenService", "O serviço especificado não existe.")
        return self._new_handle(("svc", service, access))

    def CloseServiceHandle(self, handle):
        del self.open_handles[handle]

    def QueryServiceConfig(self, handle):
        s = self._svc(handle, self.SERVICE_QUERY_CONFIG)
        return (s.service_type, s.start, 1, s.binary_path, "", 0, [], "LocalSystem", s.display_name)

    def QueryServiceConfig2(self, handle, level):
        s = self._svc(handle, self.SERVICE_QUERY_CONFIG)
        assert level == self.SERVICE_CONFIG_DELAYED_AUTO_START_INFO
        return s.delayed

    def QueryServiceStatus(self, handle):
        s = self._svc(handle, self.SERVICE_QUERY_STATUS)
        if s.state == self.SERVICE_STOP_PENDING:
            s._pending_polls += 1
            if s._pending_polls >= s.stop_polls_needed:
                s.state = self.SERVICE_STOPPED
        return (s.service_type, s.state, 0, 0, 0, 0, 0)

    def ChangeServiceConfig(self, handle, service_type, start, error_control, binary,
                            group, fetch_tag, deps, account, password, display_name):
        s = self._svc(handle, self.SERVICE_CHANGE_CONFIG)
        self.change_calls.append((s.name, service_type, start, error_control, binary,
                                  group, fetch_tag, deps, account, password, display_name))
        if s.deny_change:
            raise FakeServiceError(5, "ChangeServiceConfig", "Acesso negado")
        if service_type != self.SERVICE_NO_CHANGE:
            s.service_type = service_type
        if start != self.SERVICE_NO_CHANGE:
            s.start = start
        if binary is not None:
            s.binary_path = binary
        return None

    def ChangeServiceConfig2(self, handle, level, value):
        s = self._svc(handle, self.SERVICE_CHANGE_CONFIG)
        assert level == self.SERVICE_CONFIG_DELAYED_AUTO_START_INFO
        s.delayed = bool(value)

    def ControlService(self, handle, control):
        s = self._svc(handle, self.SERVICE_STOP)
        assert control == self.SERVICE_CONTROL_STOP
        if s.state == self.SERVICE_STOPPED:
            raise FakeServiceError(1062, "ControlService", "O serviço não foi iniciado.")
        if s.dependents_running:
            raise FakeServiceError(1051, "ControlService", "Há serviços dependentes em execução.")
        s.state = self.SERVICE_STOP_PENDING
        s._pending_polls = 0
        return (s.service_type, s.state, 0, 0, 0, 0, 0)

    def StartService(self, handle, args):
        s = self._svc(handle, self.SERVICE_START)
        if s.start == self.SERVICE_DISABLED:
            raise FakeServiceError(1058, "StartService", "O serviço está desativado.")
        if s.state == self.SERVICE_RUNNING:
            raise FakeServiceError(1056, "StartService", "Já está em execução.")
        s.state = self.SERVICE_RUNNING
