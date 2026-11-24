from __future__ import annotations

import customtkinter as ctk

from gui.pages.base import BasePage
from gui.theme import (
    BG_CARD, BORDER_SUBTLE, RED, RISK_COLORS, TEXT_PRIMARY, TEXT_SECONDARY, DangerButton,
    PrimaryButton, SecondaryButton, card, font, separator, truncate,
)
from models import ServiceRisk


class ServicesPage(BasePage):
    title = "Serviços"
    subtitle = ("Só aparecem serviços conhecidos e seguros de desativar. Serviços críticos do sistema "
                "nunca são exibidos. O estado original é guardado para o botão 'Reativar'.")

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(2, weight=1)
        self._services = []
        self._action_buttons: list[ctk.CTkButton] = []

        # Aviso de serviços danificados pela v1.0 (só aparece se houver).
        self._banner = card(self, border_color=RED)
        banner_text = ctk.CTkFrame(self._banner, fg_color="transparent")
        banner_text.pack(side="left", fill="x", expand=True, padx=16, pady=12)
        self._banner_title = ctk.CTkLabel(banner_text, text="", font=font(14, "bold"),
                                          text_color=RED, anchor="w")
        self._banner_title.pack(anchor="w")
        ctk.CTkLabel(banner_text, font=font(12), text_color=TEXT_PRIMARY, anchor="w", justify="left",
                     wraplength=560,
                     text="A versão 1.0 deste app trocava o executável dos serviços que desativava, "
                          "deixando-os quebrados. O reparo devolve a configuração original do Windows "
                          "(eles continuam desativados até você clicar em 'Reativar').").pack(anchor="w")
        self._repair_all_btn = DangerButton(self._banner, text="Reparar todos", width=140,
                                            command=self.repair_all)
        self._repair_all_btn.pack(side="right", padx=16)

        self._scroll = ctk.CTkScrollableFrame(self, fg_color=BG_CARD, corner_radius=10,
                                              border_width=1, border_color=BORDER_SUBTLE)
        self._scroll.grid(row=2, column=0, sticky="nsew", pady=(0, 16))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew")
        self._refresh_btn = SecondaryButton(buttons, text="Atualizar lista", command=self.refresh)
        self._refresh_btn.pack(side="left", padx=(0, 10))
        self._safe_btn = SecondaryButton(buttons, text="Desativar todos os seguros", command=self.disable_all_safe)
        self._safe_btn.pack(side="left", padx=(0, 16))
        self._status = ctk.CTkLabel(buttons, text="", font=font(12), text_color=TEXT_SECONDARY)
        self._status.pack(side="left")

    # ------------------------------------------------------------ dados

    def refresh(self) -> None:
        mgr = self.deps.service_manager
        if mgr is None:
            self._show_unavailable()
            return
        self._set_busy(True, "Lendo serviços…")
        self.runner.submit(mgr.get_manageable_services, self._render, self._on_error, name="servicos")

    def _show_unavailable(self) -> None:
        for widget in self._scroll.winfo_children():
            widget.destroy()
        reason = getattr(self.app, "service_manager_error", None) or "pywin32 indisponível"
        ctk.CTkLabel(self._scroll, text="Não foi possível acessar os serviços do Windows.\n"
                                        f"Detalhe: {reason}\n\nReinstale com: pip install pywin32",
                     text_color=TEXT_SECONDARY, justify="left").pack(pady=16, padx=14, anchor="w")
        self._refresh_btn.configure(state="disabled")
        self._safe_btn.configure(state="disabled")

    def _on_error(self, exc) -> None:
        self._set_busy(False, f"Erro ao ler serviços: {exc}")

    def _render(self, services) -> None:
        self._services = services
        for widget in self._scroll.winfo_children():
            widget.destroy()
        self._action_buttons.clear()

        damaged = [s for s in services if s.is_damaged]
        self.app.set_nav_alert("services", bool(damaged))
        if damaged:
            self._banner_title.configure(text=f"{len(damaged)} serviço(s) danificado(s) pela versão anterior")
            self._banner.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        else:
            self._banner.grid_remove()

        if not services:
            ctk.CTkLabel(self._scroll, text="Nenhum serviço da lista encontrado neste PC.",
                         text_color=TEXT_SECONDARY).pack(pady=16)
        for i, service in enumerate(services):
            if i > 0:
                separator(self._scroll).pack(fill="x", padx=14)
            self._service_row(service)

        self._set_busy(False, "")

    def _service_row(self, service) -> None:
        row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)

        info_col = ctk.CTkFrame(row, fg_color="transparent")
        info_col.pack(side="left", fill="x", expand=True)
        top = ctk.CTkFrame(info_col, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=service.display_name, font=font(14, "bold"),
                     text_color=TEXT_PRIMARY).pack(side="left")
        ctk.CTkLabel(top, text=f"   {service.state.label} · {service.start_type.label}", font=font(12),
                     text_color=TEXT_SECONDARY).pack(side="left")
        ctk.CTkLabel(top, text=f"   {service.risk.value}", font=font(12, "bold"),
                     text_color=RISK_COLORS[service.risk]).pack(side="left")

        ctk.CTkLabel(info_col, text=service.explanation, font=font(12), text_color=TEXT_SECONDARY,
                     wraplength=560, justify="left", anchor="w").pack(anchor="w", pady=(4, 0))
        if service.is_damaged:
            ctk.CTkLabel(info_col, text=f"Danificado: executável trocado por {truncate(service.binary_path, 70)}",
                         font=font(12, "bold"), text_color=RED, wraplength=560, justify="left",
                         anchor="w").pack(anchor="w", pady=(4, 0))

        if service.is_damaged:
            btn = DangerButton(row, text="Reparar", width=120,
                               command=lambda s=service: self._run_action("repair", s))
        elif service.is_disabled:
            btn = SecondaryButton(row, text="Reativar", width=120,
                                  command=lambda s=service: self._run_action("restore", s))
        else:
            btn = PrimaryButton(row, text="Desativar", width=120,
                                command=lambda s=service: self._run_action("disable", s))
        btn.pack(side="right")
        self._action_buttons.append(btn)

    # ------------------------------------------------------------ ações

    def _run_action(self, action: str, service) -> None:
        mgr = self.deps.service_manager
        if action == "disable":
            question = f"Desativar '{service.display_name}'?\n\n{service.explanation}"
            if service.risk == ServiceRisk.CAUTION:
                question += "\n\nEste serviço é marcado como 'Cautela'."
            if not self.dialogs.ask("Desativar serviço", question):
                return
            fn, verb = (lambda: mgr.disable_service(service.service_name)), "Desativando"
        elif action == "restore":
            fn, verb = (lambda: mgr.restore_service(service.service_name)), "Reativando"
        else:
            fn, verb = (lambda: mgr.repair_service(service.service_name)), "Reparando"

        self._set_busy(True, f"{verb} {service.display_name}…")

        def done(result):
            self._set_busy(False, "")
            (self.dialogs.info if result.ok else self.dialogs.error)(service.display_name, result.message)
            self.refresh()

        self.runner.submit(fn, done, self._after_failure, name=f"servico-{action}")

    def repair_all(self) -> None:
        mgr = self.deps.service_manager
        self._set_busy(True, "Reparando serviços…")
        self.runner.submit(mgr.repair_all_damaged, lambda r: self._batch_done("Reparo", r),
                           self._after_failure, name="reparar-todos")

    def disable_all_safe(self) -> None:
        targets = [s for s in self._services
                   if s.risk == ServiceRisk.SAFE and not s.is_disabled and not s.is_damaged]
        if not targets:
            self.dialogs.info("Serviços", "Todos os serviços marcados como 'Seguro' já estão desativados.")
            return
        names = "\n".join(f"• {s.display_name}" for s in targets)
        if not self.dialogs.ask("Desativar serviços seguros", f"Desativar estes serviços?\n\n{names}"):
            return
        mgr = self.deps.service_manager
        self._set_busy(True, "Desativando serviços…")
        self.runner.submit(lambda: {s.display_name: mgr.disable_service(s.service_name) for s in targets},
                           lambda r: self._batch_done("Desativação", r), self._after_failure,
                           name="desativar-seguros")

    def _batch_done(self, label: str, results: dict) -> None:
        self._set_busy(False, "")
        ok = sum(1 for r in results.values() if r.ok)
        failed = {name: r.message for name, r in results.items() if not r.ok}
        message = f"{ok} de {len(results)} serviço(s) concluído(s)."
        if failed:
            message += "\n\nFalharam:\n" + "\n".join(f"• {n}: {m}" for n, m in failed.items())
        (self.dialogs.error if failed else self.dialogs.info)(label, message)
        self.refresh()

    def _after_failure(self, exc) -> None:
        self._set_busy(False, "")
        self.dialogs.error("Serviços", f"Erro inesperado: {exc}")
        self.refresh()

    def _set_busy(self, busy: bool, status: str) -> None:
        state = "disabled" if busy else "normal"
        for btn in [*self._action_buttons, self._refresh_btn, self._safe_btn, self._repair_all_btn]:
            try:
                btn.configure(state=state)
            except Exception:
                pass  # botão já destruído numa atualização da lista
        self._status.configure(text=status)
