"""
URLs públicas de la API y archivo dashboard/api-base.js.

El dashboard puede abrirse fuera de la API (visor de archivos, file://, otro servidor estático).
Para que aun así encuentre la API, al arrancar se escribe `dashboard/api-base.js` con las URLs por
las que se puede llegar a este proceso:

    PUBLIC_URL             (env, separadas por coma) tiene prioridad
    https://{port}-{E2B_SANDBOX_ID}.e2b.app   si se ejecuta dentro de un sandbox E2B / Arena
    http://localhost:{port} · http://127.0.0.1:{port}

El puerto se toma de PORT / UVICORN_PORT (por defecto 8000).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("api.publico")


def puerto_publico() -> int:
    for var in ("PUBLIC_PORT", "PORT", "UVICORN_PORT"):
        valor = os.environ.get(var)
        if valor and valor.isdigit():
            return int(valor)
    return 8000


def urls_publicas() -> list[str]:
    puerto = puerto_publico()
    urls: list[str] = []
    for u in os.environ.get("PUBLIC_URL", "").split(","):
        u = u.strip().rstrip("/")
        if u:
            urls.append(u)
    sandbox = os.environ.get("E2B_SANDBOX_ID")
    if sandbox:
        urls.append(f"https://{puerto}-{sandbox}.e2b.app")
    urls += [f"http://localhost:{puerto}", f"http://127.0.0.1:{puerto}"]
    vistos: list[str] = []
    for u in urls:
        if u not in vistos:
            vistos.append(u)
    return vistos


def escribir_api_base(dashboard_dir: Path) -> Path:
    """Escribe dashboard/api-base.js (lo lee dashboard/apibase.js). Se sobrescribe en cada arranque."""
    urls = urls_publicas()
    ruta = dashboard_dir / "api-base.js"
    contenido = (
        "// Generado automáticamente por la API al arrancar (api/core/publico.py) — no editar a mano.\n"
        "// URLs por las que el dashboard puede llegar a la API cuando se abre fuera de ella.\n"
        f"window.MLOPS_API_BASES = {json.dumps(urls)};\n"
        f"window.MLOPS_API_GENERADO = {json.dumps(datetime.now(timezone.utc).isoformat(timespec='seconds'))};\n"
    )
    try:
        if not ruta.exists() or ruta.read_text(encoding="utf-8") != contenido:
            ruta.write_text(contenido, encoding="utf-8")
        log.info("dashboard/api-base.js → %s", ", ".join(urls))
    except OSError as exc:  # sistema de archivos de solo lectura, etc.
        log.warning("No se pudo escribir %s: %s", ruta, exc)
    return ruta
