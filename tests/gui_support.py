"""Monta o app com dependências falsas (registro, serviços, disco) para testes de interface."""

from __future__ import annotations

import os
import time

from models import ActionResult, StartupSource
from services.backup_store import BackupStore
from services.service_manager import SERVICE_WIN32_OWN_PROCESS, SERVICE_WIN32_SHARE_PROCESS, ServiceManager
from services.startup_manager import APPROVED_KEY_PATH, LEGACY_BACKUP_KEY_PATH, RUN_KEY_PATH, StartupManager, \
    disabled_value
from services.system_info import SystemInfo
from services.temp_cleaner import CleanupCategory, TempCleanerService
from tests.fakes import FakeService, FakeWin32Service, FakeWinreg

GB = 1024 ** 3


class RecordingDialogs:
    """Responde 'sim' a toda pergunta e guarda o que foi mostrado."""

    def __init__(self, answer: bool = True):
        self.answer = answer
        self.shown: list[tuple[str, str, str]] = []

    def info(self, title, message):
        self.shown.append(("info", title, message))

    def warning(self, title, message):
        self.shown.append(("warning", title, message))

    def error(self, title, message):
        self.shown.append(("error", title, message))

    def ask(self, title, message):
        self.shown.append(("ask", title, message))
        return self.answer


class FakeRecycleBin:
    def __init__(self):
        self.size, self.items = 350 * 1024 ** 2, 42

    def available(self):
        return True

    def query(self):
        return self.size, self.items

    def empty(self):
        self.size = self.items = 0
        return True


def build_fake_world(tmp_path):
    reg = FakeWinreg()
    hkcu, hklm = reg.HKEY_CURRENT_USER, reg.HKEY_LOCAL_MACHINE
    reg.set_value(hkcu, RUN_KEY_PATH, "Discord",
                  r'"C:\Users\u\AppData\Local\Discord\Update.exe" --processStart Discord.exe')
    reg.set_value(hkcu, RUN_KEY_PATH, "Spotify", r"C:\Users\u\AppData\Roaming\Spotify\Spotify.exe /minimized")
    reg.set_value(hkcu, RUN_KEY_PATH, "OneDrive", r'"C:\Program Files\Microsoft OneDrive\OneDrive.exe" /background')
    reg.set_value(hkcu, RUN_KEY_PATH, "ProgramaRemovido", r"C:\Apagado\velho.exe")
    reg.set_value(hklm, RUN_KEY_PATH, "SecurityHealth", r"%windir%\system32\SecurityHealthSystray.exe",
                  reg.REG_EXPAND_SZ)
    reg.set_value(hklm, RUN_KEY_PATH, "RtkAudUService",
                  r'"C:\Windows\System32\DriverStore\RtkAudUService64.exe" -background', wow32=True)
    reg.set_value(hkcu, APPROVED_KEY_PATH + r"\Run", "Spotify", disabled_value(time.time()), reg.REG_BINARY)
    reg.set_value(hkcu, LEGACY_BACKUP_KEY_PATH, "Steam", r'"C:\Program Files (x86)\Steam\steam.exe" -silent')

    existing = {r"C:\Users\u\AppData\Local\Discord\Update.exe", r"C:\Users\u\AppData\Roaming\Spotify\Spotify.exe",
                r"C:\Program Files\Microsoft OneDrive\OneDrive.exe",
                r"C:\Windows\System32\DriverStore\RtkAudUService64.exe"}
    user_folder = tmp_path / "Startup"
    user_folder.mkdir()
    (user_folder / "Enviar para o OneNote.lnk").write_bytes(b"x")
    startup = StartupManager(reg=reg, startup_folders={StartupSource.USER_FOLDER: str(user_folder)},
                             path_exists=lambda p: p in existing)

    netsvcs = r"C:\WINDOWS\system32\svchost.exe -k netsvcs -p"
    scm = FakeWin32Service([
        FakeService("Fax", "Fax", SERVICE_WIN32_OWN_PROCESS, 3, r"C:\WINDOWS\system32\fxssvc.exe", state=1),
        FakeService("WSearch", "Windows Search", SERVICE_WIN32_OWN_PROCESS, 2,
                    r"C:\WINDOWS\system32\SearchIndexer.exe /Embedding", delayed=True),
        FakeService("XblAuthManager", "Gerenciador de Autenticação do Xbox Live", SERVICE_WIN32_OWN_PROCESS, 4,
                    r'"C:\Users\u\Downloads\eunetxinhu-otimizacoes.exe"', state=1),
        FakeService("XblGameSave", "Jogo Salvo no Xbox Live", SERVICE_WIN32_SHARE_PROCESS, 3, netsvcs, state=1),
        FakeService("DiagTrack", "Experiências do Usuário Conectado e Telemetria", SERVICE_WIN32_OWN_PROCESS, 2,
                    r"C:\WINDOWS\system32\svchost.exe -k utcsvc -p"),
        FakeService("MapsBroker", "Gerenciador de Mapas Baixados", SERVICE_WIN32_SHARE_PROCESS, 4,
                    r"C:\WINDOWS\System32\svchost.exe -k NetworkService -p", state=1),
    ])
    services = ServiceManager(api=scm, backup=BackupStore(tmp_path / "backup.json"),
                              env={"SystemRoot": r"C:\WINDOWS"}, sleep=lambda s: None, stop_timeout=1)

    temp = tmp_path / "Temp"
    for i in range(12):
        path = temp / f"pasta{i % 3}" / f"arquivo{i}.tmp"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * (300_000 * (i + 1)))
        old = time.time() - 3 * 86400
        os.utime(path, (old, old))
    categories = [
        CleanupCategory("user_temp", "Temporários do usuário",
                        "Arquivos que programas e instaladores deixam para trás no %TEMP%.", folders=(str(temp),)),
        CleanupCategory("error_reports", "Relatórios de erro", "Relatórios de travamentos já enviados.",
                        folders=(str(tmp_path / "WER"),), use_age_filter=False),
        CleanupCategory("recycle_bin", "Lixeira", "Esvazia a Lixeira de todas as unidades. Não dá para desfazer.",
                        default_selected=False, use_age_filter=False, is_recycle_bin=True),
        CleanupCategory("prefetch", "Prefetch", "Arquivos que o Windows usa para abrir programas mais rápido.",
                        folders=(str(tmp_path / "Prefetch"),), default_selected=False,
                        warning="Não recomendado: apagar deixa o próximo boot e a abertura dos programas "
                                "MAIS LENTOS até o Windows reconstruir esses arquivos."),
    ]
    (tmp_path / "WER").mkdir()
    (tmp_path / "Prefetch").mkdir()
    # Como a pasta Temp foi criada agora, o ctime (Linux) é recente: o "relógio" do
    # limpador anda 2 dias para frente para os arquivos parecerem antigos.
    cleaner = TempCleanerService(categories=categories, recycle_bin=FakeRecycleBin(),
                                 clock=lambda: time.time() + 2 * 86400)

    info = SystemInfo(os_name="Windows 11 Pro 24H2 (build 26100)",
                      cpu_name="Intel(R) Core(TM) i3-7020U CPU @ 2.30GHz", cpu_count=4,
                      ram_total=4 * GB, ram_available=int(0.55 * GB), disk_drive="C:\\",
                      disk_total=120 * GB, disk_free=int(13.5 * GB), uptime_seconds=6 * 86400 + 5 * 3600)

    from gui.app import AppDependencies
    deps = AppDependencies(
        startup_manager=startup,
        temp_cleaner=cleaner,
        service_manager=services,
        get_system_info=lambda: info,
        create_restore_point=lambda: ActionResult(True, "Ponto de restauração criado."),
        open_folder=lambda path: None,
    )
    return deps, reg, scm


def pump(app, seconds: float = 0.5) -> None:
    """Processa eventos do Tk e a fila de tarefas em segundo plano até ficar ocioso."""
    deadline = time.time() + seconds
    while True:
        app.update()
        app.runner.drain()
        if time.time() >= deadline and not app.runner.busy:
            break
        if time.time() > deadline + 10:
            raise TimeoutError("tarefas em segundo plano não terminaram")
        time.sleep(0.02)
    app.update()
