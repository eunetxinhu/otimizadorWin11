import json

import pytest

from services.backup_store import BackupStore
from services.cmdline import executable_name, executable_path, expand_windows_vars


@pytest.mark.parametrize("command,expected", [
    (r'"C:\Program Files\App\app.exe" --min', r"C:\Program Files\App\app.exe"),
    (r"C:\Program Files\App\app.exe --min", r"C:\Program Files\App\app.exe"),
    (r"C:\WINDOWS\system32\svchost.exe -k netsvcs -p", r"C:\WINDOWS\system32\svchost.exe"),
    (r"%windir%\system32\SecurityHealthSystray.exe", r"%windir%\system32\SecurityHealthSystray.exe"),
    ("rundll32.exe shell32.dll,Control_RunDLL", "rundll32.exe"),
    ('"C:\\sem fim.exe', "C:\\sem fim.exe"),
    ("ctfmon", "ctfmon"),
    ("", ""),
    ("   ", ""),
])
def test_executable_path(command, expected):
    assert executable_path(command) == expected


def test_executable_name_is_case_insensitive():
    assert executable_name(r'"C:\X\PythonService.EXE"') == "pythonservice.exe"


def test_expand_windows_vars_case_insensitive():
    assert expand_windows_vars(r"%systemroot%\x %Nope%", {"SystemRoot": r"C:\W"}) == r"C:\W\x %Nope%"


def test_backup_store_roundtrip(tmp_path):
    store = BackupStore(tmp_path / "sub" / "backup.json")
    assert store.get_service_original("X") is None
    store.save_service_original("X", "auto")
    store.save_service_original("X", "disabled")  # não sobrescreve
    assert BackupStore(store.path).get_service_original("X") == "auto"
    store.remove_service_original("X")
    assert store.get_service_original("X") is None


def test_backup_store_survives_corrupted_file(tmp_path):
    path = tmp_path / "backup.json"
    path.write_text("{ isso não é json", encoding="utf-8")
    store = BackupStore(path)
    assert store.get_service_original("X") is None
    store.save_service_original("X", "manual")
    assert json.loads(path.read_text(encoding="utf-8"))["services"]["X"]["start_type"] == "manual"
