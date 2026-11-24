"""
Testes de integração contra o Windows DE VERDADE (registro, Service Control
Manager, sistema de arquivos NTFS). Rodam no CI (GitHub Actions, windows-latest),
numa máquina descartável. Fora do Windows são pulados.

Os testes que alteram serviços/registro desfazem tudo ao final, mas mesmo
assim só devem rodar em máquinas de teste.
"""

import ctypes
import os
import stat
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="somente Windows")

if sys.platform == "win32":
    import win32service
    import winreg

    from models import ServiceRisk, StartType
    from services.backup_store import BackupStore
    from services.recycle_bin import RecycleBin
    from services.service_manager import SERVICE_WIN32_SHARE_PROCESS, ServiceManager, ServiceSpec
    from services.startup_manager import APPROVED_KEY_PATH, RUN_KEY_PATH, StartupManager
    from services.system_info import get_system_info
    from services.temp_cleaner import CleanupCategory, TempCleanerService, build_default_categories


def _is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


needs_admin = pytest.mark.skipif(sys.platform == "win32" and not _is_admin(), reason="requer administrador")


# ===================================================================== serviços

def _raw_config(name):
    scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    try:
        svc = win32service.OpenService(scm, name, win32service.SERVICE_QUERY_CONFIG)
        try:
            config = win32service.QueryServiceConfig(svc)
            delayed = False
            if config[1] == win32service.SERVICE_AUTO_START:
                delayed = bool(win32service.QueryServiceConfig2(
                    svc, win32service.SERVICE_CONFIG_DELAYED_AUTO_START_INFO))
            return {"type": config[0], "start": config[1], "binary": config[3], "delayed": delayed}
        finally:
            win32service.CloseServiceHandle(svc)
    finally:
        win32service.CloseServiceHandle(scm)


def _raw_set_start(name, start, delayed):
    scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    try:
        svc = win32service.OpenService(scm, name, win32service.SERVICE_CHANGE_CONFIG)
        try:
            win32service.ChangeServiceConfig(svc, win32service.SERVICE_NO_CHANGE, start,
                                             win32service.SERVICE_NO_CHANGE, None, None, 0,
                                             None, None, None, None)
            if start == win32service.SERVICE_AUTO_START:
                win32service.ChangeServiceConfig2(svc, win32service.SERVICE_CONFIG_DELAYED_AUTO_START_INFO, delayed)
        finally:
            win32service.CloseServiceHandle(svc)
    finally:
        win32service.CloseServiceHandle(scm)


def test_lists_real_services_without_errors(tmp_path):
    mgr = ServiceManager(backup=BackupStore(tmp_path / "b.json"))
    services = mgr.get_manageable_services()
    print("\nServiços da whitelist neste Windows:",
          [(s.service_name, s.start_type.value, s.state.value, s.binary_path) for s in services])
    for s in services:
        assert not s.is_damaged, f"{s.service_name} detectado como danificado numa máquina limpa: {s.binary_path}"


@needs_admin
def test_disable_and_restore_real_service_keeps_binary(tmp_path):
    mgr = ServiceManager(backup=BackupStore(tmp_path / "b.json"))
    candidates = {s.service_name: s for s in mgr.get_manageable_services() if not s.is_disabled}
    name = next((n for n in ("MapsBroker", "XblGameSave", "XblAuthManager", "RetailDemo", "PrintNotify",
                             "DiagTrack", "Fax", "WMPNetworkSvc", "WSearch") if n in candidates), None)
    if name is None:
        pytest.skip("nenhum serviço da whitelist ativo neste Windows")

    before = _raw_config(name)
    print(f"\nTestando com {name}: {before}")
    try:
        result = mgr.disable_service(name)
        assert result.ok, result.message
        during = _raw_config(name)
        assert during["start"] == win32service.SERVICE_DISABLED
        assert during["binary"] == before["binary"], "o executável do serviço NÃO pode mudar"
        assert during["type"] == before["type"], "o tipo do serviço NÃO pode mudar"

        result = mgr.restore_service(name)
        assert result.ok, result.message
        after = _raw_config(name)
        assert after == before
    finally:
        current = _raw_config(name)
        if current["start"] != before["start"] or current["delayed"] != before["delayed"]:
            _raw_set_start(name, before["start"], before["delayed"])


TEST_SERVICE = "EunetxinhuCITest"
TEST_GROUP_IMAGE = r"%SystemRoot%\System32\svchost.exe -k EunetxinhuCITestGroup"


@pytest.fixture
def dummy_service():
    """Serviço descartável (nunca é iniciado) para reproduzir o bug da v1.0."""
    scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)

    def delete():
        try:
            svc = win32service.OpenService(scm, TEST_SERVICE, win32service.SERVICE_ALL_ACCESS)
        except win32service.error:
            return
        try:
            win32service.DeleteService(svc)
        finally:
            win32service.CloseServiceHandle(svc)

    delete()
    svc = win32service.CreateService(
        scm, TEST_SERVICE, "Eunetxinhu CI Test", win32service.SERVICE_ALL_ACCESS,
        SERVICE_WIN32_SHARE_PROCESS, win32service.SERVICE_DEMAND_START,
        win32service.SERVICE_ERROR_NORMAL, TEST_GROUP_IMAGE, None, 0, None, None, None)
    win32service.CloseServiceHandle(svc)
    try:
        yield TEST_SERVICE
    finally:
        delete()
        win32service.CloseServiceHandle(scm)


@needs_admin
def test_v1_bug_is_detected_and_repaired(dummy_service, tmp_path):
    whitelist = {dummy_service: ServiceSpec(ServiceRisk.SAFE, "teste", TEST_GROUP_IMAGE,
                                            SERVICE_WIN32_SHARE_PROCESS, StartType.MANUAL)}
    mgr = ServiceManager(backup=BackupStore(tmp_path / "b.json"), whitelist=whitelist)
    original = _raw_config(dummy_service)
    assert original["binary"].lower().endswith(r"svchost.exe -k eunetxinhucitestgroup")

    # Reproduz EXATAMENTE a chamada da v1.0.
    import win32serviceutil
    try:
        win32serviceutil.ChangeServiceConfig(None, dummy_service, startType=win32service.SERVICE_DISABLED)
    except Exception as exc:  # se o pywin32 não achar o pythonservice.exe, simula o estrago
        print(f"\nChamada da v1.0 falhou ({exc}); simulando o efeito dela")
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        svc = win32service.OpenService(scm, dummy_service, win32service.SERVICE_CHANGE_CONFIG)
        win32service.ChangeServiceConfig(svc, win32service.SERVICE_WIN32_OWN_PROCESS,
                                         win32service.SERVICE_DISABLED, win32service.SERVICE_NO_CHANGE,
                                         r'"C:\Python\pythonservice.exe"', None, 0, None, None, None, None)
        win32service.CloseServiceHandle(svc)
        win32service.CloseServiceHandle(scm)

    broken = _raw_config(dummy_service)
    print(f"\nDepois da chamada da v1.0: {broken}")
    assert "svchost.exe" not in broken["binary"].lower(), "a v1.0 trocava o executável do serviço"
    assert broken["type"] == win32service.SERVICE_WIN32_OWN_PROCESS

    (item,) = mgr.get_manageable_services()
    assert item.is_damaged
    assert not mgr.restore_service(dummy_service).ok  # reativar danificado é recusado

    result = mgr.repair_service(dummy_service)
    assert result.ok, result.message
    repaired = _raw_config(dummy_service)
    print(f"Depois do reparo: {repaired}")
    assert repaired["binary"].lower().endswith(r"\system32\svchost.exe -k eunetxinhucitestgroup")
    assert repaired["type"] == SERVICE_WIN32_SHARE_PROCESS
    assert repaired["start"] == win32service.SERVICE_DISABLED

    assert mgr.restore_service(dummy_service).ok
    assert _raw_config(dummy_service)["start"] == win32service.SERVICE_DEMAND_START

    # E o fluxo novo de desativar não estraga nada.
    assert mgr.disable_service(dummy_service).ok
    after_disable = _raw_config(dummy_service)
    assert after_disable["binary"] == repaired["binary"] and after_disable["type"] == repaired["type"]


# ================================================================ inicialização

def test_real_startup_disable_enable_roundtrip():
    name = "EunetxinhuCITest"
    command = r'"C:\Windows\System32\notepad.exe" /teste'
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)
    try:
        mgr = StartupManager()
        items = {i.name: i for i in mgr.get_startup_items()}
        print("\nItens de inicialização:", [(i.name, i.location, i.is_enabled) for i in items.values()])
        item = items[name]
        assert item.is_enabled and not item.target_missing

        assert mgr.disable_startup_item(item).ok
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY_PATH + r"\Run") as key:
            data, value_type = winreg.QueryValueEx(key, name)
        assert value_type == winreg.REG_BINARY and data[0] == 0x03 and len(data) == 12
        assert {i.name: i for i in mgr.get_startup_items()}[name].is_enabled is False
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
            assert winreg.QueryValueEx(key, name)[0] == command  # nada foi apagado

        assert mgr.enable_startup_item(item).ok
        assert {i.name: i for i in mgr.get_startup_items()}[name].is_enabled is True
    finally:
        for path in (RUN_KEY_PATH, APPROVED_KEY_PATH + r"\Run"):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


# ===================================================================== limpeza

def _old_clock():
    return time.time() + 3 * 86400


def test_ntfs_junction_is_never_followed(tmp_path):
    temp = tmp_path / "Temp"
    docs = tmp_path / "Documentos"
    temp.mkdir()
    docs.mkdir()
    (temp / "lixo.tmp").write_bytes(b"x")
    precious = docs / "importante.docx"
    precious.write_bytes(b"conteudo")
    link = temp / "junction_para_documentos"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(docs)], check=True, capture_output=True)
    assert (link / "importante.docx").exists()

    cat = CleanupCategory("t", "Temp", "", folders=(str(temp),))
    svc = TempCleanerService(categories=[cat], clock=_old_clock)
    assert svc.scan(["t"], skip_recent=False)["t"].files == 1
    (result,) = svc.clean(["t"], skip_recent=False)

    assert result.files_deleted == 1
    assert precious.read_bytes() == b"conteudo"
    assert link.exists()


def test_locked_and_readonly_files(tmp_path):
    temp = tmp_path / "Temp"
    temp.mkdir()
    readonly = temp / "somente_leitura.tmp"
    readonly.write_bytes(b"r")
    os.chmod(readonly, stat.S_IREAD)
    locked = temp / "em_uso.tmp"
    handle = open(locked, "wb")  # Python abre sem FILE_SHARE_DELETE: o Windows bloqueia a exclusão
    try:
        cat = CleanupCategory("t", "Temp", "", folders=(str(temp),))
        (result,) = TempCleanerService(categories=[cat], clock=_old_clock).clean(["t"], skip_recent=False)
        assert not readonly.exists()
        assert locked.exists()
        assert result.files_deleted == 1 and result.skipped_in_use == 1
    finally:
        handle.close()


def test_default_categories_on_real_windows():
    cats = {c.key: c for c in build_default_categories()}
    print("\nCategorias:", {k: c.folders for k, c in cats.items()})
    assert "user_temp" in cats
    assert "recycle_bin" in cats


def test_recycle_bin_query():
    info = RecycleBin().query()
    assert info is not None
    size, items = info
    assert size >= 0 and items >= 0


# ===================================================================== sistema

def test_real_system_info():
    info = get_system_info()
    print(f"\n{info}")
    assert "Windows" in info.os_name
    assert info.ram_total and info.ram_total > 512 * 1024 ** 2
    assert info.disk_total and info.disk_free is not None
    assert info.uptime_seconds and info.uptime_seconds > 0
