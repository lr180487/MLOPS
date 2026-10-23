#!/usr/bin/env python3
"""
Exporta la base de datos del proyecto a output/exportaciones/ SIN necesidad de la API en marcha.

    python exportar_base_datos.py                 # todas las tablas en CSV, XLSX, PDF, JSON + base_datos.*
    python exportar_base_datos.py --destino /tmp/x
    python exportar_base_datos.py --solo predicciones.xlsx base_datos.pdf

Usa los mismos componentes que la API (api/core/export.py): PostgreSQL si hay DATABASE_URL,
si no SQLite (storage/mlops.sqlite3). Los archivos quedan en el workspace, así que se pueden
descargar desde el visor de archivos aunque el servidor esté apagado.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("SIMULATOR_ENABLED", "0")
os.environ.setdefault("STATIC_EXPORTS", "0")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.config import settings                 # noqa: E402
from api.core.export import Exportador          # noqa: E402
from api.main import construir_contexto         # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Exporta la base de datos del proyecto (CSV / XLSX / PDF / JSON / SQLite).")
    parser.add_argument("--destino", type=Path, default=settings.base_dir / "output" / "exportaciones")
    parser.add_argument("--solo", nargs="*", metavar="TABLA.FORMATO", help="exporta solo estos archivos, p. ej. predicciones.xlsx base_datos.pdf")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

    ctx = construir_contexto(settings)
    try:
        exp = Exportador(ctx)
        args.destino.mkdir(parents=True, exist_ok=True)
        if args.solo:
            for nombre in args.solo:
                tabla, _, formato = nombre.rpartition(".")
                contenido, _, archivo = exp.exportar(tabla, formato)
                (args.destino / archivo).write_bytes(contenido)
                print(f"✓ {args.destino / archivo}  ({len(contenido):,} B)")
            return 0
        indice = exp.generar_estaticas(args.destino)
        ok = [a for a in indice["archivos"] if "error" not in a]
        print(f"✓ {len(ok)} archivos en {args.destino} · backend {indice['backend']} · {indice['total_filas']} filas · {indice['generado']}")
        for a in indice["archivos"]:
            print(f"   {'✗' if 'error' in a else '·'} {a['archivo']:<22} {a.get('bytes', 0):>9,} B {a.get('error', '')}")
        return 0 if len(ok) == len(indice["archivos"]) else 1
    finally:
        ctx.db.close()


if __name__ == "__main__":
    raise SystemExit(main())
