"""
Utilitários para checar/exigir privilégio de administrador no Windows.
Necessário porque escrever em HKEY_LOCAL_MACHINE e mudar configuração de
serviços exige elevação.
"""

import ctypes
import os
import subprocess
import sys


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def relaunch_as_admin() -> None:
    """
    Relança o próprio script pedindo elevação (equivalente a clicar em
    'Executar como administrador'). Encerra o processo atual em seguida.
    """
    # Usa o caminho absoluto do script - se passarmos só "main.py" (relativo),
    # o processo elevado pode abrir em outra pasta de trabalho (ex: System32)
    # e não vai achar o arquivo nem os módulos gui/services.
    script_path = os.path.abspath(sys.argv[0])
    other_args = sys.argv[1:]

    params = subprocess.list2cmdline([script_path] + other_args)

    # Passamos a pasta atual explicitamente (lpDirectory) para garantir que o
    # processo elevado herde a mesma pasta de trabalho que o processo original.
    working_dir = os.getcwd()

    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, working_dir, 1
    )

    # ShellExecuteW retorna um valor <= 32 em caso de erro (ex: usuário cancelou o UAC).
    if result <= 32:
        print(f"Não foi possível elevar privilégios (código {result}). "
              "Se você cancelou a janela do UAC, rode o app de novo e clique em 'Sim'.")
        input("Pressione Enter para sair...")

    sys.exit(0)

