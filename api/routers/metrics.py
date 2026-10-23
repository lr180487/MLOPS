"""GET /api/metrics/training, /api/metrics/live, /api/metrics/summary"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import Ctx

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/training")
async def metrics_training(ctx: Ctx):
    """Métricas de entrenamiento (models/metricas.json), cacheadas."""
    if not ctx.predictor.metricas:
        raise HTTPException(status_code=404, detail="No existe models/metricas.json. Ejecuta el notebook.")
    valor, _, _ = await ctx.cache.get_or_compute(f"metrics:training:{ctx.predictor.hash}", lambda: ctx.predictor.metricas, ttl=3600)
    return valor


@router.get("/live")
async def metrics_live(ctx: Ctx):
    """Métricas de producción: ventana móvil, acumulado, latencias, deriva, serie temporal."""
    return ctx.monitor.metricas()


@router.get("/summary")
async def metrics_summary(ctx: Ctx):
    """Resumen combinado: entrenamiento + producción + persistencia + caché + SSE."""
    return await ctx.service.resumen()
