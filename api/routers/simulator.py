"""GET /api/simulator/status, POST /api/simulator/start, POST /api/simulator/stop (+ /burst complementario)"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ..deps import Ctx
from ..schemas import SimuladorBurst, SimuladorStart

log = logging.getLogger("api.simulator")
router = APIRouter(prefix="/simulator", tags=["simulator"])


@router.get("/status")
async def simulator_status(ctx: Ctx):
    return ctx.simulator.status()


@router.post("/start")
async def simulator_start(ctx: Ctx, body: SimuladorStart | None = None):
    """Arranca el simulador (o cambia su intervalo si ya está activo)."""
    r = await ctx.simulator.start(body.intervalo if body else None)
    log.info("simulador start intervalo=%s", r["intervalo_s"])
    return {"ok": True, **r}


@router.post("/stop")
async def simulator_stop(ctx: Ctx):
    r = await ctx.simulator.stop()
    log.info("simulador stop")
    return {"ok": True, **r}


@router.post("/burst")
async def simulator_burst(ctx: Ctx, body: SimuladorBurst | None = None):
    """(Complementario) Genera una ráfaga de eventos de golpe."""
    r = await ctx.simulator.rafaga(body.cantidad if body else 20)
    return {"ok": True, **r}
