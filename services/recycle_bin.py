"""
Lixeira do Windows via Shell API (SHQueryRecycleBinW / SHEmptyRecycleBinW).
Fora do Windows, available() é False e nada acontece.
"""

from __future__ import annotations

import ctypes
import logging
import sys

log = logging.getLogger(__name__)

SHERB_NOCONFIRMATION = 0x1
SHERB_NOPROGRESSUI = 0x2
SHERB_NOSOUND = 0x4


class _SHQUERYRBINFO(ctypes.Structure):
    # No shellapi.h esta struct é "packed" (pshpack1) só em 32 bits.
    if ctypes.sizeof(ctypes.c_void_p) == 4:
        _pack_ = 1
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("i64Size", ctypes.c_int64),
        ("i64NumItems", ctypes.c_int64),
    ]


class RecycleBin:

    def available(self) -> bool:
        return sys.platform == "win32"

    def query(self) -> tuple[int, int] | None:
        """(bytes, quantidade de itens) somando todas as unidades, ou None se falhar."""
        if not self.available():
            return None
        info = _SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
        try:
            hr = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        except Exception:
            log.exception("SHQueryRecycleBinW falhou")
            return None
        if hr != 0:
            log.warning("SHQueryRecycleBinW retornou HRESULT 0x%08X", hr & 0xFFFFFFFF)
            return None
        return int(info.i64Size), int(info.i64NumItems)

    def empty(self) -> bool:
        if not self.available():
            return False
        flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
        try:
            hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
        except Exception:
            log.exception("SHEmptyRecycleBinW falhou")
            return False
        # Lixeira já vazia pode retornar E_UNEXPECTED; o que importa é ficar vazia.
        if hr != 0:
            after = self.query()
            return after is not None and after[1] == 0
        return True
