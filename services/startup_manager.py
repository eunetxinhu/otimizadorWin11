"""
Gerencia programas de inicialização automática do Windows,
lendo/escrevendo nas chaves de registro "Run" via winreg (biblioteca padrão).
"""

import winreg
from models import StartupItem

RUN_KEY_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
BACKUP_KEY_PATH = r"SOFTWARE\EunetxinhuOtimizacoes\StartupBackup"


class StartupManager:

    def get_startup_items(self) -> list[StartupItem]:
        """Lista todos os itens de inicialização encontrados em HKCU e HKLM."""
        items: list[StartupItem] = []
        items.extend(self._read_run_key(winreg.HKEY_CURRENT_USER, is_machine_wide=False))
        items.extend(self._read_run_key(winreg.HKEY_LOCAL_MACHINE, is_machine_wide=True))
        return items

    def _read_run_key(self, hive, is_machine_wide: bool) -> list[StartupItem]:
        result: list[StartupItem] = []
        try:
            with winreg.OpenKey(hive, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
                index = 0
                while True:
                    try:
                        name, command, _ = winreg.EnumValue(key, index)
                        result.append(StartupItem(
                            name=name,
                            command=str(command),
                            location=r"HKLM\...\Run" if is_machine_wide else r"HKCU\...\Run",
                            is_machine_wide=is_machine_wide,
                            is_enabled=True,
                        ))
                        index += 1
                    except OSError:
                        # EnumValue lança OSError quando o índice passa do último valor -
                        # é assim que winreg sinaliza "acabou a lista", não é um erro real.
                        break
        except FileNotFoundError:
            # A chave pode não existir em alguns sistemas - sem problema, ignora essa fonte.
            pass
        except PermissionError:
            # Sem permissão de leitura (raro, mas possível sem admin em HKLM).
            pass
        return result

    def disable_startup_item(self, item: StartupItem) -> bool:
        """Remove o item da chave Run, mas faz backup do valor antes."""
        hive = winreg.HKEY_LOCAL_MACHINE if item.is_machine_wide else winreg.HKEY_CURRENT_USER
        try:
            self._backup_item(item)
            with winreg.OpenKey(hive, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, item.name)
            return True
        except PermissionError:
            # Provavelmente precisa rodar como administrador (caso de HKLM).
            return False
        except FileNotFoundError:
            # Já não existe mais - considera sucesso.
            return True
        except OSError:
            return False

    def restore_startup_item(self, item: StartupItem) -> bool:
        """Restaura um item previamente desativado, devolvendo-o à chave Run."""
        hive = winreg.HKEY_LOCAL_MACHINE if item.is_machine_wide else winreg.HKEY_CURRENT_USER
        try:
            with winreg.CreateKey(hive, RUN_KEY_PATH) as key:
                winreg.SetValueEx(key, item.name, 0, winreg.REG_SZ, item.command)
            return True
        except OSError:
            return False

    def _backup_item(self, item: StartupItem) -> None:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, BACKUP_KEY_PATH) as key:
            winreg.SetValueEx(key, item.name, 0, winreg.REG_SZ, item.command)
