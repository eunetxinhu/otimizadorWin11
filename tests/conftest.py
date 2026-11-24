import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.fakes import FakeService, FakeWin32Service, FakeWinreg  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Nenhum teste escreve backup/log na pasta real do usuário."""
    monkeypatch.setenv("EUNETXINHU_DATA_DIR", str(tmp_path / "appdata"))


@pytest.fixture(autouse=True)
def _isolated_logging():
    """Handlers instalados por setup_logging() num teste não vazam para os próximos."""
    import logging

    import app_info

    root = logging.getLogger()
    before = list(root.handlers)
    configured = app_info._logging_configured
    yield
    for handler in root.handlers[:]:
        if handler not in before:
            root.removeHandler(handler)
            handler.close()
    app_info._logging_configured = configured


@pytest.fixture
def fake_reg():
    return FakeWinreg()


@pytest.fixture
def make_scm():
    def factory(*services: FakeService) -> FakeWin32Service:
        return FakeWin32Service(list(services))
    return factory
