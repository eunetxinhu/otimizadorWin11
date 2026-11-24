import subprocess
import sys

import pytest

import app_info
from elevation import build_relaunch_command
from services.restore_point import create_restore_point
from services.system_info import SystemInfo, build_recommendations, get_system_info

GB = 1024 ** 3


# ------------------------------------------------------------- elevação

def test_relaunch_frozen_exe_does_not_repeat_its_own_path():
    program, params = build_relaunch_command([r"C:\Apps\otimizador.exe", "--x"], r"C:\Apps\otimizador.exe", True)
    assert program == r"C:\Apps\otimizador.exe"
    assert params == "--x"


def test_relaunch_script_uses_pythonw_and_absolute_script(tmp_path, monkeypatch):
    (tmp_path / "python.exe").write_bytes(b"")
    (tmp_path / "pythonw.exe").write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    program, params = build_relaunch_command(["main.py", "a b"], str(tmp_path / "python.exe"), False)
    assert program == str(tmp_path / "pythonw.exe")
    assert params == subprocess.list2cmdline([str(tmp_path / "main.py"), "a b"])


def test_relaunch_script_without_pythonw(tmp_path):
    program, _ = build_relaunch_command(["main.py"], str(tmp_path / "python.exe"), False)
    assert program == str(tmp_path / "python.exe")


# ------------------------------------------------------------- main/log

@pytest.mark.skipif(sys.platform == "win32", reason="comportamento fora do Windows")
def test_main_refuses_non_windows(capsys):
    import main
    assert main.main([]) == 1
    assert "só funciona no Windows" in capsys.readouterr().out


def test_logging_goes_to_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("EUNETXINHU_DATA_DIR", str(tmp_path / "dados"))
    monkeypatch.setattr(app_info, "_logging_configured", False)
    import logging
    app_info.setup_logging()
    logging.getLogger("teste").warning("olá log")
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            handler.flush()
    assert "olá log" in app_info.log_file().read_text(encoding="utf-8")


def test_resource_path_points_to_project():
    import os
    assert os.path.exists(app_info.resource_path("app_icon.ico"))


# ------------------------------------------------------------- sistema

def test_system_info_runs_anywhere():
    info = get_system_info()
    assert info.os_name
    assert info.disk_total is None or info.disk_total > 0


def test_recommendations_cover_problems():
    info = SystemInfo(ram_total=4 * GB, ram_available=int(0.4 * GB), disk_total=100 * GB,
                      disk_free=5 * GB, uptime_seconds=10 * 86400)
    tips = build_recommendations(info, startup_enabled=15, damaged_services=2, legacy_backups=1)
    levels = [level for level, _ in tips]
    text = " ".join(t for _, t in tips)
    assert levels[0] == "danger" and "Reparar todos" in text
    assert "5%" in text and "90%" in text and "15 programas" in text and "10 dias" in text


def test_recommendations_all_good():
    info = SystemInfo(ram_total=16 * GB, ram_available=10 * GB, disk_total=500 * GB,
                      disk_free=300 * GB, uptime_seconds=3600)
    expected = [("ok", "Tudo certo por aqui. Nenhum problema encontrado.")]
    assert build_recommendations(info, startup_enabled=3) == expected


# ------------------------------------------------------- ponto de restauração

class FakeProc:
    def __init__(self, code, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


@pytest.mark.parametrize("code,out,ok,expected", [
    (0, "", True, "criado"),
    (2, "AVISO:A new system restore point cannot be created", False, "24 horas"),
    (1, "ERRO:System protection is disabled", False, "Proteção do Sistema"),
])
def test_restore_point_outcomes(code, out, ok, expected):
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        return FakeProc(code, out)

    result = create_restore_point(runner=runner)
    assert result.ok is ok and expected in result.message
    assert calls[0][0] == "powershell.exe" and "Checkpoint-Computer" in calls[0][-1]


def test_restore_point_timeout():
    def runner(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    assert not create_restore_point(runner=runner).ok


# ------------------------------------------------------------- formatação

def test_formatters():
    pytest.importorskip("customtkinter")
    from gui.theme import format_bytes, format_duration, truncate
    assert format_bytes(512) == "512 B"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(5 * GB) == "5.0 GB"
    assert format_bytes(None) == "—"
    assert format_duration(90) == "1 min"
    assert format_duration(2 * 86400 + 3 * 3600) == "2 d 3 h"
    assert truncate("abcdef", 4) == "abc…"
