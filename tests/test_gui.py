"""
Testes de interface: abre a janela de verdade (com dependências falsas) e
executa os fluxos pelos mesmos métodos que os botões chamam.
Pulado automaticamente se não houver Tk/customtkinter ou tela disponível.
"""

import os
import sys

import pytest

pytest.importorskip("tkinter")
pytest.importorskip("customtkinter")

if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    pytest.skip("sem DISPLAY (use xvfb-run)", allow_module_level=True)

from services.startup_manager import APPROVED_KEY_PATH, RUN_KEY_PATH  # noqa: E402
from tests.gui_support import RecordingDialogs, build_fake_world, pump  # noqa: E402


@pytest.fixture
def world(tmp_path):
    from gui.app import OtimizacoesApp

    deps, reg, scm = build_fake_world(tmp_path)
    dialogs = RecordingDialogs()
    app = OtimizacoesApp(deps=deps, dialogs=dialogs)
    pump(app)
    yield app, dialogs, reg, scm, tmp_path
    app.destroy()


def test_overview_flags_damaged_services(world):
    app, dialogs, *_ = world
    assert "services" in app._nav_alerts
    app.pages["overview"].create_restore_point()
    pump(app)
    assert ("info", "Ponto de restauração", "Ponto de restauração criado.") in dialogs.shown


def test_services_repair_disable_and_restore(world):
    app, dialogs, _reg, scm, _ = world
    app.show_page("services")
    pump(app)
    page = app.pages["services"]
    assert page._banner.winfo_ismapped()

    page.repair_all()
    pump(app)
    assert scm.services["xblauthmanager"].binary_path == r"C:\WINDOWS\system32\svchost.exe -k netsvcs -p"
    assert "services" not in app._nav_alerts
    assert not page._banner.winfo_ismapped()

    fax = next(s for s in page._services if s.service_name == "Fax")
    page._run_action("disable", fax)
    pump(app)
    assert scm.services["fax"].start == 4
    assert dialogs.shown[-1][0] == "info"

    fax = next(s for s in page._services if s.service_name == "Fax")
    assert fax.is_disabled and fax.has_backup
    page._run_action("restore", fax)
    pump(app)
    assert scm.services["fax"].start == 3

    # Nenhuma chamada da API mexeu no executável fora do reparo.
    assert all(call[4] is None for call in scm.change_calls if call[0] != "XblAuthManager")
    assert scm.open_handles == {}


def test_disable_all_safe_skips_caution_and_damaged(world):
    app, dialogs, _reg, scm, _ = world
    app.show_page("services")
    pump(app)
    app.pages["services"].disable_all_safe()
    pump(app)
    assert scm.services["fax"].start == 4
    assert scm.services["xblgamesave"].start == 4
    assert scm.services["wsearch"].start == 2            # "Cautela": não entra no lote
    assert scm.services["xblauthmanager"].binary_path.startswith('"C:\\Users')  # danificado: intocado


def test_startup_toggle_and_legacy_restore(world):
    app, dialogs, reg, *_ = world
    app.show_page("startup")
    pump(app)
    page = app.pages["startup"]

    item, var = next((i, v) for i, v in page._rows if i.name == "Discord")
    var.set(False)
    page._toggle(item, var)
    data, _ = reg.get_value(reg.HKEY_CURRENT_USER, APPROVED_KEY_PATH + r"\Run", "Discord")
    assert data[0] == 0x03
    assert reg.get_value(reg.HKEY_CURRENT_USER, RUN_KEY_PATH, "Discord") is not None  # nada apagado
    assert "2 desativado" in page._summary.cget("text")

    legacy = page.deps.startup_manager.get_legacy_backups()[0]
    page._legacy_action(legacy, restore=True)
    pump(app)
    assert reg.get_value(reg.HKEY_CURRENT_USER, RUN_KEY_PATH, "Steam") is not None
    assert page.deps.startup_manager.get_legacy_backups() == []


def test_startup_toggle_failure_reverts_switch(world):
    app, dialogs, reg, *_ = world
    app.show_page("startup")
    pump(app)
    page = app.pages["startup"]
    reg.make_readonly(reg.HKEY_LOCAL_MACHINE, APPROVED_KEY_PATH + r"\Run")

    item, var = next((i, v) for i, v in page._rows if i.name == "SecurityHealth")
    var.set(False)
    page._toggle(item, var)
    assert var.get() is True
    assert dialogs.shown[-1][0] == "error"


def test_cleanup_analyze_and_clean(world):
    app, dialogs, _reg, _scm, tmp_path = world
    app.show_page("cleanup")
    pump(app)
    page = app.pages["cleanup"]
    assert page._size_labels["user_temp"].cget("text") == "22.3 MB"

    page.clean()
    pump(app)
    assert dialogs.shown[-1][0] == "ask"
    assert not any((tmp_path / "Temp").rglob("*.tmp"))
    assert "concluída: 12 arquivo(s)" in page._status.cget("text")
    assert page._analyze_btn.cget("state") == "normal"
