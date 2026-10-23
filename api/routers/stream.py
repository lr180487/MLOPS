"""GET /api/stream — Server-Sent Events"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..core.monitor import ahora_iso
from ..deps import Ctx

router = APIRouter(prefix="/stream", tags=["stream"])


@router.get("")
@router.get("/", include_in_schema=False)
async def stream(request: Request, ctx: Ctx):
    """Emite `prediccion`, `feedback`, `metricas`, `modelo` y `ping` en tiempo real (text/event-stream)."""

    async def generador():
        with ctx.bus.subscribe() as cola:
            yield "retry: 3000\n\n"
            yield ctx.bus.formatear({"tipo": "metricas", "metricas": ctx.monitor.metricas()})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(cola.get(), timeout=15)
                    yield ctx.bus.formatear(msg)
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'tipo': 'ping', 'timestamp': ahora_iso()})}\n\n"

    return StreamingResponse(generador(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
