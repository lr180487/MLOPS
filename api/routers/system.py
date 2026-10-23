
"""GET /api/system/info y /api/system/logs."""

from __future__ import annotations

import os
import platform
import sys
from typing import Literal

import psutil
from fastapi import APIRouter, Query

from ..core.monitor import ahora_iso
from ..core.publico import urls_publicas
from ..deps import Ctx

router = APIRouter(prefix="/system", tags=["system"])


def _version(modulo: str) -> str | None:
    """Obtiene la versión de un paquete instalado."""
    try:
        paquete = __import__(modulo)
        return getattr(paquete, "__version__", None)
    except Exception:  # noqa: BLE001
        return None


def _memoria_rss_mb() -> float:
    """Memoria RSS actual del proceso, expresada en MiB."""
    proceso = psutil.Process(os.getpid())
    return round(proceso.memory_info().rss / (1024 * 1024), 1)


@router.get("/info")
async def system_info(ctx: Ctx):
    """Información del proceso, versiones, backends y configuración pública."""
    db = ctx.db.health()
    cache = ctx.cache.stats()

    return {
        "app": {
            "nombre": ctx.settings.app_name,
            "version": ctx.settings.app_version,
            "uptime_s": ctx.uptime_s,
            "timestamp": ahora_iso(),
            "urls_publicas": urls_publicas(),
            "pid": os.getpid(),
            "python": sys.version.split()[0],
            "plataforma": platform.platform(),
            "memoria_rss_mb": _memoria_rss_mb(),
        },
        "versiones": {
            modulo: _version(modulo)
            for modulo in [
                "fastapi",
                "uvicorn",
                "pydantic",
                "sklearn",
                "pandas",
                "numpy",
                "httpx",
                "psycopg",
            ]
        },
        "backends": {
            "database": {
                "backend": db.get("backend"),
                "fallback": db.get("fallback"),
                "fallback_reason": db.get("fallback_reason"),
                # No exponer el DSN: puede contener usuario y contraseña.
                "dsn_configurado": bool(db.get("dsn")),
            },
            "cache": {
                "l1": "lru-local",
                "l2": (
                    "upstash-redis"
                    if ctx.cache.l2.configurado
                    else None
                ),
                "upstash_activa": ctx.cache.l2.disponible,
                "hit_ratio_global": cache["hit_ratio_global"],
                "items_local": cache["niveles"]["local"]["items"],
            },
            "modelo": {
                "version": ctx.predictor.version,
                "hash": ctx.predictor.hash,
                "recargas": ctx.predictor.recargas,
            },
            "simulador": ctx.simulator.status(),
            "sse": ctx.bus.stats(),
        },
        "config": ctx.settings.resumen_publico(),
        "rutas": {
            "dashboard": "/index.html",
            "resultados": "/resultados.html",
            "docs": "/docs",
            "openapi": "/openapi.json",
        },
    }


@router.get("/logs")
async def system_logs(
    ctx: Ctx,
    n: int = Query(40, ge=1, le=500),
    archivo: Literal["api", "ejecucion"] = "api",
):
    """Devuelve las últimas líneas de un archivo de log permitido."""
    ruta = ctx.settings.logs_dir / f"{archivo}.log"

    if not ruta.exists():
        return {"archivo": ruta.name, "lineas": []}

    lineas = ruta.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()

    return {
        "archivo": ruta.name,
        "lineas": lineas[-n:][::-1],
    }
