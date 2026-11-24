from __future__ import annotations

import logging

import customtkinter as ctk

from gui.pages.base import BasePage
from gui.theme import (
    BORDER_SUBTLE, LEVEL_COLORS, TEXT_PRIMARY, TEXT_SECONDARY, YELLOW, PrimaryButton,
    SecondaryButton, card, font, format_bytes, format_duration, truncate,
)
from services.system_info import build_recommendations

log = logging.getLogger(__name__)


class OverviewPage(BasePage):
    title = "Visão geral"
    subtitle = ("Um resumo do seu PC e do que pode ser melhorado. "
                "Antes de mudanças grandes, crie um ponto de restauração.")

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(2, weight=1)

        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        for col in range(4):
            stats.grid_columnconfigure(col, weight=1, uniform="stats")

        self._cards = {}
        for col, (key, label) in enumerate([("os", "Sistema"), ("cpu", "Processador"),
                                            ("ram", "Memória RAM"), ("disk", "Disco do sistema")]):
            self._cards[key] = self._stat_card(stats, col, label, with_bar=key in ("ram", "disk"))

        tips_card = card(self)
        tips_card.grid(row=2, column=0, sticky="nsew", pady=(0, 16))
        ctk.CTkLabel(tips_card, text="Recomendações", font=font(15, "bold"),
                     text_color=TEXT_PRIMARY, anchor="w").pack(anchor="w", padx=18, pady=(16, 8))
        self._tips_box = ctk.CTkFrame(tips_card, fg_color="transparent")
        self._tips_box.pack(fill="both", expand=True, padx=18, pady=(0, 14))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew")
        self._restore_btn = PrimaryButton(buttons, text="Criar ponto de restauração",
                                          command=self.create_restore_point)
        self._restore_btn.pack(side="left", padx=(0, 10))
        self._refresh_btn = SecondaryButton(buttons, text="Atualizar", width=110, command=self.refresh)
        self._refresh_btn.pack(side="left", padx=(0, 16))
        self._status = ctk.CTkLabel(buttons, text="", font=font(12), text_color=TEXT_SECONDARY)
        self._status.pack(side="left")

    def _stat_card(self, parent, col, label, with_bar):
        frame = card(parent)
        frame.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0 if col == 3 else 6))
        ctk.CTkLabel(frame, text=label, font=font(12), text_color=TEXT_SECONDARY,
                     anchor="w").pack(anchor="w", padx=16, pady=(14, 2))
        value = ctk.CTkLabel(frame, text="…", font=font(17, "bold"), text_color=TEXT_PRIMARY,
                             anchor="w", justify="left", wraplength=190)
        value.pack(anchor="w", padx=16)
        detail = ctk.CTkLabel(frame, text="", font=font(12), text_color=TEXT_SECONDARY,
                              anchor="w", justify="left", wraplength=190)
        detail.pack(anchor="w", padx=16, pady=(2, 0))
        bar = None
        if with_bar:
            bar = ctk.CTkProgressBar(frame, height=6, progress_color=YELLOW, fg_color=BORDER_SUBTLE)
            bar.set(0)
            bar.pack(fill="x", padx=16, pady=(10, 0))
        ctk.CTkFrame(frame, fg_color="transparent", height=12).pack()
        return value, detail, bar

    # ------------------------------------------------------------ dados

    def refresh(self) -> None:
        self._refresh_btn.configure(state="disabled")
        self._status.configure(text="Lendo informações do PC…")
        self.runner.submit(self._collect, self._show, self._on_error, name="visao-geral")

    def _collect(self):
        deps = self.deps
        info = deps.get_system_info()

        def safe(fn, default=None):
            try:
                return fn()
            except Exception:
                log.exception("Falha ao coletar dado da visão geral")
                return default

        startup_enabled = safe(lambda: sum(1 for i in deps.startup_manager.get_startup_items() if i.is_enabled))
        legacy = safe(lambda: len(deps.startup_manager.get_legacy_backups()), 0)
        damaged = safe(lambda: len(deps.service_manager.get_damaged_services()), 0) if deps.service_manager else 0
        tips = build_recommendations(info, startup_enabled, damaged, legacy)
        return info, startup_enabled, damaged, tips

    def _show(self, data) -> None:
        info, startup_enabled, damaged, tips = data
        self._refresh_btn.configure(state="normal")
        self._status.configure(text="")
        self.app.set_nav_alert("services", damaged > 0)

        value, detail, _ = self._cards["os"]
        value.configure(text=truncate(info.os_name, 40))
        detail.configure(text=f"Ligado há {format_duration(info.uptime_seconds)}")

        value, detail, _ = self._cards["cpu"]
        value.configure(text=truncate(info.cpu_name or "Desconhecido", 44))
        detail.configure(text=f"{info.cpu_count} núcleos lógicos" if info.cpu_count else "")

        value, detail, bar = self._cards["ram"]
        if info.ram_total:
            used = info.ram_total - (info.ram_available or 0)
            value.configure(text=f"{info.ram_used_percent:.0f}% em uso")
            detail.configure(text=f"{format_bytes(used)} de {format_bytes(info.ram_total)}")
            bar.set(min(1.0, info.ram_used_percent / 100))
        else:
            value.configure(text="—")

        value, detail, bar = self._cards["disk"]
        if info.disk_total:
            value.configure(text=f"{format_bytes(info.disk_free)} livres")
            detail.configure(text=f"de {format_bytes(info.disk_total)} em {info.disk_drive}")
            bar.set(min(1.0, 1 - info.disk_free / info.disk_total))
        else:
            value.configure(text="—")

        for widget in self._tips_box.winfo_children():
            widget.destroy()
        for level, text in tips:
            row = ctk.CTkFrame(self._tips_box, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text="●", font=font(12), text_color=LEVEL_COLORS.get(level, TEXT_PRIMARY),
                         width=18).pack(side="left", anchor="n")
            ctk.CTkLabel(row, text=text, font=font(13), text_color=TEXT_PRIMARY, anchor="w",
                         justify="left", wraplength=700).pack(side="left", fill="x", anchor="w")

    def _on_error(self, exc) -> None:
        self._refresh_btn.configure(state="normal")
        self._status.configure(text=f"Erro ao ler informações: {exc}")

    # ------------------------------------------------------------ ações

    def create_restore_point(self) -> None:
        self._restore_btn.configure(state="disabled")
        self._status.configure(text="Criando ponto de restauração (pode levar 1 minuto)…")

        def done(result):
            self._restore_btn.configure(state="normal")
            self._status.configure(text="")
            (self.dialogs.info if result.ok else self.dialogs.warning)("Ponto de restauração", result.message)

        def failed(exc):
            self._restore_btn.configure(state="normal")
            self._status.configure(text="")
            self.dialogs.error("Ponto de restauração", f"Erro inesperado: {exc}")

        self.runner.submit(self.deps.create_restore_point, done, failed, name="ponto-restauracao")
