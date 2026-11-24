from __future__ import annotations

import customtkinter as ctk

from gui.pages.base import BasePage
from gui.theme import (
    BG_CARD, BORDER_SUBTLE, RED, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY, YELLOW, YELLOW_HOVER,
    PrimaryButton, SecondaryButton, font, separator, truncate,
)


class StartupPage(BasePage):
    title = "Inicialização"
    subtitle = ("Programas que abrem junto com o Windows. Desligue a chave dos que você não usa todo dia. "
                "Funciona como o Gerenciador de Tarefas: nada é apagado e dá para religar quando quiser.")

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(2, weight=1)
        self._rows: list[tuple] = []  # (item, var)

        self._summary = ctk.CTkLabel(self, text="", font=font(13), text_color=TEXT_SECONDARY, anchor="w")
        self._summary.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self._scroll = ctk.CTkScrollableFrame(self, fg_color=BG_CARD, corner_radius=10,
                                              border_width=1, border_color=BORDER_SUBTLE)
        self._scroll.grid(row=2, column=0, sticky="nsew", pady=(0, 16))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew")
        self._refresh_btn = SecondaryButton(buttons, text="Atualizar lista", command=self.refresh)
        self._refresh_btn.pack(side="left")

    # ------------------------------------------------------------ dados

    def refresh(self) -> None:
        self._refresh_btn.configure(state="disabled")
        self._summary.configure(text="Lendo programas de inicialização…")
        mgr = self.deps.startup_manager
        self.runner.submit(lambda: (mgr.get_startup_items(), mgr.get_legacy_backups()),
                           self._render, self._on_error, name="inicializacao")

    def _on_error(self, exc) -> None:
        self._refresh_btn.configure(state="normal")
        self._summary.configure(text=f"Erro ao ler a inicialização: {exc}")

    def _render(self, data) -> None:
        items, legacy = data
        self._refresh_btn.configure(state="normal")
        for widget in self._scroll.winfo_children():
            widget.destroy()
        self._rows.clear()

        if legacy:
            self._section_title(f"Removidos pela versão anterior ({len(legacy)})",
                                "A versão 1.0 apagava os itens do registro. Restaure os que quiser de volta "
                                "(eles voltam para a inicialização deste usuário).")
            for i, entry in enumerate(sorted(legacy, key=lambda e: e.name.lower())):
                if i > 0:
                    separator(self._scroll).pack(fill="x", padx=14)
                self._legacy_row(entry)
            self._section_title("Programas de inicialização", "")

        if not items:
            ctk.CTkLabel(self._scroll, text="Nenhum item de inicialização encontrado.",
                         text_color=TEXT_SECONDARY).pack(pady=16)
        for i, item in enumerate(sorted(items, key=lambda it: it.name.lower())):
            if i > 0:
                separator(self._scroll).pack(fill="x", padx=14)
            self._item_row(item)

        self._update_summary()

    def _section_title(self, title: str, hint: str) -> None:
        ctk.CTkLabel(self._scroll, text=title, font=font(14, "bold"), text_color=YELLOW,
                     anchor="w").pack(anchor="w", padx=14, pady=(14, 0))
        if hint:
            ctk.CTkLabel(self._scroll, text=hint, font=font(12), text_color=TEXT_SECONDARY, anchor="w",
                         justify="left", wraplength=640).pack(anchor="w", padx=14, pady=(2, 4))

    def _item_row(self, item) -> None:
        row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)

        var = ctk.BooleanVar(value=item.is_enabled)
        switch = ctk.CTkSwitch(row, text="", variable=var, width=46, progress_color=YELLOW,
                               button_color=TEXT_PRIMARY, button_hover_color=YELLOW_HOVER)
        switch.configure(command=lambda it=item, v=var: self._toggle(it, v))
        switch.pack(side="left", padx=(0, 10))

        text_col = ctk.CTkFrame(row, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(text_col, text=item.name, font=font(14, "bold"), text_color=TEXT_PRIMARY,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(text_col, text=truncate(item.command, 95), font=font(12),
                     text_color=TEXT_SECONDARY, anchor="w").pack(anchor="w")

        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right")
        ctk.CTkLabel(right, text=item.location, font=font(11), text_color=TEXT_MUTED).pack(anchor="e")
        if item.target_missing:
            ctk.CTkLabel(right, text="arquivo não existe mais", font=font(11, "bold"),
                         text_color=RED).pack(anchor="e")

        self._rows.append((item, var))

    def _legacy_row(self, entry) -> None:
        row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)
        text_col = ctk.CTkFrame(row, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(text_col, text=entry.name, font=font(14, "bold"), text_color=TEXT_PRIMARY,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(text_col, text=truncate(entry.command, 80), font=font(12),
                     text_color=TEXT_SECONDARY, anchor="w").pack(anchor="w")
        SecondaryButton(row, text="Descartar", width=96,
                        command=lambda e=entry: self._legacy_action(e, restore=False)).pack(side="right")
        PrimaryButton(row, text="Restaurar", width=96,
                      command=lambda e=entry: self._legacy_action(e, restore=True)).pack(side="right", padx=8)

    # ------------------------------------------------------------ ações

    def _toggle(self, item, var) -> None:
        wanted = bool(var.get())
        result = self.deps.startup_manager.set_enabled(item, wanted)
        if not result.ok:
            var.set(not wanted)
            self.dialogs.error("Inicialização", f"Não foi possível alterar '{item.name}'.\n\n{result.message}")
        self._update_summary()

    def _legacy_action(self, entry, restore: bool) -> None:
        mgr = self.deps.startup_manager
        if restore:
            result = mgr.restore_legacy_backup(entry)
        else:
            if not self.dialogs.ask("Descartar backup",
                                    f"Descartar o backup de '{entry.name}'? Ele não poderá mais ser restaurado."):
                return
            result = mgr.discard_legacy_backup(entry)
        if not result.ok:
            self.dialogs.error("Inicialização", result.message)
        self.refresh()

    def _update_summary(self) -> None:
        total = len(self._rows)
        enabled = sum(1 for _, var in self._rows if var.get())
        self._summary.configure(text=f"{total} programa(s) · {enabled} ativo(s) · {total - enabled} desativado(s)")
