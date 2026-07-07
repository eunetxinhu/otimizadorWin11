"""
Ponto de entrada do eunetxinhu otimizações.

Verifica se está rodando como administrador (necessário para mexer em
HKEY_LOCAL_MACHINE e configuração de serviços) e, se não estiver, pede
elevação automaticamente antes de abrir a interface.
"""

import sys
import traceback

from elevation import is_admin, relaunch_as_admin


def run():
    if sys.platform != "win32":
        print("O eunetxinhu otimizações só funciona no Windows (usa Registro e Serviços do Windows).")
        sys.exit(1)

    if not is_admin():
        relaunch_as_admin()
        return  # relaunch_as_admin() já encerra o processo atual

    # Import tardio: customtkinter/pywin32 só existem no Windows, então importamos
    # depois de já termos garantido que estamos no Windows e com admin.
    from gui.app import OtimizacoesApp

    app = OtimizacoesApp()
    app.mainloop()


def main():
    # Envolve tudo em try/except para que, se algo der errado, o erro fique
    # visível na tela em vez da janela simplesmente piscar e fechar.
    try:
        run()
    except Exception:
        print("Ocorreu um erro ao iniciar o app:\n")
        traceback.print_exc()
        input("\nPressione Enter para sair...")
        sys.exit(1)


if __name__ == "__main__":
    main()

