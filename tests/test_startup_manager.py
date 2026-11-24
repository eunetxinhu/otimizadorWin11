import struct

import pytest

from models import LegacyStartupBackup, StartupSource
from services.startup_manager import (
    APPROVED_KEY_PATH,
    LEGACY_BACKUP_KEY_PATH,
    RUN_KEY_PATH,
    StartupManager,
    disabled_value,
    is_enabled_value,
)
from tests.fakes import FakeWinreg

HKCU = FakeWinreg.HKEY_CURRENT_USER
HKLM = FakeWinreg.HKEY_LOCAL_MACHINE
ENABLED = bytes([2] + [0] * 11)
NOW = 1_750_000_000.0


@pytest.fixture
def folders(tmp_path):
    user = tmp_path / "user_startup"
    common = tmp_path / "common_startup"
    user.mkdir()
    common.mkdir()
    (user / "OneNote.lnk").write_bytes(b"x")
    (user / "desktop.ini").write_text("[.ShellClassInfo]")
    (common / "Ferramenta.lnk").write_bytes(b"x")
    return {StartupSource.USER_FOLDER: str(user), StartupSource.COMMON_FOLDER: str(common)}


@pytest.fixture
def reg():
    r = FakeWinreg()
    r.set_value(HKCU, RUN_KEY_PATH, "Discord", r'"C:\Users\u\AppData\Local\Discord\Update.exe" --start')
    r.set_value(HKCU, RUN_KEY_PATH, "Antigo", r"C:\Apagado\antigo.exe /bg")
    r.set_value(HKLM, RUN_KEY_PATH, "SecurityHealth", r"%windir%\system32\SecurityHealthSystray.exe",
                FakeWinreg.REG_EXPAND_SZ)
    r.set_value(HKLM, RUN_KEY_PATH, "Driver32", r"C:\Program Files (x86)\Drv\tray.exe", wow32=True)
    # Já desativado pelo Gerenciador de Tarefas:
    r.set_value(HKCU, APPROVED_KEY_PATH + r"\Run", "Antigo", disabled_value(NOW), FakeWinreg.REG_BINARY)
    r.set_value(HKCU, APPROVED_KEY_PATH + r"\Run", "Discord", ENABLED, FakeWinreg.REG_BINARY)
    return r


def make(reg, folders, existing=()):
    return StartupManager(reg=reg, startup_folders=folders,
                          path_exists=lambda p: p in existing, clock=lambda: NOW)


def by_name(items):
    return {i.name: i for i in items}


def test_lists_all_sources_with_real_state(reg, folders):
    items = by_name(make(reg, folders).get_startup_items())

    assert set(items) == {"Discord", "Antigo", "SecurityHealth", "Driver32", "OneNote.lnk", "Ferramenta.lnk"}
    assert items["Discord"].source == StartupSource.HKCU_RUN and items["Discord"].is_enabled
    assert items["Antigo"].is_enabled is False
    assert items["SecurityHealth"].source == StartupSource.HKLM_RUN
    assert items["Driver32"].source == StartupSource.HKLM_RUN32  # WOW6432Node
    assert items["OneNote.lnk"].source == StartupSource.USER_FOLDER
    assert items["Ferramenta.lnk"].source == StartupSource.COMMON_FOLDER
    assert items["Ferramenta.lnk"].is_machine_wide


def test_flags_items_whose_executable_no_longer_exists(reg, folders):
    existing = {r"C:\Users\u\AppData\Local\Discord\Update.exe"}
    items = by_name(make(reg, folders, existing).get_startup_items())
    assert items["Antigo"].target_missing
    assert not items["Discord"].target_missing
    assert not items["SecurityHealth"].target_missing  # %windir% não resolvido -> não afirma nada


@pytest.mark.parametrize("source,hive,subkey", [
    ("Discord", HKCU, "Run"),
    ("SecurityHealth", HKLM, "Run"),
    ("Driver32", HKLM, "Run32"),
    ("OneNote.lnk", HKCU, "StartupFolder"),
    ("Ferramenta.lnk", HKLM, "StartupFolder"),
])
def test_disable_is_non_destructive_and_task_manager_compatible(reg, folders, source, hive, subkey):
    mgr = make(reg, folders)
    item = by_name(mgr.get_startup_items())[source]
    run_before = {k: dict(v) for k, v in reg.keys.items() if "startupapproved" not in k[1]}

    assert mgr.disable_startup_item(item).ok

    data, value_type = reg.get_value(hive, APPROVED_KEY_PATH + "\\" + subkey, source)
    assert value_type == FakeWinreg.REG_BINARY
    assert len(data) == 12 and data[0] == 0x03
    filetime = struct.unpack("<Q", data[4:])[0]
    assert abs(filetime / 1e7 - 11644473600 - NOW) < 1
    # Nada fora de StartupApproved foi alterado/apagado.
    assert {k: dict(v) for k, v in reg.keys.items() if "startupapproved" not in k[1]} == run_before
    assert by_name(mgr.get_startup_items())[source].is_enabled is False

    assert mgr.enable_startup_item(item).ok
    assert reg.get_value(hive, APPROVED_KEY_PATH + "\\" + subkey, source)[0] == ENABLED
    assert by_name(mgr.get_startup_items())[source].is_enabled is True


def test_disable_without_permission_reports_failure(reg, folders):
    reg.make_readonly(HKLM, APPROVED_KEY_PATH + r"\Run")
    mgr = make(reg, folders)
    item = by_name(mgr.get_startup_items())["SecurityHealth"]
    result = mgr.disable_startup_item(item)
    assert not result.ok
    assert item.is_enabled  # estado local não muda se falhou


@pytest.mark.parametrize("first_byte,enabled", [(0x02, True), (0x06, True), (0x03, False), (0x07, False)])
def test_approved_value_interpretation(first_byte, enabled):
    assert is_enabled_value(bytes([first_byte] + [0] * 11)) is enabled


def test_missing_or_garbage_approved_value_counts_as_enabled():
    assert is_enabled_value(None) and is_enabled_value(b"") and is_enabled_value("texto")


def test_missing_keys_are_fine(folders):
    assert make(FakeWinreg(), {}).get_startup_items() == []


# ------------------------------------------------------- backups da v1.0

def test_legacy_backup_restore(reg, folders):
    reg.set_value(HKCU, LEGACY_BACKUP_KEY_PATH, "Spotify", r"%APPDATA%\Spotify\Spotify.exe /minimized")
    reg.set_value(HKCU, LEGACY_BACKUP_KEY_PATH, "Discord", "duplicado")
    mgr = make(reg, folders)

    backups = {b.name: b for b in mgr.get_legacy_backups()}
    assert set(backups) == {"Spotify", "Discord"}

    assert mgr.restore_legacy_backup(backups["Spotify"]).ok
    data, value_type = reg.get_value(HKCU, RUN_KEY_PATH, "Spotify")
    assert data == r"%APPDATA%\Spotify\Spotify.exe /minimized"
    assert value_type == FakeWinreg.REG_EXPAND_SZ  # mantém as variáveis funcionando

    # Já existe no Run: não sobrescreve, só limpa o backup.
    result = mgr.restore_legacy_backup(backups["Discord"])
    assert result.ok and "já estava" in result.message
    assert reg.get_value(HKCU, RUN_KEY_PATH, "Discord")[0].startswith('"C:\\Users')
    assert mgr.get_legacy_backups() == []


def test_legacy_backup_discard(reg, folders):
    reg.set_value(HKCU, LEGACY_BACKUP_KEY_PATH, "Teams", "teams.exe")
    mgr = make(reg, folders)
    assert mgr.discard_legacy_backup(LegacyStartupBackup("Teams", "teams.exe")).ok
    assert mgr.get_legacy_backups() == []
    assert reg.get_value(HKCU, RUN_KEY_PATH, "Teams") is None
