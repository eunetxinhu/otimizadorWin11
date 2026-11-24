import pytest

from models import ServiceState, StartType
from services.backup_store import BackupStore
from services.service_manager import (
    SERVICE_WIN32_OWN_PROCESS,
    SERVICE_WIN32_SHARE_PROCESS,
    WHITELIST,
    ServiceManager,
)
from tests.fakes import FakeService, FakeWin32Service

AUTO, MANUAL, DISABLED = 2, 3, 4
RUNNING, STOPPED = 4, 1
NO_CHANGE = FakeWin32Service.SERVICE_NO_CHANGE

WSEARCH_IMAGE = r"C:\WINDOWS\system32\SearchIndexer.exe /Embedding"
NETSVCS_IMAGE = r"C:\WINDOWS\system32\svchost.exe -k netsvcs -p"
ENV = {"SYSTEMROOT": r"C:\WINDOWS", "ProgramW6432": r"C:\Program Files"}


def wsearch(**kw):
    base = dict(name="WSearch", display_name="Windows Search", service_type=SERVICE_WIN32_OWN_PROCESS,
                start=AUTO, binary_path=WSEARCH_IMAGE, state=RUNNING, delayed=True)
    base.update(kw)
    return FakeService(**base)


def xbl(**kw):
    base = dict(name="XblAuthManager", display_name="Xbox Live Auth Manager",
                service_type=SERVICE_WIN32_SHARE_PROCESS, start=MANUAL,
                binary_path=NETSVCS_IMAGE, state=STOPPED)
    base.update(kw)
    return FakeService(**base)


@pytest.fixture
def backup(tmp_path):
    return BackupStore(tmp_path / "backup.json")


def manager(api, backup):
    return ServiceManager(api=api, backup=backup, env=ENV, sleep=lambda s: None, stop_timeout=2)


# ------------------------------------------------------------------ listagem

def test_lists_only_existing_whitelisted_services(make_scm, backup):
    api = make_scm(wsearch(), xbl(), FakeService("Spooler", "Spooler", 0x10, AUTO, "spoolsv.exe"))
    items = {s.service_name: s for s in manager(api, backup).get_manageable_services()}

    assert set(items) == {"WSearch", "XblAuthManager"}  # Spooler não está na whitelist
    assert items["WSearch"].start_type == StartType.AUTOMATIC_DELAYED
    assert items["WSearch"].state == ServiceState.RUNNING
    assert items["XblAuthManager"].start_type == StartType.MANUAL
    assert not any(s.is_damaged for s in items.values())
    assert api.open_handles == {}  # nenhum handle vazado


# ------------------------------------------------------- desativar (bug v1.0)

def test_disable_changes_only_the_start_type(make_scm, backup):
    api = make_scm(wsearch())
    result = manager(api, backup).disable_service("WSearch")

    svc = api.services["wsearch"]
    assert result.ok
    assert svc.start == DISABLED
    assert svc.binary_path == WSEARCH_IMAGE              # executável intacto
    assert svc.service_type == SERVICE_WIN32_OWN_PROCESS  # tipo intacto
    assert svc.state == STOPPED
    # A chamada à API não pode mexer em executável/tipo/conta (o bug da v1.0).
    (call,) = api.change_calls
    _, service_type, start, error_control, binary, group, _tag, deps, account, password, display = call
    assert service_type == NO_CHANGE and error_control == NO_CHANGE
    assert start == DISABLED
    assert binary is None and group is None and deps is None
    assert account is None and password is None and display is None
    assert api.open_handles == {}


def test_disable_saves_original_start_type_only_once(make_scm, backup):
    api = make_scm(wsearch())
    mgr = manager(api, backup)
    mgr.disable_service("WSearch")
    mgr.disable_service("WSearch")  # segunda vez não pode sobrescrever com "disabled"
    assert backup.get_service_original("WSearch") == "auto_delayed"


def test_disable_refuses_service_outside_whitelist(make_scm, backup):
    api = make_scm(FakeService("Spooler", "Spooler", 0x10, AUTO, "spoolsv.exe"))
    result = manager(api, backup).disable_service("Spooler")
    assert not result.ok
    assert api.change_calls == []


def test_disable_with_running_dependents_still_disables(make_scm, backup):
    api = make_scm(xbl(state=RUNNING, dependents_running=True))
    result = manager(api, backup).disable_service("XblAuthManager")
    assert result.ok
    assert "próxima reinicialização" in result.message
    assert api.services["xblauthmanager"].start == DISABLED


def test_disable_reports_access_denied(make_scm, backup):
    api = make_scm(xbl(deny_change=True))
    result = manager(api, backup).disable_service("XblAuthManager")
    assert not result.ok
    assert "administrador" in result.message
    assert api.open_handles == {}


def test_disable_missing_service(make_scm, backup):
    result = manager(make_scm(), backup).disable_service("Fax")
    assert not result.ok


# ------------------------------------------------------------------ reativar

def test_restore_uses_backup_including_delayed_start(make_scm, backup):
    api = make_scm(wsearch())
    mgr = manager(api, backup)
    mgr.disable_service("WSearch")

    result = mgr.restore_service("WSearch")
    svc = api.services["wsearch"]
    assert result.ok
    assert svc.start == AUTO and svc.delayed is True
    assert svc.state == RUNNING  # automático volta a rodar na hora
    assert backup.get_service_original("WSearch") is None
    assert svc.binary_path == WSEARCH_IMAGE


def test_restore_without_backup_uses_windows_default(make_scm, backup):
    api = make_scm(xbl(start=DISABLED))
    result = manager(api, backup).restore_service("XblAuthManager")
    assert result.ok
    assert api.services["xblauthmanager"].start == MANUAL  # padrão do Windows 11


def test_restore_when_already_enabled_is_noop(make_scm, backup):
    api = make_scm(xbl())
    result = manager(api, backup).restore_service("XblAuthManager")
    assert result.ok
    assert api.change_calls == []


# ------------------------------------------------- serviços danificados (v1.0)

V1_EXE = r'"C:\Users\fulano\Downloads\eunetxinhu-otimizacoes.exe"'
V1_PYTHONSERVICE = r'"C:\Python313\pythonservice.exe"'


@pytest.mark.parametrize("bad_binary", [V1_EXE, V1_PYTHONSERVICE])
def test_detects_service_damaged_by_v1(make_scm, backup, bad_binary):
    api = make_scm(xbl(start=DISABLED, binary_path=bad_binary, service_type=SERVICE_WIN32_OWN_PROCESS))
    (item,) = manager(api, backup).get_manageable_services()
    assert item.is_damaged


def test_repair_restores_default_image_and_type_keeping_start(make_scm, backup):
    api = make_scm(xbl(start=DISABLED, binary_path=V1_EXE, service_type=SERVICE_WIN32_OWN_PROCESS))
    mgr = manager(api, backup)

    result = mgr.repair_service("XblAuthManager")
    svc = api.services["xblauthmanager"]
    assert result.ok
    assert svc.binary_path == r"C:\WINDOWS\system32\svchost.exe -k netsvcs -p"
    assert svc.service_type == SERVICE_WIN32_SHARE_PROCESS
    assert svc.start == DISABLED  # reparo não liga o serviço sozinho
    assert not mgr.get_manageable_services()[0].is_damaged

    assert mgr.restore_service("XblAuthManager").ok
    assert svc.start == MANUAL


def test_repair_expands_program_files_with_quotes(make_scm, backup):
    api = make_scm(FakeService("WMPNetworkSvc", "WMP", SERVICE_WIN32_OWN_PROCESS, DISABLED, V1_EXE, STOPPED))
    assert manager(api, backup).repair_service("WMPNetworkSvc").ok
    assert api.services["wmpnetworksvc"].binary_path == r'"C:\Program Files\Windows Media Player\wmpnetwk.exe"'


def test_restore_refuses_damaged_service(make_scm, backup):
    api = make_scm(xbl(start=DISABLED, binary_path=V1_EXE))
    result = manager(api, backup).restore_service("XblAuthManager")
    assert not result.ok
    assert api.services["xblauthmanager"].start == DISABLED


def test_repair_on_healthy_service_does_nothing(make_scm, backup):
    api = make_scm(xbl())
    assert manager(api, backup).repair_service("XblAuthManager").ok
    assert api.change_calls == []


def test_repair_all_damaged(make_scm, backup):
    api = make_scm(
        xbl(start=DISABLED, binary_path=V1_EXE),
        wsearch(start=DISABLED, binary_path=V1_PYTHONSERVICE, delayed=False),
    )
    results = manager(api, backup).repair_all_damaged()
    assert set(results) == {"XblAuthManager", "WSearch"}
    assert all(r.ok for r in results.values())
    assert api.services["wsearch"].binary_path == r"C:\WINDOWS\system32\SearchIndexer.exe /Embedding"


def test_every_whitelist_entry_is_self_consistent():
    """O executável padrão de cada serviço tem que ser reconhecido como 'não danificado'."""
    for name, spec in WHITELIST.items():
        assert not ServiceManager._is_damaged(spec, spec.default_image), name
        assert spec.default_start in (StartType.MANUAL, StartType.AUTOMATIC, StartType.AUTOMATIC_DELAYED)
