"""
/api/analisis — Analiza el dataset con varios tipos de algoritmos
(regresión, clasificación, clustering, anomalías y series temporales).

Los cálculos corren en un hilo (no bloquean el SSE) y se cachean en el Cache
Manager con una clave que incluye los parámetros y la huella del dataset, de
modo que repetir un análisis es inmediato y cambiar los datos invalida todo.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging

from fastapi import APIRouter, HTTPException, Query

from ..core.analisis import NUMERICAS, Analizador, catalogo_publico
from ..deps import AppContext, Ctx

router = APIRouter(prefix="/analisis", tags=["analisis"])
log = logging.getLogger("api.analisis")

TTL = 6 * 3600


def _analizador(ctx: AppContext) -> Analizador:
    """Un Analizador por dataset cargado (se reutiliza mientras el Predictor no recargue los datos)."""
    cache = getattr(ctx, "_analizador", None)
    if cache is None or cache[0] is not ctx.predictor.dataset:
        if ctx.predictor.dataset is None:
            raise HTTPException(status_code=503, detail="No hay dataset cargado (data/datos.csv).")
        cache = (ctx.predictor.dataset, Analizador(ctx.predictor.dataset))
        ctx._analizador = cache  # type: ignore[attr-defined]
    return cache[1]


def _clave(an: Analizador, tipo: str, **params) -> str:
    firma = hashlib.md5(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return f"analisis:{an.huella}:{tipo}:{firma}"


async def _calcular(ctx: AppContext, tipo: str, fn, **params) -> dict:
    an = _analizador(ctx)
    clave = _clave(an, tipo, **params)
    try:
        valor, hit, _ = await ctx.cache.get_or_compute(clave, lambda: asyncio.to_thread(fn, an), ttl=TTL)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**valor, "cache": bool(hit)}


# --------------------------------------------------------------------------- #
@router.get("/catalogo", summary="Tipos de análisis, algoritmos, métricas y opciones")
async def catalogo(ctx: Ctx):
    return catalogo_publico(ctx.predictor.dataset)


@router.get("/regresion", summary="Regresión: predecir una variable numérica (lineal, Ridge, Random Forest, Gradient Boosting)")
async def regresion(ctx: Ctx, objetivo: str = Query("temperatura", description=f"Variable a predecir: {', '.join(NUMERICAS)}"),
                    test_size: float = Query(0.25, ge=0.1, le=0.5), cv: int = Query(5, ge=3, le=10)):
    return await _calcular(ctx, "regresion", lambda an: an.regresion(objetivo, test_size, cv), objetivo=objetivo, test_size=test_size, cv=cv)


@router.get("/clasificacion", summary="Clasificación: SI/NO o cultivo (logística, árbol, Random Forest, SVM, Gradient Boosting)")
async def clasificacion(ctx: Ctx, objetivo: str = Query("resultado", pattern="^(resultado|cultivo)$"),
                        test_size: float = Query(0.25, ge=0.1, le=0.5), cv: int = Query(5, ge=3, le=10),
                        umbral: float | None = Query(None, ge=0.05, le=0.95, description="Solo binario: umbral sobre P(SI); vacío = decisión nativa")):
    return await _calcular(ctx, "clasificacion", lambda an: an.clasificacion(objetivo, test_size, cv, umbral),
                           objetivo=objetivo, test_size=test_size, cv=cv, umbral=umbral)


@router.get("/clustering", summary="Clustering: K-Means, DBSCAN y jerárquico sobre las variables climáticas")
async def clustering(ctx: Ctx, k: int = Query(3, ge=2, le=10), eps: float = Query(1.0, ge=0.1, le=5.0), min_samples: int = Query(10, ge=2, le=100),
                     n_clusters: int = Query(3, ge=2, le=10), enlace: str = Query("ward", pattern="^(ward|average|complete|single)$"),
                     variables: str | None = Query(None, description="Lista separada por comas; vacío = las cinco")):
    vars_ = [v.strip() for v in variables.split(",") if v.strip()] if variables else None
    if vars_ is not None and (len(vars_) < 2 or any(v not in NUMERICAS for v in vars_)):
        raise HTTPException(status_code=422, detail=f"variables debe incluir al menos dos de: {', '.join(NUMERICAS)}")
    return await _calcular(ctx, "clustering", lambda an: an.clustering(k, eps, min_samples, n_clusters, enlace, vars_),
                           k=k, eps=eps, min_samples=min_samples, n_clusters=n_clusters, enlace=enlace, variables=vars_)


@router.get("/anomalias", summary="Anomalías: Isolation Forest, LOF y z-score (con anomalías inyectadas opcionales)")
async def anomalias(ctx: Ctx, contaminacion: float = Query(0.05, ge=0.005, le=0.3), umbral_z: float = Query(3.0, ge=1.5, le=6.0),
                    vecinos: int = Query(20, ge=5, le=100), inyectar: int = Query(0, ge=0, le=200)):
    return await _calcular(ctx, "anomalias", lambda an: an.anomalias(contaminacion, umbral_z, vecinos, inyectar),
                           contaminacion=contaminacion, umbral_z=umbral_z, vecinos=vecinos, inyectar=inyectar)


@router.get("/series", summary="Series temporales: media móvil, suavizado exponencial, Holt, ARIMA y regresión temporal")
async def series(ctx: Ctx, fuente: str = Query("dataset", pattern="^(dataset|predicciones|simulada)$"),
                 variable: str = Query("temperatura"), bloque: int = Query(10, ge=1, le=100),
                 medida: str = Query("conteo", pattern="^(conteo|tasa_si|probabilidad|latencia)$"),
                 intervalo: str = Query("minuto", pattern="^(minuto|10min|hora|dia)$"),
                 n: int = Query(120, ge=24, le=1000), tendencia: float = Query(1.0, ge=-3, le=3), amplitud: float = Query(1.0, ge=0, le=3),
                 ruido: float = Query(0.5, ge=0, le=3),
                 test_frac: float = Query(0.2, ge=0.1, le=0.5), ventana: int = Query(5, ge=1, le=50), alpha: float = Query(0.3, ge=0.01, le=0.99),
                 p: int = Query(1, ge=0, le=5), d: int = Query(1, ge=0, le=2), q: int = Query(1, ge=0, le=5),
                 lags: int = Query(3, ge=1, le=24), periodo: int = Query(0, ge=0, le=100), futuro: int = Query(0, ge=0, le=100)):
    """`fuente=dataset`: una variable del CSV en orden de registro (promediada por bloques) · `predicciones`: historial real del
    servicio (conteo, tasa de SI, probabilidad media o latencia por intervalo) · `simulada`: serie con tendencia + estacionalidad
    calibrada con el dataset. `periodo` activa la estacionalidad en la regresión temporal (0 = sin estacionalidad)."""
    if variable not in NUMERICAS:
        raise HTTPException(status_code=422, detail=f"variable debe ser una de: {', '.join(NUMERICAS)}")
    an = _analizador(ctx)
    params = dict(fuente=fuente, variable=variable, bloque=bloque, medida=medida, intervalo=intervalo, n=n, tendencia=tendencia, amplitud=amplitud, ruido=ruido,
                  test_frac=test_frac, ventana=ventana, alpha=alpha, p=p, d=d, q=q, lags=lags, periodo=periodo, futuro=futuro)
    if fuente == "predicciones":
        filas = await asyncio.to_thread(ctx.db.execute, "SELECT ts, prediccion, probabilidad_si, latencia_ms FROM predictions ORDER BY ts", (), "all")
        filas = [dict(f) for f in filas]
        if not filas:
            raise HTTPException(status_code=422, detail="Todavía no hay predicciones registradas: usa el dashboard o el simulador para generar actividad.")
        ultimo = filas[-1]["ts"]
        params["_ultimo"] = ultimo; params["_n"] = len(filas)   # la caché caduca sola cuando llegan predicciones nuevas

        def fn(an: Analizador) -> dict:
            s = Analizador.serie_predicciones(filas, medida, intervalo)
            return an.serie(s["valores"], s["etiquetas"], test_frac, ventana, alpha, (p, d, q), lags, periodo, futuro or None, meta=s)
        ttl = 60
    else:
        def fn(an: Analizador) -> dict:
            s = an.serie_dataset(variable, bloque) if fuente == "dataset" else an.serie_simulada(variable, n, tendencia, amplitud, periodo or 12, ruido)
            per = periodo if fuente == "dataset" else (periodo or 12)
            return an.serie(s["valores"], s["etiquetas"], test_frac, ventana, alpha, (p, d, q), lags, per, futuro or None, meta=s)
        ttl = TTL
    clave = _clave(an, "series", **params)
    try:
        valor, hit, _ = await ctx.cache.get_or_compute(clave, lambda: asyncio.to_thread(fn, an), ttl=ttl)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**valor, "cache": bool(hit)}


# --------------------------------------------------------------------------- #
async def precalcular(ctx: AppContext) -> None:
    """Calienta la caché con los análisis por defecto (en segundo plano, uno tras otro)."""
    try:
        an = _analizador(ctx)
    except HTTPException:
        return
    tareas = [
        ("regresion", lambda: an.regresion("temperatura", 0.25, 5), dict(objetivo="temperatura", test_size=0.25, cv=5)),
        ("clasificacion", lambda: an.clasificacion("resultado", 0.25, 5, None), dict(objetivo="resultado", test_size=0.25, cv=5, umbral=None)),
        ("clustering", lambda: an.clustering(3, 1.0, 10, 3, "ward", None), dict(k=3, eps=1.0, min_samples=10, n_clusters=3, enlace="ward", variables=None)),
        ("anomalias", lambda: an.anomalias(0.05, 3.0, 20, 0), dict(contaminacion=0.05, umbral_z=3.0, vecinos=20, inyectar=0)),
    ]
    for tipo, fn, params in tareas:
        clave = _clave(an, tipo, **params)
        ok, _, _ = await ctx.cache.get(clave)
        if ok:
            continue
        try:
            valor = await asyncio.to_thread(fn)
            await ctx.cache.set(clave, valor, ttl=TTL)
        except Exception as exc:  # noqa: BLE001
            log.warning("Precálculo de %s falló: %s", tipo, exc)
    log.info("Análisis por defecto precalculados (%d filas)", len(an.df))
