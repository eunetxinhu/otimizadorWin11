from __future__ import annotations

import customtkinter as ctk

from gui.theme import TEXT_PRIMARY, TEXT_SECONDARY, font


class BasePage(ctk.CTkFrame):
    """Página do app: cabeçalho + conteúdo. Subclasses montam o resto a partir da linha 1."""

    title = ""
    subtitle = ""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self._loaded_once = False

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        ctk.CTkLabel(header, text=self.title, font=font(22, "bold"),
                     text_color=TEXT_PRIMARY, anchor="w").pack(anchor="w")
        ctk.CTkLabel(header, text=self.subtitle, font=font(13), text_color=TEXT_SECONDARY,
                     anchor="w", wraplength=720, justify="left").pack(anchor="w", pady=(4, 0))

    def on_show(self) -> None:
        """Chamado quando a página aparece. Carrega os dados na primeira vez."""
        if not self._loaded_once:
            self._loaded_once = True
            self.refresh()

    def refresh(self) -> None:
        pass

    @property
    def deps(self):
        return self.app.deps

    @property
    def dialogs(self):
        return self.app.dialogs

    @property
    def runner(self):
        return self.app.runner
