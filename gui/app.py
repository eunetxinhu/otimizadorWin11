"""
Janela principal do "eunetxinhu otimizações" (customtkinter).
Design minimalista: navegação lateral + conteúdo, paleta preto/amarelo.

As dependências (managers, leitura do sistema, diálogos) são injetáveis:
o app real usa AppDependencies.default(); os testes passam versões falsas.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from tkinter import messagebox
from typing import Any
from collections.abc import Callable

import customtkinter as ctk

from app_info import APP_NAME, APP_VERSION, log_dir, resource_path
from gui.background import BackgroundRunner
from gui.pages.cleanup import CleanupPage
from gui.pages.overview import OverviewPage
from gui.pages.services import ServicesPage
from gui.pages.startup import StartupPage
from gui.theme import (
    BG_CARD, BG_MAIN, BG_SIDEBAR, ON_YELLOW, RED, TEXT_MUTED, TEXT_SECONDARY, YELLOW, font,
)

log = logging.getLogger(__name__)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")  # sobrescrito pelas cores do gui/theme.py

NAV_ITEMS = [
    ("overview", "Visão geral", OverviewPage),
    ("startup", "Inicialização", StartupPage),
    ("cleanup", "Limpeza", CleanupPage),
    ("services", "Serviços", ServicesPage),
]


def _open_folder(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]


@dataclass
class AppDependencies:
    startup_manager: Any
    temp_cleaner: Any
    service_manager: Any               # None se o pywin32 não carregar
    get_system_info: Callable[[], Any]
    create_restore_point: Callable[[], Any]
    open_folder: Callable[[str], None] = _open_folder
    service_manager_error: str | None = None
    extra: dict = field(default_factory=dict)

    @classmethod
    def default(cls) -> AppDependencies:
        from services.restore_point import create_restore_point
        from services.startup_manager import StartupManager
        from services.system_info import get_system_info
        from services.temp_cleaner import TempCleanerService

        service_manager, error = None, None
        try:
            from services.service_manager import ServiceManager
            service_manager = ServiceManager()
        except Exception as exc:  # pywin32 ausente/quebrado não pode impedir o app de abrir
            log.exception("Gerenciador de serviços indisponível")
            error = str(exc)

        return cls(
            startup_manager=StartupManager(),
            temp_cleaner=TempCleanerService(),
            service_manager=service_manager,
            get_system_info=get_system_info,
            create_restore_point=create_restore_point,
            service_manager_error=error,
        )


class MessageBoxDialogs:
    """Diálogos nativos (bloqueantes) do Tk."""

    def __init__(self, root):
        self._root = root

    def info(self, title: str, message: str) -> None:
        messagebox.showinfo(title, message, parent=self._root)

    def warning(self, title: str, message: str) -> None:
        messagebox.showwarning(title, message, parent=self._root)

    def error(self, title: str, message: str) -> None:
        messagebox.showerror(title, message, parent=self._root)

    def ask(self, title: str, message: str) -> bool:
        return bool(messagebox.askyesno(title, message, parent=self._root))


class OtimizacoesApp(ctk.CTk):

    def __init__(self, deps: AppDependencies | None = None, dialogs=None, start_page: str = "overview"):
        super().__init__()

        self.title(APP_NAME)
        self.geometry("1120x720")
        self.minsize(980, 640)
        self.configure(fg_color=BG_MAIN)
        self._set_icon()

        self.deps = deps or AppDependencies.default()
        self.service_manager_error = self.deps.service_manager_error
        self.dialogs = dialogs or MessageBoxDialogs(self)
        self.runner = BackgroundRunner(self)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._nav_alerts: set[str] = set()
        self._current: str | None = None
        self._build_sidebar()

        self.content = ctk.CTkFrame(self, fg_color=BG_MAIN)
        self.content.grid(row=0, column=1, sticky="nsew", padx=32, pady=28)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.pages = {key: page_cls(self.content, self) for key, _label, page_cls in NAV_ITEMS}
        self.show_page(start_page)

    # ------------------------------------------------------------ janela

    def _set_icon(self) -> None:
        icon = resource_path("app_icon.ico")
        if sys.platform == "win32" and os.path.exists(icon):
            try:
                # Chamar iconbitmap antes do CTk impede ele de trocar pelo ícone padrão dele.
                self.iconbitmap(icon)
            except Exception:
                log.warning("Não foi possível aplicar o ícone da janela")

    def destroy(self) -> None:
        if hasattr(self, "runner"):
            self.runner.stop()
        # Cancela callbacks "after" pendentes (do customtkinter, por exemplo) para o
        # Tcl não reclamar de "invalid command name" depois que a janela some.
        try:
            for after_id in self.tk.splitlist(self.tk.call("after", "info")):
                self.after_cancel(after_id)
        except Exception:
            pass
        super().destroy()

    # ------------------------------------------------------------ navegação

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, fg_color=BG_SIDEBAR, corner_radius=0, width=220)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=24, pady=(32, 36))
        ctk.CTkLabel(brand, text="eunetxinhu", font=font(20, "bold"), text_color=YELLOW,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(brand, text="otimizações", font=font(13), text_color=TEXT_SECONDARY,
                     anchor="w").pack(anchor="w")

        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.pack(fill="x", padx=12)
        for key, label, _cls in NAV_ITEMS:
            btn = ctk.CTkButton(nav, text=label, anchor="w", fg_color="transparent", hover_color=BG_CARD,
                                text_color=TEXT_SECONDARY, corner_radius=8, height=40, font=font(14),
                                command=lambda k=key: self.show_page(k))
            btn.pack(fill="x", pady=2)
            self._nav_buttons[key] = btn

        ctk.CTkLabel(sidebar, text=f"v{APP_VERSION}", text_color=TEXT_MUTED,
                     font=font(11)).pack(side="bottom", pady=(4, 20))
        ctk.CTkButton(sidebar, text="Abrir pasta de logs", fg_color="transparent", hover_color=BG_CARD,
                      text_color=TEXT_MUTED, font=font(12), height=28,
                      command=lambda: self.deps.open_folder(str(log_dir()))).pack(side="bottom", padx=12)

    def show_page(self, key: str) -> None:
        if key not in self.pages:
            key = "overview"
        for page in self.pages.values():
            page.grid_remove()
        self.pages[key].grid(row=0, column=0, sticky="nsew")
        self._current = key
        self._paint_nav()
        self.pages[key].on_show()

    def set_nav_alert(self, key: str, alert: bool) -> None:
        """Marca um item do menu (ex: serviços danificados que precisam de reparo)."""
        if alert:
            self._nav_alerts.add(key)
        else:
            self._nav_alerts.discard(key)
        self._paint_nav()

    def _paint_nav(self) -> None:
        labels = {key: label for key, label, _cls in NAV_ITEMS}
        for key, btn in self._nav_buttons.items():
            text = labels[key] + ("  ●" if key in self._nav_alerts else "")
            if key == self._current:
                btn.configure(text=text, fg_color=YELLOW, hover_color=YELLOW, text_color=ON_YELLOW,
                              font=font(14, "bold"))
            else:
                color = RED if key in self._nav_alerts else TEXT_SECONDARY
                btn.configure(text=text, fg_color="transparent", hover_color=BG_CARD,
                              text_color=color, font=font(14))
