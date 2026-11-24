from __future__ import annotations

import threading

import customtkinter as ctk

from gui.pages.base import BasePage
from gui.theme import (
    BG_CARD, BORDER_SUBTLE, GREEN, RED, TEXT_PRIMARY, TEXT_SECONDARY, YELLOW, YELLOW_HOVER,
    PrimaryButton, SecondaryButton, font, format_bytes, separator,
)


class CleanupPage(BasePage):
    title = "Limpeza"
    subtitle = ("Remove temporários e caches que o Windows e os programas recriam sozinhos. "
                "Arquivos em uso são pulados, e atalhos/junctions nunca são seguidos.")

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(1, weight=1)
        self._vars: dict[str, ctk.BooleanVar] = {}
        self._size_labels: dict[str, ctk.CTkLabel] = {}
        self._cancel = threading.Event()
        self._busy = False

        scroll = ctk.CTkScrollableFrame(self, fg_color=BG_CARD, corner_radius=10,
                                        border_width=1, border_color=BORDER_SUBTLE)
        scroll.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        for i, cat in enumerate(self.deps.temp_cleaner.categories):
            if i > 0:
                separator(scroll).pack(fill="x", padx=14)
            self._category_row(scroll, cat)

        options = ctk.CTkFrame(self, fg_color="transparent")
        options.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self._skip_recent = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(options, text="Ignorar arquivos modificados nas últimas 24 horas (recomendado)",
                      variable=self._skip_recent, font=font(13), text_color=TEXT_PRIMARY,
                      progress_color=YELLOW, button_color=TEXT_PRIMARY, button_hover_color=YELLOW_HOVER,
                      command=self.analyze).pack(side="left")

        progress_row = ctk.CTkFrame(self, fg_color="transparent")
        progress_row.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        self._progress = ctk.CTkProgressBar(progress_row, mode="indeterminate", height=6,
                                            progress_color=YELLOW, fg_color=BORDER_SUBTLE)
        self._status = ctk.CTkLabel(progress_row, text="", font=font(13), text_color=TEXT_PRIMARY,
                                    anchor="w", justify="left", wraplength=760)
        self._status.pack(side="left", fill="x")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, sticky="ew")
        self._analyze_btn = SecondaryButton(buttons, text="Analisar", command=self.analyze)
        self._analyze_btn.pack(side="left", padx=(0, 10))
        self._clean_btn = PrimaryButton(buttons, text="Limpar selecionados", command=self.clean)
        self._clean_btn.pack(side="left", padx=(0, 10))
        self._cancel_btn = SecondaryButton(buttons, text="Cancelar", width=100, command=self._cancel.set)

    def _category_row(self, parent, cat) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)

        var = ctk.BooleanVar(value=cat.default_selected)
        self._vars[cat.key] = var
        ctk.CTkCheckBox(row, text="", variable=var, width=22, checkbox_width=20, checkbox_height=20,
                        fg_color=YELLOW, hover_color=YELLOW_HOVER, border_color=TEXT_SECONDARY,
                        checkmark_color="#0A0A0A").pack(side="left", padx=(0, 12), anchor="n", pady=2)

        text_col = ctk.CTkFrame(row, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(text_col, text=cat.title, font=font(14, "bold"), text_color=TEXT_PRIMARY,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(text_col, text=cat.description, font=font(12), text_color=TEXT_SECONDARY,
                     anchor="w", justify="left", wraplength=560).pack(anchor="w")
        if cat.warning:
            ctk.CTkLabel(text_col, text=cat.warning, font=font(12, "bold"), text_color=YELLOW,
                         anchor="w", justify="left", wraplength=560).pack(anchor="w", pady=(2, 0))

        size = ctk.CTkLabel(row, text="—", font=font(13, "bold"), text_color=TEXT_SECONDARY, width=110,
                            anchor="e")
        size.pack(side="right", anchor="n")
        self._size_labels[cat.key] = size

    # ------------------------------------------------------------ ações

    def refresh(self) -> None:
        self.analyze()

    def _selected_keys(self) -> list[str]:
        return [key for key, var in self._vars.items() if var.get()]

    def analyze(self) -> None:
        if self._busy:
            return
        keys = list(self._vars)  # a prévia mostra todas as categorias
        skip_recent = self._skip_recent.get()
        self._start("Analisando…")
        cleaner = self.deps.temp_cleaner
        self.runner.submit(
            lambda: cleaner.scan(keys, skip_recent=skip_recent, cancel=self._cancel, progress=self._progress_cb),
            self._show_scan, self._failed, name="analisar-limpeza")

    def _show_scan(self, results) -> None:
        self._stop()
        total = 0
        for key, label in self._size_labels.items():
            res = results.get(key)
            if res is None:
                continue
            label.configure(text=format_bytes(res.bytes) if res.files else "vazio",
                            text_color=TEXT_PRIMARY if res.files else TEXT_SECONDARY)
            if self._vars[key].get():
                total += res.bytes
        recent = sum(r.skipped_recent for r in results.values())
        text = f"Espaço que pode ser liberado nos itens marcados: {format_bytes(total)}"
        if recent:
            text += f"  ·  {recent} arquivo(s) recente(s) serão mantidos"
        self._status.configure(text=text, text_color=TEXT_PRIMARY)

    def clean(self) -> None:
        if self._busy:
            return
        keys = self._selected_keys()
        if not keys:
            self.dialogs.info("Limpeza", "Marque pelo menos uma categoria.")
            return
        titles = [c.title for c in self.deps.temp_cleaner.categories if c.key in keys]
        message = "Apagar os arquivos destas categorias?\n\n" + "\n".join(f"• {t}" for t in titles)
        if "recycle_bin" in keys:
            message += "\n\nA Lixeira será esvaziada - isso não pode ser desfeito."
        if not self.dialogs.ask("Confirmar limpeza", message):
            return

        skip_recent = self._skip_recent.get()
        self._start("Limpando…")
        cleaner = self.deps.temp_cleaner
        self.runner.submit(
            lambda: cleaner.clean(keys, skip_recent=skip_recent, cancel=self._cancel, progress=self._progress_cb),
            self._show_clean, self._failed, name="limpeza")

    def _show_clean(self, results) -> None:
        cancelled = self._cancel.is_set()
        self._stop()
        freed = sum(r.bytes_freed for r in results)
        files = sum(r.files_deleted for r in results)
        in_use = sum(r.skipped_in_use for r in results)
        for r in results:
            label = self._size_labels.get(r.category_key)
            if label is not None:
                label.configure(text=f"-{format_bytes(r.bytes_freed)}", text_color=GREEN)
        state = "cancelada" if cancelled else "concluída"
        text = f"Limpeza {state}: {files} arquivo(s), {format_bytes(freed)} liberado(s)."
        if in_use:
            text += f"  {in_use} em uso/protegido(s) foram pulados."
        self._status.configure(text=text, text_color=GREEN)

    def _failed(self, exc) -> None:
        self._stop()
        self._status.configure(text=f"Erro: {exc}", text_color=RED)

    # ------------------------------------------------------------ progresso

    def _progress_cb(self, category_title: str, count: int) -> None:
        # Chamado na thread de trabalho: só agenda a atualização na interface.
        self.runner.call_in_ui(
            lambda: self._status.configure(text=f"{category_title}: {count} arquivo(s) verificados…",
                                           text_color=TEXT_PRIMARY))

    def _start(self, text: str) -> None:
        self._busy = True
        self._cancel.clear()
        self._analyze_btn.configure(state="disabled")
        self._clean_btn.configure(state="disabled")
        self._cancel_btn.pack(side="left")
        self._status.pack_forget()
        self._progress.pack(side="left", padx=(0, 12))
        self._status.pack(side="left", fill="x")
        self._progress.start()
        self._status.configure(text=text, text_color=TEXT_PRIMARY)

    def _stop(self) -> None:
        self._busy = False
        self._progress.stop()
        self._progress.pack_forget()
        self._cancel_btn.pack_forget()
        self._analyze_btn.configure(state="normal")
        self._clean_btn.configure(state="normal")
