"""Páginas del dashboard (HTML/JS estáticos) y redirecciones.

Los proxies de vista previa (y algunos navegadores) cachean los archivos ``.js`` por extensión aunque
se envíe ``Cache-Control: no-cache``, con lo que el usuario puede quedarse con scripts antiguos tras un
cambio. Por eso:

* los HTML se sirven con las referencias a los scripts locales **versionadas** (``script.js?v=<mtime>``):
  cada edición de un script cambia la URL y obliga a descargarlo de nuevo;
* todos los recursos del dashboard se envían con ``no-store`` (navegador y CDN).

Los HTML del disco no se modifican: siguen siendo válidos abiertos como archivos estáticos.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ..core.publico import escribir_api_base
from ..deps import Ctx

router = APIRouter(include_in_schema=False)

PAGINAS = {"index": "index.html", "resultados": "resultados.html", "analisis": "analisis.html"}
SCRIPTS = {"script.js", "resultados.js", "analisis.js", "loader.js", "sonidos.js", "animaciones.js", "apibase.js", "api-base.js"}

SIN_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "CDN-Cache-Control": "no-store",
    "Surrogate-Control": "no-store",
}
_RE_SCRIPT_LOCAL = re.compile(r'(src=")((?:script|resultados|analisis|loader|sonidos|animaciones|apibase|api-base)\.js)(")')


def _version(ruta: Path) -> str:
    try:
        st = ruta.stat()
        return f"{int(st.st_mtime)}-{st.st_size}"
    except OSError:
        return "0"


def _html(ctx: Ctx, nombre: str) -> HTMLResponse:
    """HTML con los scripts locales versionados según su fecha de modificación y tamaño."""
    carpeta = ctx.settings.dashboard_dir
    ruta = carpeta / nombre
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Página no encontrada")
    html = ruta.read_text(encoding="utf-8")
    html = _RE_SCRIPT_LOCAL.sub(lambda m: f'{m.group(1)}{m.group(2)}?v={_version(carpeta / m.group(2))}{m.group(3)}', html)
    return HTMLResponse(html, headers=SIN_CACHE)


def _js(ctx: Ctx, nombre: str) -> FileResponse:
    ruta = ctx.settings.dashboard_dir / nombre
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Recurso no encontrado")
    return FileResponse(ruta, media_type="application/javascript", headers=SIN_CACHE)


@router.get("/")
@router.get("/dashboard")
@router.get("/dashboard/")
async def raiz():
    """La raíz y /dashboard redirigen al dashboard (index.html)."""
    return RedirectResponse(url="/index.html", status_code=307)


@router.get("/resultados")
@router.get("/resultados/")
async def resultados_redirect():
    return RedirectResponse(url="/resultados.html", status_code=307)


@router.get("/analisis")
@router.get("/analisis/")
async def analisis_redirect():
    return RedirectResponse(url="/analisis.html", status_code=307)


@router.get("/index.html")
async def index(ctx: Ctx):
    return _html(ctx, "index.html")


@router.get("/resultados.html")
async def resultados(ctx: Ctx):
    return _html(ctx, "resultados.html")


@router.get("/analisis.html")
async def analisis_html(ctx: Ctx):
    return _html(ctx, "analisis.html")


@router.get("/script.js")
async def script_js(ctx: Ctx):
    return _js(ctx, "script.js")


@router.get("/resultados.js")
async def resultados_js(ctx: Ctx):
    return _js(ctx, "resultados.js")


@router.get("/analisis.js")
async def analisis_js(ctx: Ctx):
    return _js(ctx, "analisis.js")


@router.get("/loader.js")
async def loader_js(ctx: Ctx):
    """Pantalla de arranque del dashboard (logo con anillo giratorio durante 5 s)."""
    return _js(ctx, "loader.js")


@router.get("/sonidos.js")
async def sonidos_js(ctx: Ctx):
    """Sonidos del dashboard sincronizados con cada acción, con reverberación configurable (Web Audio)."""
    return _js(ctx, "sonidos.js")


@router.get("/animaciones.js")
async def animaciones_js(ctx: Ctx):
    """Animaciones de las gráficas e indicadores del dashboard (plugins de Chart.js, contadores, transiciones de canvas)."""
    return _js(ctx, "animaciones.js")


@router.get("/apibase.js")
async def apibase_js(ctx: Ctx):
    """Localizador de la API para cuando el dashboard se abre fuera de ella."""
    return _js(ctx, "apibase.js")


@router.get("/api-base.js")
async def api_base_js(ctx: Ctx):
    """URLs públicas de esta API (archivo generado al arrancar por api/core/publico.py)."""
    if not (ctx.settings.dashboard_dir / "api-base.js").exists():
        escribir_api_base(ctx.settings.dashboard_dir)
    return _js(ctx, "api-base.js")
