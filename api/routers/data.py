"""Endpoints complementarios (no sustituidos por el árbol nuevo): datos, heatmap, eventos, descargas."""

from __future__ import annotations

import asyncio
import logging
import json
import subprocess
import sys

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from ..core.export import FORMATOS, Exportador
from ..deps import Ctx

router = APIRouter(tags=["datos"])
log = logging.getLogger("api.data")


def _resultado(ctx) -> dict:
    if not ctx.settings.result_path.exists():
        raise HTTPException(status_code=404, detail="No existe output/resultado.json. Ejecuta procesar_datos.py.")
    return json.loads(ctx.settings.result_path.read_text(encoding="utf-8"))


@router.get("/api/data/summary")
async def data_summary(ctx: Ctx):
    """Contenido de output/resultado.json (cacheado 30 s)."""
    valor, _, _ = await ctx.cache.get_or_compute("data:summary", lambda: _resultado(ctx), ttl=30)
    return valor


@router.get("/api/data/sample")
async def data_sample(ctx: Ctx, n: int = Query(50, ge=1, le=500)):
    return {"filas": ctx.predictor.dataset.head(n).to_dict(orient="records")}


@router.post("/api/data/reprocess")
async def reprocesar_datos(ctx: Ctx):
    """Vuelve a ejecutar procesar_datos.py y devuelve el nuevo resultado.json."""
    proc = await asyncio.to_thread(subprocess.run, [sys.executable, str(ctx.settings.base_dir / "procesar_datos.py")],
                                   capture_output=True, text=True, cwd=str(ctx.settings.base_dir), timeout=120)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=f"procesar_datos.py falló: {proc.stderr[-800:]}")
    await ctx.cache.delete("data:summary")
    return {"ok": True, "resultado": _resultado(ctx)}


@router.get("/api/heatmap/probability", tags=["model"])
async def heatmap_probability(ctx: Ctx, cultivo: str = Query("cafe"), x: str = Query("temperatura"), y: str = Query("humedad"),
                              resolucion: int = Query(20, ge=5, le=40)):
    """Superficie P(SI) sobre una rejilla (x, y); el resto de variables se fijan en su media. Cacheada."""
    clave = f"heatmap:{ctx.predictor.hash}:{cultivo.strip().lower()}:{x}:{y}:{resolucion}"
    try:
        valor, _, _ = await ctx.cache.get_or_compute(clave, lambda: ctx.predictor.heatmap(cultivo, x, y, resolucion), ttl=3600)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return valor


@router.get("/api/events", tags=["metrics"])
async def events(ctx: Ctx, n: int = Query(30, ge=1, le=500)):
    """Últimos eventos en memoria (más recientes primero)."""
    return {"eventos": ctx.monitor.ultimos(n)}


@router.get("/download/resultado.json")
@router.head("/download/resultado.json", include_in_schema=False)
async def descargar_resultado(ctx: Ctx):
    """Descarga directa de output/resultado.json (Content-Disposition: attachment)."""
    if not ctx.settings.result_path.exists():
        raise HTTPException(status_code=404, detail="No existe output/resultado.json. Ejecuta procesar_datos.py.")
    return FileResponse(ctx.settings.result_path, media_type="application/json", filename="resultado.json", headers={"Cache-Control": "no-cache"})


@router.get("/api/data/exports", summary="Catálogo de tablas exportables (CSV / XLSX / PDF / JSON)")
async def exports(ctx: Ctx):
    """Tablas de la base de datos disponibles para descarga, con filas, columnas y URLs."""
    return await asyncio.to_thread(Exportador(ctx).catalogo)


@router.post("/api/data/exports/static", summary="Regenera las copias estáticas en output/exportaciones/")
async def exports_static(ctx: Ctx):
    """Escribe todas las exportaciones (CSV/XLSX/PDF/JSON por tabla + base_datos.*) en `output/exportaciones/`
    junto con `index.json`. Sirven de respaldo cuando el dashboard se abre sin la API (visor de archivos, file://)."""
    indice = await asyncio.to_thread(Exportador(ctx).generar_estaticas)
    return {"ok": True, **indice}


@router.get("/download/{tabla}.{formato}", summary="Descarga una tabla o toda la base de datos")
@router.head("/download/{tabla}.{formato}", include_in_schema=False)
async def descargar_tabla(tabla: str, formato: str, request: Request, ctx: Ctx,
                          limite: int | None = Query(None, ge=1, le=5000, description="Filas máximas por tabla en PDF")):
    """
    `tabla` ∈ datos · predicciones · feedback · resultado · base_datos ·
    `formato` ∈ csv · xlsx · pdf · json (base_datos también admite zip y sqlite; su csv es un ZIP de CSV).
    Los archivos se generan en memoria en el momento (Content-Disposition: attachment).
    """
    exportador = Exportador(ctx)
    formato = formato.lower()
    if tabla != "base_datos" and tabla not in exportador.tablas:
        raise HTTPException(status_code=404, detail=f"Tabla desconocida: {tabla}. Disponibles: {', '.join(exportador.tablas)}, base_datos")
    if formato not in ("csv", "xlsx", "pdf", "json", "zip", "sqlite") or (formato in ("zip", "sqlite") and tabla != "base_datos"):
        raise HTTPException(status_code=400, detail="Formato no soportado; usa csv, xlsx, pdf o json (base_datos admite además zip y sqlite)")
    if request.method == "HEAD":   # sin generar el archivo
        media, ext = FORMATOS["zip" if (tabla == "base_datos" and formato == "csv") else formato]
        return Response(status_code=200, media_type=media, headers={"Content-Disposition": f'attachment; filename="{tabla}.{ext}"'})
    try:
        contenido, media, nombre = await asyncio.to_thread(exportador.exportar, tabla, formato, limite)
    except Exception as e:
        log.exception("error exportando %s.%s", tabla, formato)
        raise HTTPException(status_code=500, detail=f"No se pudo generar {tabla}.{formato}: {e}") from e
    return Response(content=contenido, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"', "Cache-Control": "no-cache", "Content-Length": str(len(contenido))})
