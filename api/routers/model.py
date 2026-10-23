"""GET /api/model/info, GET /api/model/metrics, POST /api/model/reload"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from ..deps import Ctx

log = logging.getLogger("api.model")
router = APIRouter(prefix="/model", tags=["model"])


@router.get("/info")
async def model_info(ctx: Ctx):
    """Metadatos del modelo: features, categorías, rangos, pipeline, hash y versión."""
    valor, _, _ = await ctx.cache.get_or_compute(f"model:info:{ctx.predictor.hash}", ctx.predictor.info, ttl=3600)
    return valor


@router.get("/metrics")
async def model_metrics(ctx: Ctx):
    """Métricas de entrenamiento del modelo cargado (idéntico a /api/metrics/training)."""
    if not ctx.predictor.metricas:
        raise HTTPException(status_code=404, detail="No existe models/metricas.json.")
    return ctx.predictor.metricas


@router.post("/reload")
async def model_reload(ctx: Ctx):
    """Recarga modelo.joblib y metricas.json desde disco sin reiniciar; invalida la caché de inferencia."""
    try:
        r = await asyncio.to_thread(ctx.predictor.reload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"No se pudo recargar el modelo: {exc}") from exc
    ctx.monitor.medias_train = ctx.predictor.medias()
    ctx.monitor.desv_train = ctx.predictor.desviaciones()
    borradas = await ctx.cache.clear("pred:feat")
    await ctx.cache.clear("model:info")
    await ctx.cache.clear("metrics")
    await ctx.bus.publish("modelo", {"modelo": {"version": ctx.predictor.version, "hash": ctx.predictor.hash, "cambio": r["cambio"]}})
    log.info("modelo recargado hash=%s cambio=%s", r["hash_actual"], r["cambio"])
    return {**r, "cache_invalidada": borradas["eliminadas"]}
