"""
Executa tarefas demoradas fora da thread da interface.

O Tkinter não é thread-safe: só a thread principal pode mexer em widgets.
Por isso o trabalho roda numa thread e o resultado volta por uma fila, que
a thread principal esvazia com after().
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any
from collections.abc import Callable

log = logging.getLogger(__name__)


class BackgroundRunner:

    def __init__(self, root, poll_ms: int = 60):
        self._root = root
        self._poll_ms = poll_ms
        self._queue: queue.Queue = queue.Queue()
        self._after_id = None
        self._active = 0
        self._stopped = False
        self._poll()

    @property
    def busy(self) -> bool:
        return self._active > 0

    def submit(self, fn: Callable[[], Any],
               on_success: Callable[[Any], None] | None = None,
               on_error: Callable[[BaseException], None] | None = None,
               name: str = "tarefa") -> None:
        """Roda fn() numa thread; os callbacks rodam na thread da interface."""
        self._active += 1

        def worker():
            try:
                result = fn()
            except BaseException as exc:  # noqa: BLE001 - qualquer erro volta para a UI
                log.exception("Falha em %s", name)
                self._queue.put((self._finish, (on_error, exc)))
            else:
                self._queue.put((self._finish, (on_success, result)))

        threading.Thread(target=worker, name=name, daemon=True).start()

    def call_in_ui(self, fn: Callable, *args) -> None:
        """Agenda fn(*args) na thread da interface. Pode ser chamado de qualquer thread."""
        self._queue.put((fn, args))

    def drain(self) -> None:
        """Processa agora tudo o que está na fila (usado também pelos testes)."""
        while True:
            try:
                fn, args = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn(*args)
            except Exception:
                log.exception("Erro num callback da interface")

    def stop(self) -> None:
        self._stopped = True
        if self._after_id is not None:
            try:
                self._root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _finish(self, callback, value) -> None:
        self._active -= 1
        if callback is not None:
            callback(value)

    def _poll(self) -> None:
        if self._stopped:
            return
        self.drain()
        self._after_id = self._root.after(self._poll_ms, self._poll)
