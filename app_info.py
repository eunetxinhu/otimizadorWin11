"""
Informações gerais do app (nome, versão), caminhos de dados/recursos e log.

Mantido sem dependências de Windows para poder ser importado (e testado)
em qualquer sistema.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "eunetxinhu otimizações"
APP_VERSION = "2.0.0"
APP_ID = "EunetxinhuOtimizacoes"

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_logging_configured = False


def data_dir() -> Path:
    """
    Pasta onde o app guarda backups e logs:
    %LOCALAPPDATA%\\EunetxinhuOtimizacoes (ou ~/.eunetxinhu-otimizacoes fora do Windows).
    """
    override = os.environ.get("EUNETXINHU_DATA_DIR")
    if override:
        base = Path(override)
    elif os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"]) / APP_ID
    else:
        base = Path.home() / ".eunetxinhu-otimizacoes"
    base.mkdir(parents=True, exist_ok=True)
    return base


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file() -> Path:
    return log_dir() / "app.log"


def resource_path(relative: str) -> str:
    """
    Caminho de um arquivo empacotado junto com o app (ex: o ícone).
    Funciona tanto rodando o .py quanto no .exe do PyInstaller (que extrai
    os arquivos em sys._MEIPASS).
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def is_frozen() -> bool:
    """True quando rodando como .exe gerado pelo PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configura log em arquivo (com rotação) e, se houver console, também no stderr.
    No .exe sem console (--windowed) sys.stderr é None, então o arquivo é a
    única saída - é ele que o usuário manda quando algo dá errado.
    """
    global _logging_configured
    if _logging_configured:
        return

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT)

    try:
        file_handler = RotatingFileHandler(
            log_file(), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        pass  # sem log em arquivo não é motivo para o app não abrir

    if sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    _logging_configured = True
