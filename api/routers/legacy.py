"""
Alias *deprecated* de la API v1. Siguen funcionando (mismo formato de respuesta)
pero delegan en los servicios nuevos; en Swagger aparecen tachados.

    /health              → /api/health
    /predict             → /api/predictions
    /predict/batch       → /api/predictions/batch
    /feedback (POST)     → /api/feedback   ({id} → {prediction_id})
    /api/info            → /api/model/info
    /api/logs            → /api/system/logs
    /api/simulator       → /api/simulator/start | /stop | /burst
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from ..core.monitor import ahora_iso
from ..deps import Ctx
from ..schemas import ControlSimuladorLegacy, FeedbackLegacy, LoteObservaciones, Observacion

router = APIRouter(tags=["legacy (deprecated)"], deprecated=True)


@router.get("/health", summary="[deprecated] usa /api/health")
async def health_v1(ctx: Ctx):
    return {"status": "ok", "modelo_cargado": ctx.predictor.modelo is not None, "uptime_s": ctx.uptime_s, "timestamp": ahora_iso(),
            "deprecated": True, "usa": "/api/health"}


@router.get("/api/info", summary="[deprecated] usa /api/model/info")
async def info_v1(ctx: Ctx):
    return {**ctx.predictor.info(), "deprecated": True, "usa": "/api/model/info"}


@router.post("/predict", summary="[deprecated] usa POST /api/predictions")
async def predict_v1(obs: Observacion, ctx: Ctx, umbral: float = Query(0.5, ge=0.05, le=0.95)):
    try:
        e = await ctx.service.predecir(obs.model_dump(), umbral=umbral, origen="api-v1")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await ctx.service.difundir_metricas()
    return {"id": e["id"], "prediccion": ctx.settings.clases[e["prediccion"]], "probabilidad_si": e["probabilidad_si"],
            "probabilidad_no": round(1 - e["probabilidad_si"], 4), "umbral": umbral, "latencia_ms": e["latencia_ms"],
            "timestamp": e["timestamp"], "deprecated": True, "usa": "POST /api/predictions"}


@router.post("/predict/batch", summary="[deprecated] usa POST /api/predictions/batch")
async def predict_batch_v1(lote: LoteObservaciones, ctx: Ctx, umbral: float = Query(0.5, ge=0.05, le=0.95)):
    try:
        res = await ctx.service.predecir_lote([o.model_dump() for o in lote.observaciones], umbral, origen="api-v1-batch")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"n": len(res), "umbral": umbral, "resultados": [{"id": r["id"], "prediccion": r["prediccion"], "probabilidad_si": r["probabilidad_si"]} for r in res],
            "deprecated": True, "usa": "POST /api/predictions/batch"}


@router.post("/feedback", summary="[deprecated] usa POST /api/feedback")
async def feedback_v1(fb: FeedbackLegacy, ctx: Ctx):
    try:
        r = await ctx.service.feedback(fb.id, fb.real, origen="api-v1")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="id no encontrado o ya etiquetado") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="id no encontrado o ya etiquetado") from exc
    return {"ok": True, "id": fb.id, "acierto": r["acierto"], "deprecated": True, "usa": "POST /api/feedback"}


@router.get("/api/logs", summary="[deprecated] usa /api/system/logs")
async def logs_v1(ctx: Ctx, n: int = Query(40, ge=1, le=500), archivo: Literal["api", "ejecucion"] = "api"):
    ruta = ctx.settings.logs_dir / f"{archivo}.log"
    lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines() if ruta.exists() else []
    return {"archivo": ruta.name, "lineas": lineas[-n:][::-1]}


@router.post("/api/simulator", summary="[deprecated] usa /api/simulator/start|stop|burst")
async def simulador_v1(ctrl: ControlSimuladorLegacy, ctx: Ctx):
    if ctrl.accion == "start":
        r = await ctx.simulator.start()
    elif ctrl.accion == "stop":
        r = await ctx.simulator.stop()
    elif ctrl.accion == "speed":
        if ctrl.intervalo is None:
            raise HTTPException(status_code=422, detail="intervalo requerido")
        r = await ctx.simulator.start(ctrl.intervalo) if ctx.simulator.activo else (setattr(ctx.simulator, "intervalo", ctrl.intervalo) or ctx.simulator.status())
    else:
        r = await ctx.simulator.rafaga(ctrl.cantidad or 20)
    m = ctx.monitor.metricas()
    return {"ok": True, "simulador": {"activo": r["activo"], "intervalo_s": r["intervalo_s"]}, "total_predicciones": m["total_predicciones"],
            "deprecated": True, "usa": "/api/simulator/start|stop|burst"}
