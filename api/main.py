"""
api/main.py
-----------
API REST modular (FastAPI) de la Práctica MLOps — v2.

    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

Arquitectura
------------
    Dashboard (HTML + Tailwind + JS)  ──REST / SSE / Swagger──▶  FastAPI
        ├── Predictor  ─┐
        ├── Metrics    ─┼──▶  Cache Manager  (L1 LRU local  →  L2 Upstash Redis)
        └── Feedback   ─┘             │
                                      ▼
                              Persistencia: PostgreSQL  ── falla ──▶  SQLite
                                      │
                                      └──▶ SSE ──▶ Dashboard

Árbol de rutas (/api): health, predictions, feedback, metrics, stream, cache,
simulator, model, system, analisis. Los endpoints de la v1
(/health, /predict, /feedback, /api/info, /api/simulator …) se mantienen como
alias *deprecated* en `routers/legacy.py`.
"""

from __future__ import annotations

import asyncio

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import Settings, settings
from .core.cache import CacheManager
from .core.database import Database
from .core.events import EventBus
from .core.model import Predictor
from .core.monitor import Monitor
from .core.export import Exportador
from .core.publico import escribir_api_base, urls_publicas
from .core.service import PredictionService
from .core.simulator import Simulator
from .deps import AppContext
from .routers import analisis, cache, data, feedback, health, legacy, metrics, model, pages, predictions, simulator, stream, system

settings.logs_dir.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.FileHandler(settings.logs_dir / "api.log", encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("api")


# --------------------------------------------------------------------------- #
# Construcción del contexto (todos los componentes)
# --------------------------------------------------------------------------- #
def construir_contexto(s: Settings) -> AppContext:
    db = Database(s).connect()
    cache_mgr = CacheManager(s)
    bus = EventBus()
    predictor = Predictor(s).load()
    monitor = Monitor(s, predictor.medias(), predictor.desviaciones())
    service = PredictionService(s, predictor, monitor, db, cache_mgr, bus)
    simulator = Simulator(s, predictor, service)
    return AppContext(settings=s, db=db, cache=cache_mgr, bus=bus, predictor=predictor, monitor=monitor, service=service, simulator=simulator)


# --------------------------------------------------------------------------- #
# Ciclo de vida
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    ctx = construir_contexto(settings)
    app.state.ctx = ctx

    # 1) rehidratar el monitor con el historial persistido; si no hay, calentar con el simulador
    n = await ctx.service.rehidratar_monitor(ctx.settings.history_max)
    if n:
        log.info("Monitor rehidratado con %d predicciones desde %s", n, ctx.db.backend)
    else:
        await ctx.simulator.calentar(ctx.settings.warmup_events)
        log.info("Monitor calentado con %d eventos sintéticos", ctx.settings.warmup_events)

    # 2) simulador de tráfico
    if ctx.settings.simulator_enabled:
        await ctx.simulator.start()

    # 3) dashboard/api-base.js (URLs públicas de esta API) y copias estáticas de las exportaciones
    escribir_api_base(ctx.settings.dashboard_dir)
    if ctx.settings.static_exports:
        try:
            await asyncio.to_thread(Exportador(ctx).generar_estaticas)
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudieron generar las exportaciones estáticas: %s", exc)

    # 4) análisis del dataset (regresión, clasificación, clustering, anomalías) precalculados en segundo plano
    tarea_analisis = asyncio.create_task(analisis.precalcular(ctx)) if ctx.settings.analysis_precompute else None

    log.info("API lista · db=%s cache=%s", ctx.db.backend, "l1+upstash" if ctx.cache.l2.configurado else "l1")
    yield

    if tarea_analisis and not tarea_analisis.done():
        tarea_analisis.cancel()

    await ctx.simulator.stop()
    await ctx.cache.close()
    ctx.db.close()


# --------------------------------------------------------------------------- #
# Aplicación
# --------------------------------------------------------------------------- #
TAGS = [
    {"name": "health", "description": "Estado del servicio y de cada componente."},
    {"name": "predictions", "description": "Predicciones (caché → monitor → persistencia → SSE)."},
    {"name": "feedback", "description": "Etiquetas reales que cierran el ciclo de monitoreo."},
    {"name": "metrics", "description": "Métricas de entrenamiento y de producción."},
    {"name": "stream", "description": "Server-Sent Events en tiempo real."},
    {"name": "cache", "description": "Cache Manager: LRU local + Upstash Redis."},
    {"name": "simulator", "description": "Simulador de tráfico de producción."},
    {"name": "model", "description": "Información, métricas y recarga del modelo."},
    {"name": "system", "description": "Información del sistema y logs."},
    {"name": "datos", "description": "Complementarios: resultado.json, muestra del CSV, descargas."},
    {"name": "analisis", "description": "Análisis del dataset con varios tipos de algoritmos: regresión, clasificación, clustering, anomalías y series temporales."},
    {"name": "legacy (deprecated)", "description": "Alias de la v1. Usa las rutas /api/… equivalentes."},
]

app = FastAPI(
    title=settings.app_name,
    description=("API modular de la Práctica MLOps: predicción SI/NO, métricas en vivo (SSE), Cache Manager de dos niveles, "
                 "persistencia PostgreSQL con fallback a SQLite y exportación de la base de datos (CSV/XLSX/PDF/SQLite)."),
    version=settings.app_version,
    lifespan=lifespan,
    openapi_tags=TAGS,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Cabeceras estándar de obsolescencia para los alias v1 (RFC 8594 / draft-ietf-httpapi-deprecation-header)
LEGACY_SUCESOR = {
    "/health": "/api/health", "/predict": "/api/predictions", "/predict/batch": "/api/predictions/batch",
    "/feedback": "/api/feedback", "/api/info": "/api/model/info", "/api/logs": "/api/system/logs",
    "/api/simulator": "/api/simulator/start",
}


class DeprecationHeadersMiddleware:
    """Middleware ASGI puro (no interfiere con el streaming SSE) que añade las cabeceras."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        sucesor = LEGACY_SUCESOR.get(scope.get("path", ""))
        if not sucesor or (scope["path"] == "/feedback" and scope.get("method") == "GET"):
            return await self.app(scope, receive, send)

        async def send_con_cabeceras(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [(b"deprecation", b"true"), (b"link", f'<{sucesor}>; rel="successor-version"'.encode()),
                            (b"x-deprecated-alias", f"usa {sucesor}".encode())]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_con_cabeceras)


app.add_middleware(DeprecationHeadersMiddleware)

# Árbol /api/...
for r in (health, predictions, feedback, metrics, stream, cache, simulator, model, system, analisis):
    app.include_router(r.router, prefix="/api")
# Complementarios, páginas y alias v1
app.include_router(data.router)
app.include_router(pages.router)
app.include_router(legacy.router)

# Estáticos: respaldo local de Chart.js, imágenes del notebook y compatibilidad /static
app.mount("/vendor", StaticFiles(directory=settings.dashboard_dir / "vendor"), name="vendor")
app.mount("/output", StaticFiles(directory=settings.base_dir / "output"), name="output")
app.mount("/static", StaticFiles(directory=settings.dashboard_dir), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
