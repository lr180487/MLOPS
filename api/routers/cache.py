"""GET /api/cache/stats, GET|PUT|DELETE /api/cache/{key}, DELETE /api/cache"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..deps import Ctx
from ..schemas import CacheValor

router = APIRouter(prefix="/cache", tags=["cache"])


@router.get("/stats")
async def cache_stats(ctx: Ctx, claves: int = Query(20, ge=0, le=500)):
    """Estadísticas de ambos niveles (hits, misses, hit ratio, evictions) y muestra de claves."""
    muestra = ctx.cache.keys(limit=claves)
    return {**ctx.cache.stats(), "muestra_claves": muestra,
            "muestra": [{"key": k, "ttl_s": ctx.cache.l1.ttl(k)} for k in muestra]}


@router.delete("")
@router.delete("/", include_in_schema=False)
async def cache_clear(ctx: Ctx, prefix: str | None = Query(None, description="Solo claves con este prefijo (p. ej. pred, metrics)")):
    """Vacía la caché (L1 y L2)."""
    return {"ok": True, **(await ctx.cache.clear(prefix))}


@router.get("/{key:path}")
async def cache_get(key: str, ctx: Ctx):
    ok, valor, nivel = await ctx.cache.get(key)
    if not ok:
        raise HTTPException(status_code=404, detail="clave no encontrada o expirada")
    return {"key": key, "value": valor, "nivel": nivel, "ttl_s": ctx.cache.ttl(key)}


@router.put("/{key:path}")
async def cache_put(key: str, body: CacheValor, ctx: Ctx):
    return {"ok": True, **(await ctx.cache.set(key, body.value, body.ttl))}


@router.delete("/{key:path}")
async def cache_delete(key: str, ctx: Ctx):
    r = await ctx.cache.delete(key)
    if not r["eliminada"]:
        raise HTTPException(status_code=404, detail="clave no encontrada")
    return {"ok": True, **r}
