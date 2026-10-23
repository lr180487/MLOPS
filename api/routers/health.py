"""GET /api/health, /api/health/database, /api/health/cache"""

from __future__ import annotations

from fastapi import APIRouter

from ..core.monitor import ahora_iso
from ..deps import Ctx

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
@router.get("/", include_in_schema=False)
async def health(ctx: Ctx):
    """Estado global del servicio y de cada componente."""
    db = ctx.db.health()
    cache = await ctx.cache.health()
    componentes = {
        "modelo": {"status": "ok" if ctx.predictor.modelo is not None else "error", "version": ctx.predictor.version, "hash": ctx.predictor.hash},
        "database": {"status": db.get("status"), "backend": db.get("backend"), "fallback": db.get("fallback"), "latencia_ms": db.get("latencia_ms")},
        "cache": {"status": cache["status"], "upstash": cache["niveles"]["upstash"].get("activa"), "items_local": cache["niveles"]["local"]["items"]},
        "simulador": {"status": "ok", "activo": ctx.simulator.activo},
        "sse": {"status": "ok", "suscriptores": ctx.bus.suscriptores},
    }
    estados = {c["status"] for c in componentes.values()}
    status = "ok" if estados <= {"ok"} else ("degraded" if "error" not in estados or componentes["modelo"]["status"] == "ok" else "error")
    return {"status": status, "version": ctx.settings.app_version, "uptime_s": ctx.uptime_s, "timestamp": ahora_iso(),
            "modelo_cargado": ctx.predictor.modelo is not None, "componentes": componentes}


@router.get("/database")
async def health_database(ctx: Ctx):
    """Backend activo (postgresql | sqlite), latencia, conteo de tablas y motivo del fallback."""
    return ctx.db.health()


@router.get("/cache")
async def health_cache(ctx: Ctx):
    """Estado de los dos niveles de caché (LRU local y Upstash Redis)."""
    return {**(await ctx.cache.health()), "stats": ctx.cache.stats()}

