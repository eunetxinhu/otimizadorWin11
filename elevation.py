"""
Utilitários para checar/exigir privilégio de administrador no Windows e para
mostrar mensagens nativas (que funcionam até no .exe sem console).
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys

log = logging.getLogger(__name__)

MB_ICONERROR = 0x10
MB_ICONWARNING = 0x30
MB_ICONINFORMATION = 0x40


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def show_message(title: str, text: str, icon: int = MB_ICONERROR) -> None:
    """
    Caixa de mensagem nativa do Windows. Diferente de print()/input(), funciona
    no .exe gerado com --windowed (onde não existe console).
    """
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, icon)
    except Exception:
        print(f"{title}\n\n{text}", file=sys.stderr if sys.stderr else sys.stdout)


def build_relaunch_command(argv: list[str], executable: str, frozen: bool) -> tuple[str, str]:
    """
    Monta (programa, parâmetros) para relançar o app elevado.

    - .exe do PyInstaller: o próprio .exe, só com os argumentos extras
      (antes, o caminho do .exe era passado de novo como argumento).
    - Rodando o .py: pythonw.exe (sem janela de console extra) + caminho absoluto
      do script - um caminho relativo quebraria, pois o processo elevado pode
      começar em outra pasta (ex: System32).
    """
    if frozen:
        return executable, subprocess.list2cmdline(argv[1:])

    program = executable
    folder, name = os.path.split(executable)
    if name.lower() == "python.exe":
        pythonw = os.path.join(folder, "pythonw.exe")
        if os.path.exists(pythonw):
            program = pythonw
    return program, subprocess.list2cmdline([os.path.abspath(argv[0])] + argv[1:])


def relaunch_as_admin() -> None:
    """
    Relança o app pedindo elevação (equivalente a 'Executar como administrador')
    e encerra o processo atual.
    """
    program, params = build_relaunch_command(sys.argv, sys.executable, bool(getattr(sys, "frozen", False)))
    shell_execute = ctypes.windll.shell32.ShellExecuteW
    shell_execute.restype = ctypes.c_void_p  # HINSTANCE (evita truncar o valor em 64 bits)
    result = shell_execute(None, "runas", program, params, os.getcwd(), 1)
    code = int(result or 0)

    # ShellExecuteW retorna um valor <= 32 em caso de erro (5 = usuário recusou o UAC).
    if code <= 32:
        log.warning("Elevação recusada/falhou (código %s)", code)
        show_message(
            "eunetxinhu otimizações",
            "O app precisa de permissão de administrador para alterar a inicialização "
            "e os serviços do Windows.\n\nAbra de novo e clique em 'Sim' na janela do "
            f"Controle de Conta de Usuário.\n\n(código {code})",
            MB_ICONWARNING,
        )
        sys.exit(1)
    sys.exit(0)
