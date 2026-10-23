"""
api/core/events.py
------------------
Bus de eventos en memoria para Server-Sent Events. Cada cliente SSE recibe una
cola; `publish` reparte el mensaje a todas las colas activas.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import contextmanager
from typing import Iterator


class EventBus:
    def __init__(self, maxsize: int = 200):
        self.maxsize = maxsize
        self._colas: set[asyncio.Queue] = set()
        self.publicados = 0
        self.descartados = 0
        self.ultimo: dict | None = None

    @contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue]:
        cola: asyncio.Queue = asyncio.Queue(maxsize=self.maxsize)
        self._colas.add(cola)
        try:
            yield cola
        finally:
            self._colas.discard(cola)

    async def publish(self, tipo: str, payload: dict) -> None:
        mensaje = {"tipo": tipo, **payload}
        self.publicados += 1
        self.ultimo = {"tipo": tipo, "t": time.time()}
        for q in list(self._colas):
            try:
                q.put_nowait(mensaje)
            except asyncio.QueueFull:
                self.descartados += 1

    @property
    def suscriptores(self) -> int:
        return len(self._colas)

    @staticmethod
    def formatear(mensaje: dict) -> str:
        return f"data: {json.dumps(mensaje, ensure_ascii=False)}\n\n"

    def stats(self) -> dict:
        return {"suscriptores": self.suscriptores, "publicados": self.publicados, "descartados": self.descartados,
                "ultimo": self.ultimo}
