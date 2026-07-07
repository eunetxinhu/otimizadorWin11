"""
Interface principal do "eunetxinhu otimizações", construída com customtkinter.
Design minimalista: navegação lateral + conteúdo, paleta preto/amarelo.
"""

import customtkinter as ctk
from tkinter import messagebox

from services.startup_manager import StartupManager
from services.temp_cleaner import TempCleanerService
from services.service_manager import ServiceManager
from models import ServiceRisk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")  # sobrescrito pelas cores abaixo

# ---------- Paleta ----------
BG_MAIN = "#0A0A0A"
BG_SIDEBAR = "#111111"
BG_CARD = "#1A1A1A"
BORDER_SUBTLE = "#262626"
YELLOW = "#FFD60A"
YELLOW_HOVER = "#E6C000"
TEXT_PRIMARY = "#F5F5F5"
TEXT_SECONDARY = "#8C8C8C"
RISK_COLORS = {
    ServiceRisk.SAFE: "#4CAF50",
    ServiceRisk.CAUTION: YELLOW,
    ServiceRisk.CRITICAL: "#E64545",
}


def format_bytes(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} GB"


class PrimaryButton(ctk.CTkButton):
    """Botão de ação principal: fundo amarelo, texto preto."""
    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", YELLOW)
        kwargs.setdefault("hover_color", YELLOW_HOVER)
        kwargs.setdefault("text_color", "#0A0A0A")
        kwargs.setdefault("font", ctk.CTkFont(size=13, weight="bold"))
        kwargs.setdefault("corner_radius", 8)
        kwargs.setdefault("height", 36)
        super().__init__(master, **kwargs)


class SecondaryButton(ctk.CTkButton):
    """Botão secundário: contorno, sem preenchimento."""
    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("hover_color", BG_CARD)
        kwargs.setdefault("text_color", TEXT_PRIMARY)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", BORDER_SUBTLE)
        kwargs.setdefault("corner_radius", 8)
        kwargs.setdefault("height", 36)
        super().__init__(master, **kwargs)


class OtimizacoesApp(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title("eunetxinhu otimizações")
        self.geometry("1040x660")
        self.configure(fg_color=BG_MAIN)

        self.startup_manager = StartupManager()
        self.temp_cleaner = TempCleanerService()
        self.service_manager = ServiceManager()

        self._startup_rows: list[tuple] = []
        self._temp_folders: list[str] = []

        # Layout raiz: sidebar fixa + área de conteúdo
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()

        self.content = ctk.CTkFrame(self, fg_color=BG_MAIN)
        self.content.grid(row=0, column=1, sticky="nsew", padx=32, pady=28)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._frames: dict[str, ctk.CTkFrame] = {}
        self._nav_buttons: dict[str, ctk.CTkButton] = {}

        self._build_startup_frame()
        self._build_cleanup_frame()
        self._build_services_frame()

        self.show_frame("startup")

        self.refresh_startup()
        self._load_temp_folders()
        self.refresh_services()

    # ---------- Sidebar ----------

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, fg_color=BG_SIDEBAR, corner_radius=0, width=220)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=24, pady=(32, 40))

        ctk.CTkLabel(
            brand, text="eunetxinhu", font=ctk.CTkFont(size=20, weight="bold"),
            text_color=YELLOW, anchor="w"
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand, text="otimizações", font=ctk.CTkFont(size=13),
            text_color=TEXT_SECONDARY, anchor="w"
        ).pack(anchor="w")

        nav_items = [
            ("startup", "Inicialização"),
            ("cleanup", "Limpeza"),
            ("services", "Serviços"),
        ]

        self._nav_container = ctk.CTkFrame(sidebar, fg_color="transparent")
        self._nav_container.pack(fill="x", padx=12)

        for key, label in nav_items:
            btn = ctk.CTkButton(
                self._nav_container, text=label, anchor="w",
                fg_color="transparent", hover_color=BG_CARD,
                text_color=TEXT_SECONDARY, corner_radius=8, height=40,
                font=ctk.CTkFont(size=14),
                command=lambda k=key: self.show_frame(k)
            )
            btn.pack(fill="x", pady=2)
            self._nav_buttons[key] = btn

        ctk.CTkLabel(
            sidebar, text="v1.0", text_color="#4D4D4D", font=ctk.CTkFont(size=11)
        ).pack(side="bottom", pady=20)

    def show_frame(self, key: str):
        for frame in self._frames.values():
            frame.grid_remove()
        self._frames[key].grid(row=0, column=0, sticky="nsew")

        for k, btn in self._nav_buttons.items():
            if k == key:
                btn.configure(fg_color=YELLOW, text_color="#0A0A0A", font=ctk.CTkFont(size=14, weight="bold"))
            else:
                btn.configure(fg_color="transparent", text_color=TEXT_SECONDARY, font=ctk.CTkFont(size=14, weight="normal"))

    def _section_header(self, parent, title: str, subtitle: str):
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 20))

        ctk.CTkLabel(
            header, text=title, font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT_PRIMARY, anchor="w"
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text=subtitle, font=ctk.CTkFont(size=13),
            text_color=TEXT_SECONDARY, anchor="w", wraplength=680, justify="left"
        ).pack(anchor="w", pady=(4, 0))

        return header

    # ---------- Inicialização ----------

    def _build_startup_frame(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)
        self._frames["startup"] = frame

        self._section_header(
            frame, "Inicialização",
            "Programas que abrem junto com o Windows. Desmarque os que você não usa todo dia."
        )

        self.startup_scroll = ctk.CTkScrollableFrame(
            frame, fg_color=BG_CARD, corner_radius=10, border_width=1, border_color=BORDER_SUBTLE
        )
        self.startup_scroll.grid(row=2, column=0, sticky="nsew", pady=(0, 16))

        button_row = ctk.CTkFrame(frame, fg_color="transparent")
        button_row.grid(row=3, column=0, sticky="ew")

        SecondaryButton(button_row, text="Atualizar lista", command=self.refresh_startup).pack(side="left", padx=(0, 10))
        PrimaryButton(button_row, text="Aplicar desativações selecionadas", command=self.apply_startup_changes).pack(side="left")

    def refresh_startup(self):
        for widget in self.startup_scroll.winfo_children():
            widget.destroy()
        self._startup_rows.clear()

        items = self.startup_manager.get_startup_items()

        if not items:
            ctk.CTkLabel(self.startup_scroll, text="Nenhum item de inicialização encontrado.", text_color=TEXT_SECONDARY).pack(pady=16)
            return

        for i, item in enumerate(items):
            row = ctk.CTkFrame(self.startup_scroll, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=10)

            if i > 0:
                ctk.CTkFrame(self.startup_scroll, fg_color=BORDER_SUBTLE, height=1).pack(fill="x", padx=14)

            var = ctk.BooleanVar(value=True)
            ctk.CTkCheckBox(
                row, text="", variable=var, width=20, checkbox_width=20, checkbox_height=20,
                fg_color=YELLOW, hover_color=YELLOW_HOVER, border_color=BORDER_SUBTLE
            ).pack(side="left", padx=(0, 14))

            text_col = ctk.CTkFrame(row, fg_color="transparent")
            text_col.pack(side="left", fill="x", expand=True)

            ctk.CTkLabel(text_col, text=item.name, font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT_PRIMARY, anchor="w").pack(anchor="w")

            command_display = item.command if len(item.command) <= 80 else item.command[:77] + "..."
            ctk.CTkLabel(text_col, text=command_display, font=ctk.CTkFont(size=12), text_color=TEXT_SECONDARY, anchor="w").pack(anchor="w")

            ctk.CTkLabel(row, text=item.location, font=ctk.CTkFont(size=11), text_color="#5C5C5C").pack(side="right")

            self._startup_rows.append((item, var))

    def apply_startup_changes(self):
        to_disable = [item for item, var in self._startup_rows if not var.get()]

        if not to_disable:
            messagebox.showinfo(
                "Nada para aplicar",
                "Nenhum item foi desmarcado. Desmarque a caixa dos programas que deseja desativar."
            )
            return

        confirm = messagebox.askyesno(
            "Confirmar alteração",
            f"Isso vai remover {len(to_disable)} programa(s) da inicialização automática do Windows.\n"
            "Você pode restaurar reinstalando o programa ou usando o backup salvo pelo app.\n\nContinuar?"
        )
        if not confirm:
            return

        success = sum(1 for item in to_disable if self.startup_manager.disable_startup_item(item))
        failed = len(to_disable) - success

        messagebox.showinfo(
            "Resultado",
            f"{success} item(ns) desativado(s). {failed} falharam "
            "(geralmente por falta de permissão de administrador)."
        )
        self.refresh_startup()

    # ---------- Limpeza ----------

    def _build_cleanup_frame(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)
        self._frames["cleanup"] = frame

        self._section_header(
            frame, "Limpeza",
            "Remove arquivos temporários, cache do Explorer e Prefetch. "
            "Reversível a qualquer momento — o Windows recria esses arquivos."
        )

        self.temp_folders_box = ctk.CTkTextbox(
            frame, fg_color=BG_CARD, corner_radius=10, border_width=1, border_color=BORDER_SUBTLE,
            font=ctk.CTkFont(size=13), text_color=TEXT_SECONDARY
        )
        self.temp_folders_box.grid(row=2, column=0, sticky="nsew", pady=(0, 16))
        self.temp_folders_box.configure(state="disabled")

        button_row = ctk.CTkFrame(frame, fg_color="transparent")
        button_row.grid(row=3, column=0, sticky="ew")

        SecondaryButton(button_row, text="Calcular espaço", command=self.calculate_space).pack(side="left", padx=(0, 10))
        PrimaryButton(button_row, text="Limpar agora", command=self.clean_now).pack(side="left", padx=(0, 16))

        self.space_result_label = ctk.CTkLabel(button_row, text="", text_color=TEXT_PRIMARY, font=ctk.CTkFont(size=13))
        self.space_result_label.pack(side="left")

    def _load_temp_folders(self):
        self._temp_folders = self.temp_cleaner.get_default_target_folders()

        self.temp_folders_box.configure(state="normal")
        self.temp_folders_box.delete("1.0", "end")
        for folder in self._temp_folders:
            self.temp_folders_box.insert("end", f"  {folder}\n")
        self.temp_folders_box.configure(state="disabled")

    def calculate_space(self):
        total = self.temp_cleaner.calculate_potential_space_freed(self._temp_folders)
        self.space_result_label.configure(text=f"Espaço estimado a liberar: {format_bytes(total)}")

    def clean_now(self):
        confirm = messagebox.askyesno(
            "Confirmar limpeza",
            "Isso vai apagar arquivos temporários, cache do Explorer e do Prefetch.\n"
            "Arquivos em uso são pulados automaticamente. Continuar?"
        )
        if not confirm:
            return

        results = self.temp_cleaner.clean(self._temp_folders)
        total_freed = sum(r.bytes_freed for r in results)
        total_files = sum(r.files_deleted for r in results)

        self.space_result_label.configure(
            text=f"Limpeza concluída: {total_files} arquivo(s), {format_bytes(total_freed)} liberado(s)."
        )

    # ---------- Serviços ----------

    def _build_services_frame(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)
        self._frames["services"] = frame

        self._section_header(
            frame, "Serviços",
            "Apenas serviços conhecidos e seguros aparecem aqui. "
            "Serviços críticos do sistema nunca são exibidos para desativação."
        )

        self.services_scroll = ctk.CTkScrollableFrame(
            frame, fg_color=BG_CARD, corner_radius=10, border_width=1, border_color=BORDER_SUBTLE
        )
        self.services_scroll.grid(row=2, column=0, sticky="nsew", pady=(0, 16))

        SecondaryButton(frame, text="Atualizar lista", command=self.refresh_services).grid(row=3, column=0, sticky="w")

    def refresh_services(self):
        for widget in self.services_scroll.winfo_children():
            widget.destroy()

        services = self.service_manager.get_manageable_services()

        if not services:
            ctk.CTkLabel(self.services_scroll, text="Nenhum serviço da whitelist encontrado neste PC.", text_color=TEXT_SECONDARY).pack(pady=16)
            return

        for i, service in enumerate(services):
            row = ctk.CTkFrame(self.services_scroll, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=12)

            if i > 0:
                ctk.CTkFrame(self.services_scroll, fg_color=BORDER_SUBTLE, height=1).pack(fill="x", padx=14)

            info_col = ctk.CTkFrame(row, fg_color="transparent")
            info_col.pack(side="left", fill="x", expand=True)

            top_line = ctk.CTkFrame(info_col, fg_color="transparent")
            top_line.pack(fill="x")

            ctk.CTkLabel(top_line, text=service.display_name, font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT_PRIMARY).pack(side="left")
            ctk.CTkLabel(top_line, text=f"   {service.status} · {service.start_type}", font=ctk.CTkFont(size=12), text_color=TEXT_SECONDARY).pack(side="left")
            ctk.CTkLabel(top_line, text=f"   {service.risk.value}", font=ctk.CTkFont(size=12, weight="bold"), text_color=RISK_COLORS[service.risk]).pack(side="left")

            ctk.CTkLabel(
                info_col, text=service.explanation, font=ctk.CTkFont(size=12), text_color=TEXT_SECONDARY,
                wraplength=600, justify="left"
            ).pack(anchor="w", pady=(4, 0))

            already_disabled = service.start_type == "Disabled"
            if already_disabled:
                SecondaryButton(row, text="Já desativado", width=130, state="disabled").pack(side="right")
            else:
                PrimaryButton(row, text="Desativar", width=130, command=lambda s=service: self._disable_service(s)).pack(side="right")

    def _disable_service(self, service):
        confirm = messagebox.askyesno(
            "Confirmar", f"Desativar '{service.display_name}'?\n\n{service.explanation}"
        )
        if not confirm:
            return

        ok = self.service_manager.disable_service(service.service_name)

        if ok:
            messagebox.showinfo("Resultado", "Serviço desativado com sucesso.")
        else:
            messagebox.showerror(
                "Resultado",
                "Não foi possível desativar (verifique se o app está rodando como administrador)."
            )

        self.refresh_services()

