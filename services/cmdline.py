"""
Utilitários para interpretar linhas de comando do Windows
(ex: 'C:\\Program Files\\App\\app.exe --minimized' ou '"%SystemRoot%\\x.exe" -k grupo').

Usa ntpath explicitamente para se comportar igual no Windows e nos testes
rodando em Linux.
"""

from __future__ import annotations

import ntpath
import re

_EXE_BOUNDARY = re.compile(r"\.(exe|com|bat|cmd|lnk)(?=\s|$)", re.IGNORECASE)


def executable_path(command: str) -> str:
    """
    Extrai o caminho do executável de uma linha de comando.

    - Com aspas: tudo entre as primeiras aspas.
    - Sem aspas: até o primeiro '.exe' (ou .com/.bat/.cmd/.lnk) seguido de espaço
      ou fim - assim 'C:\\Program Files\\x.exe -a' funciona mesmo com espaços.
    - Senão: o primeiro "pedaço" antes de um espaço.
    """
    cmd = (command or "").strip()
    if not cmd:
        return ""

    if cmd[0] == '"':
        end = cmd.find('"', 1)
        return cmd[1:end] if end != -1 else cmd[1:]

    match = _EXE_BOUNDARY.search(cmd)
    if match:
        return cmd[: match.end()]

    return cmd.split()[0]


def executable_name(command: str) -> str:
    """Só o nome do arquivo executável, em minúsculas (ex: 'svchost.exe')."""
    return ntpath.basename(executable_path(command)).lower()


def expand_windows_vars(text: str, env: dict[str, str]) -> str:
    """
    Expande variáveis no estilo %VAR% usando o dicionário dado (sem diferenciar
    maiúsculas/minúsculas, como o Windows). Variáveis desconhecidas ficam como estão.
    """
    lowered = {k.lower(): v for k, v in env.items()}

    def replace(match: re.Match) -> str:
        value = lowered.get(match.group(1).lower())
        return value if value is not None else match.group(0)

    return re.sub(r"%([^%]+)%", replace, text)
