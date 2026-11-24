"""
Ponto de entrada do eunetxinhu otimizações.

Verifica se está rodando como administrador (necessário para mexer em
HKEY_LOCAL_MACHINE e na configuração de serviços) e, se não estiver, pede
elevação automaticamente antes de abrir a interface.

Uso:
    python main.py               abre o app
    python main.py --self-test   abre a janela escondida, carrega todas as telas
                                 (só leitura) e sai com código 0/1. Usado no CI
                                 para validar o .exe gerado pelo PyInstaller.
"""

from __future__ import annotations

import logging
import platform
import sys
import time

from app_info import APP_NAME, APP_VERSION, is_frozen, log_file, setup_logging

log = logging.getLogger("main")


class _ErrorCollector(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


class _SilentDialogs:
    """No autoteste nenhuma janela pode bloquear; erros mostrados viram falha."""

    def __init__(self):
        self.errors: list[str] = []

    def info(self, title, message):
        log.info("[autoteste] %s: %s", title, message)

    def warning(self, title, message):
        log.warning("[autoteste] %s: %s", title, message)

    def error(self, title, message):
        self.errors.append(f"{title}: {message}")

    def ask(self, title, message):
        return False


def self_test(timeout: float = 60.0) -> int:
    from gui.app import OtimizacoesApp

    collector = _ErrorCollector()
    logging.getLogger().addHandler(collector)
    dialogs = _SilentDialogs()
    app = OtimizacoesApp(dialogs=dialogs)
    app.withdraw()
    try:
        for key in list(app.pages):
            app.show_page(key)
            deadline = time.time() + timeout
            while True:
                app.update()
                app.runner.drain()
                if not app.runner.busy:
                    break
                if time.time() > deadline:
                    raise TimeoutError(f"a tela '{key}' não terminou de carregar")
                time.sleep(0.05)
            log.info("[autoteste] tela '%s' carregada", key)
    finally:
        app.destroy()
        logging.getLogger().removeHandler(collector)

    problems = dialogs.errors + [r.getMessage() for r in collector.records]
    if app.deps.service_manager is None:
        problems.append(f"serviços indisponíveis: {app.deps.service_manager_error}")
    for problem in problems:
        log.error("[autoteste] problema: %s", problem)
    log.info("[autoteste] %s", "OK" if not problems else f"{len(problems)} problema(s)")
    return 0 if not problems else 1


def run(argv: list[str]) -> int:
    if sys.platform != "win32":
        print("O eunetxinhu otimizações só funciona no Windows (usa Registro e Serviços do Windows).")
        return 1

    if "--self-test" in argv:
        return self_test()

    from elevation import is_admin, relaunch_as_admin

    if not is_admin():
        relaunch_as_admin()  # encerra o processo atual
        return 0

    # Import tardio: customtkinter/pywin32 só são carregados já com admin no Windows.
    from gui.app import OtimizacoesApp

    app = OtimizacoesApp()
    app.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    setup_logging()
    log.info("Iniciando %s %s (Python %s, %s, empacotado=%s)",
             APP_NAME, APP_VERSION, platform.python_version(), platform.platform(), is_frozen())
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception:
        # Sem isso, no .exe sem console a janela simplesmente não abriria e
        # ninguém saberia por quê.
        log.exception("Erro fatal ao executar o app")
        if sys.platform == "win32":
            from elevation import show_message
            show_message(APP_NAME, f"Ocorreu um erro inesperado e o app precisa fechar.\n\n"
                                   f"Detalhes foram salvos em:\n{log_file()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
