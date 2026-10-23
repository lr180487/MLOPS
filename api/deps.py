"""
api/deps.py — Contexto de la aplicación (todos los componentes) e inyección
de dependencias para los routers: `ctx: Ctx = Depends(get_ctx)`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request

from .config import Settings
from .core.cache import CacheManager
from .core.database import Database
from .core.events import EventBus
from .core.model import Predictor
from .core.monitor import Monitor
from .core.service import PredictionService
from .core.simulator import Simulator


@dataclass
class AppContext:
    settings: Settings
    db: Database
    cache: CacheManager
    bus: EventBus
    predictor: Predictor
    monitor: Monitor
    service: PredictionService
    simulator: Simulator
    inicio: float = field(default_factory=time.time)

    @property
    def uptime_s(self) -> float:
        return round(time.time() - self.inicio, 1)


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]
