"""POST /api/predictions, POST /api/predictions/batch, GET /api/predictions/{id}, GET /api/predictions"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from ..deps import Ctx
from ..schemas import LoteObservaciones, ObservacionConUmbral, PrediccionOut

log = logging.getLogger("api.predictions")
router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.post("", response_model=PrediccionOut, status_code=201)
@router.post("/", response_model=PrediccionOut, status_code=201, include_in_schema=False)
async def crear_prediccion(obs: ObservacionConUmbral, ctx: Ctx, umbral: float | None = Query(None, ge=0.05, le=0.95)):
    """Predicción individual. Pasa por caché de inferencia → monitor → persistencia → SSE."""
    u = obs.umbral if obs.umbral is not None else (umbral if umbral is not None else 0.5)
    try:
        e = await ctx.service.predecir(obs.model_dump(exclude={"umbral"}), umbral=u, origen="api")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await ctx.service.difundir_metricas()
    log.info("prediction id=%s cultivo=%s p_si=%.3f -> %s cache=%s", e["id"], e["features"]["cultivo"], e["probabilidad_si"],
             ctx.settings.clases[e["prediccion"]], e["cache_hit"])
    return PrediccionOut(id=e["id"], prediccion=ctx.settings.clases[e["prediccion"]], probabilidad_si=e["probabilidad_si"],
                         probabilidad_no=round(1 - e["probabilidad_si"], 4), umbral=u, latencia_ms=e["latencia_ms"],
                         timestamp=e["timestamp"], cache_hit=e["cache_hit"], cache_nivel=e.get("cache_nivel"),
                         modelo_version=e["modelo_version"], features=e["features"])


@router.post("/batch", status_code=201)
async def crear_predicciones_lote(lote: LoteObservaciones, ctx: Ctx, umbral: float | None = Query(None, ge=0.05, le=0.95)):
    """Predicción por lotes (hasta 500 observaciones)."""
    u = lote.umbral if lote.umbral is not None else (umbral if umbral is not None else 0.5)
    try:
        resultados = await ctx.service.predecir_lote([o.model_dump() for o in lote.observaciones], u)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"n": len(resultados), "umbral": u, "cache_hits": sum(1 for r in resultados if r["cache_hit"]), "resultados": resultados}


@router.get("")
@router.get("/", include_in_schema=False)
async def listar_predicciones(ctx: Ctx, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                              cultivo: str | None = None, ciudad: str | None = None, con_feedback: bool | None = None,
                              origen: str | None = None):
    """Historial persistido de predicciones (paginado, filtrable por cultivo, ciudad, origen y feedback)."""
    return await ctx.service.listar(limit, offset, cultivo, con_feedback, origen, ciudad)


@router.get("/{prediction_id}")
async def obtener_prediccion(prediction_id: str, ctx: Ctx):
    """Recupera una predicción por id (caché → base de datos)."""
    p = await ctx.service.obtener(prediction_id)
    if p is None:
        raise HTTPException(status_code=404, detail="prediction_id no encontrado")
    return p
