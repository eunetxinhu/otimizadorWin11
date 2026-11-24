"""
Cria um Ponto de Restauração do Sistema (via PowerShell Checkpoint-Computer),
para o usuário poder desfazer tudo pelo próprio Windows se algo der errado.
"""

from __future__ import annotations

import logging
import subprocess
import sys

from models import ActionResult

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000

# Descrição só com ASCII para não depender da codificação do console.
_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$w = $null
try {
    Checkpoint-Computer -Description 'eunetxinhu otimizacoes' -RestorePointType MODIFY_SETTINGS `
        -WarningVariable w -WarningAction SilentlyContinue
} catch {
    Write-Output ('ERRO:' + $_.Exception.Message)
    exit 1
}
if ($w) { Write-Output ('AVISO:' + $w[0]); exit 2 }
exit 0
"""


def create_restore_point(runner=subprocess.run, timeout: float = 300) -> ActionResult:
    if sys.platform != "win32" and runner is subprocess.run:
        return ActionResult(False, "Pontos de restauração só existem no Windows.")
    try:
        proc = runner(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", _SCRIPT],
            capture_output=True, text=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except FileNotFoundError:
        return ActionResult(False, "PowerShell não encontrado neste PC.")
    except subprocess.TimeoutExpired:
        return ActionResult(False, "O Windows demorou demais para criar o ponto de restauração.")

    output = (proc.stdout or "").strip()
    log.info("Checkpoint-Computer: código %s, saída %r, erro %r", proc.returncode, output, proc.stderr)

    if proc.returncode == 0:
        return ActionResult(True, "Ponto de restauração criado. Se algo der errado, use "
                                  "'Restauração do Sistema' do Windows para voltar a este ponto.")
    if proc.returncode == 2:
        # Normalmente: o Windows só permite 1 ponto a cada 24 h.
        return ActionResult(False, "O Windows não criou um novo ponto agora (ele permite só um a cada "
                                   "24 horas). Já existe um ponto recente que pode ser usado.")
    detail = output.removeprefix("ERRO:").strip() or (proc.stderr or "").strip()
    return ActionResult(False, "Não foi possível criar o ponto de restauração. Verifique se a "
                               "'Proteção do Sistema' está ativada para o disco C:.\n\n" + detail[:300])
