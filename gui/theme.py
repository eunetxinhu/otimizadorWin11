"""Paleta, fontes, botões e formatadores compartilhados pela interface."""

from __future__ import annotations

from functools import cache

import customtkinter as ctk

from models import ServiceRisk

# ---------- Paleta (preto/amarelo)
BG_MAIN = "#0A0A0A"
BG_SIDEBAR = "#111111"
BG_CARD = "#1A1A1A"
BG_CARD_HOVER = "#222222"
BORDER_SUBTLE = "#262626"
YELLOW = "#FFD60A"
YELLOW_HOVER = "#E6C000"
TEXT_PRIMARY = "#F5F5F5"
TEXT_SECONDARY = "#8C8C8C"
TEXT_MUTED = "#5C5C5C"
GREEN = "#4CAF50"
RED = "#E64545"
RED_HOVER = "#C93A3A"
ON_YELLOW = "#0A0A0A"

RISK_COLORS = {
    ServiceRisk.SAFE: GREEN,
    ServiceRisk.CAUTION: YELLOW,
    ServiceRisk.CRITICAL: RED,
}

LEVEL_COLORS = {"danger": RED, "warning": YELLOW, "info": TEXT_PRIMARY, "ok": GREEN}


@cache
def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    """Fontes em cache (criar CTkFont repetidamente vaza objetos no Tk)."""
    return ctk.CTkFont(size=size, weight=weight)


class PrimaryButton(ctk.CTkButton):
    """Ação principal: fundo amarelo, texto preto."""

    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", YELLOW)
        kwargs.setdefault("hover_color", YELLOW_HOVER)
        kwargs.setdefault("text_color", ON_YELLOW)
        kwargs.setdefault("text_color_disabled", "#3A3A3A")
        kwargs.setdefault("font", font(13, "bold"))
        kwargs.setdefault("corner_radius", 8)
        kwargs.setdefault("height", 36)
        super().__init__(master, **kwargs)


class SecondaryButton(ctk.CTkButton):
    """Ação secundária: só contorno."""

    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("hover_color", BG_CARD_HOVER)
        kwargs.setdefault("text_color", TEXT_PRIMARY)
        kwargs.setdefault("text_color_disabled", TEXT_MUTED)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", BORDER_SUBTLE)
        kwargs.setdefault("font", font(13))
        kwargs.setdefault("corner_radius", 8)
        kwargs.setdefault("height", 36)
        super().__init__(master, **kwargs)


class DangerButton(ctk.CTkButton):
    """Ação de correção urgente (ex: reparar serviço danificado)."""

    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", RED)
        kwargs.setdefault("hover_color", RED_HOVER)
        kwargs.setdefault("text_color", "#FFFFFF")
        kwargs.setdefault("font", font(13, "bold"))
        kwargs.setdefault("corner_radius", 8)
        kwargs.setdefault("height", 36)
        super().__init__(master, **kwargs)


def card(master, **kwargs) -> ctk.CTkFrame:
    kwargs.setdefault("fg_color", BG_CARD)
    kwargs.setdefault("corner_radius", 10)
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("border_color", BORDER_SUBTLE)
    return ctk.CTkFrame(master, **kwargs)


def separator(master) -> ctk.CTkFrame:
    return ctk.CTkFrame(master, fg_color=BORDER_SUBTLE, height=1, corner_radius=0)


# ---------- Formatadores

def format_bytes(num_bytes: int | float | None) -> str:
    if num_bytes is None:
        return "—"
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(value) < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
