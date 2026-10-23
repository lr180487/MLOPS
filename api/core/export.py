"""
Exportación de la base de datos del proyecto a CSV / XLSX / PDF (y JSON).

Tablas exportables
------------------
    datos          data/datos.csv (dataset de entrada)
    predicciones   tabla `predictions` de la persistencia (PostgreSQL o SQLite)
    feedback       tabla `feedback` unida a su predicción
    resultado      estadísticas por variable de output/resultado.json
    base_datos     todo lo anterior: XLSX multi-hoja, PDF por secciones o ZIP de CSV

Los archivos se generan en memoria bajo demanda; ningún formato requiere servicios
externos. El PDF usa reportlab y, si no está instalado, cae a un generador básico con
matplotlib (que ya es dependencia del proyecto).
"""

from __future__ import annotations

import io
import json
import logging
import os
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

log = logging.getLogger("api.export")

FORMATOS = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
    "json": ("application/json; charset=utf-8", "json"),
    "zip": ("application/zip", "zip"),
    "sqlite": ("application/vnd.sqlite3", "sqlite"),
}
LIMITE_PDF_TABLA = 2000       # filas máximas por tabla en un PDF individual
LIMITE_PDF_COMPLETO = 400     # filas máximas por sección en el PDF de toda la base de datos
ETIQUETA = {0: "NO", 1: "SI"}


@dataclass
class Tabla:
    clave: str
    titulo: str
    descripcion: str
    fuente: str
    cargar: Callable[[], pd.DataFrame]


# --------------------------------------------------------------------------- #
# Carga de cada tabla como DataFrame
# --------------------------------------------------------------------------- #
class Exportador:
    def __init__(self, ctx):
        self.ctx = ctx
        self.s = ctx.settings
        self.tablas: dict[str, Tabla] = {
            "datos": Tabla("datos", "Dataset de entrada", "Observaciones agroclimáticas por cultivo y ciudad con la etiqueta resultado (SI/NO).",
                           "data/datos.csv", self._datos),
            "predicciones": Tabla("predicciones", "Predicciones persistidas",
                                  "Todas las predicciones realizadas (dashboard, simulador y lotes) con el resultado real cuando se registró.",
                                  "tabla predictions", self._predicciones),
            "feedback": Tabla("feedback", "Feedback registrado", "Etiquetas reales enviadas por los usuarios y si la predicción acertó.",
                              "tabla feedback", self._feedback),
            "resultado": Tabla("resultado", "Estadísticas por variable", "Resumen del procesamiento de datos: válidos, inválidos, mínimo, promedio, máximo y promedio por cultivo (con su ciudad).",
                               "output/resultado.json", self._resultado),
        }

    # -- tablas --------------------------------------------------------------
    def _datos(self) -> pd.DataFrame:
        if not self.s.data_path.exists():
            return pd.DataFrame()
        return pd.read_csv(self.s.data_path)

    def _predicciones(self) -> pd.DataFrame:
        filas = self.ctx.db.execute("SELECT * FROM predictions ORDER BY ts, id", (), "all") or []
        df = pd.DataFrame([dict(f) for f in filas])
        if df.empty:
            return pd.DataFrame(columns=["id", "timestamp", "origen", "cultivo", "ciudad", *self.s.features_num, "probabilidad_si", "prediccion",
                                         "umbral", "etiqueta_real", "acierto", "latencia_ms", "modelo_version", "cache_hit"])
        df = df.rename(columns={"ts": "timestamp"})
        df["prediccion"] = df["prediccion"].map(ETIQUETA)
        df["etiqueta_real"] = df["etiqueta_real"].map(lambda v: ETIQUETA.get(int(v)) if pd.notna(v) else None)
        df["acierto"] = [None if r is None else (r == p) for r, p in zip(df["etiqueta_real"], df["prediccion"])]
        df["cache_hit"] = df["cache_hit"].fillna(0).astype(int).astype(bool)
        orden = ["id", "timestamp", "origen", "cultivo", "ciudad", *self.s.features_num, "probabilidad_si", "prediccion", "umbral",
                 "etiqueta_real", "acierto", "latencia_ms", "modelo_version", "cache_hit"]
        return df[[c for c in orden if c in df.columns]]

    def _feedback(self) -> pd.DataFrame:
        filas = self.ctx.db.execute(
            "SELECT f.id, f.ts, f.prediction_id, p.cultivo, p.ciudad, p.probabilidad_si, f.prediccion, f.etiqueta_real, f.acierto, f.origen, f.comentario "
            "FROM feedback f LEFT JOIN predictions p ON p.id = f.prediction_id ORDER BY f.ts, f.id", (), "all") or []
        df = pd.DataFrame([dict(f) for f in filas])
        if df.empty:
            return pd.DataFrame(columns=["id", "timestamp", "prediction_id", "cultivo", "ciudad", "probabilidad_si", "prediccion", "etiqueta_real", "acierto", "origen", "comentario"])
        df = df.rename(columns={"ts": "timestamp"})
        df["prediccion"] = df["prediccion"].map(ETIQUETA)
        df["etiqueta_real"] = df["etiqueta_real"].map(ETIQUETA)
        df["acierto"] = df["acierto"].astype(int).astype(bool)
        return df

    def _resultado(self) -> pd.DataFrame:
        if not self.s.result_path.exists():
            return pd.DataFrame()
        r = json.loads(self.s.result_path.read_text(encoding="utf-8"))
        filas = []
        ciudades = r.get("ciudad_por_cultivo", {})
        for f, c in r.get("columnas_numericas", {}).items():
            fila = {"variable": f, **c}
            for cu, prom in r.get("promedio_por_cultivo", {}).items():
                etiqueta = f"{cu}_{ciudades[cu]}" if ciudades.get(cu) else cu
                fila[f"promedio_{etiqueta}"] = prom.get(f)
            filas.append(fila)
        return pd.DataFrame(filas)

    # -- catálogo -------------------------------------------------------------
    def catalogo(self) -> dict:
        items = []
        for t in self.tablas.values():
            try:
                df = t.cargar()
                filas, columnas, error = int(len(df)), list(map(str, df.columns)), None
            except Exception as e:  # pragma: no cover - tabla no disponible
                filas, columnas, error = 0, [], str(e)
            items.append({"clave": t.clave, "titulo": t.titulo, "descripcion": t.descripcion, "fuente": t.fuente, "filas": filas,
                          "columnas": columnas, "error": error,
                          "descargas": {fmt: f"/download/{t.clave}.{fmt}" for fmt in ("csv", "xlsx", "pdf", "json")}})
        return {
            "generado": _ahora(), "backend": self.ctx.db.backend, "tablas": items,
            "completa": {"clave": "base_datos", "titulo": "Base de datos completa", "filas": sum(i["filas"] for i in items),
                         "descargas": {"xlsx": "/download/base_datos.xlsx", "pdf": "/download/base_datos.pdf", "csv": "/download/base_datos.zip",
                                       "zip": "/download/base_datos.zip", "json": "/download/base_datos.json", "sqlite": "/download/base_datos.sqlite"},
                         "sqlite": ("copia exacta del archivo SQLite en uso" if self.ctx.db.backend == "sqlite"
                                    else "copia portable en SQLite generada desde PostgreSQL")},
            "limites": {"pdf_filas_por_tabla": LIMITE_PDF_TABLA, "pdf_completo_filas_por_seccion": LIMITE_PDF_COMPLETO},
            "estaticas": self._resumen_estaticas(),
        }

    def _resumen_estaticas(self) -> dict | None:
        idx = self.leer_indice_estaticas(self.s.base_dir)
        if not idx:
            return None
        return {"carpeta": idx.get("carpeta"), "generado": idx.get("generado"), "archivos": sum(1 for a in idx.get("archivos", []) if "error" not in a),
                "indice": "/output/exportaciones/index.json"}

    # -- exportación ----------------------------------------------------------
    def exportar(self, clave: str, formato: str, limite: int | None = None) -> tuple[bytes, str, str]:
        """Devuelve (contenido, media_type, nombre_archivo)."""
        formato = formato.lower()
        if clave == "base_datos":
            return self._exportar_completa(formato, limite)
        if clave not in self.tablas:
            raise KeyError(clave)
        if formato not in ("csv", "xlsx", "pdf", "json"):
            raise ValueError(formato)
        t = self.tablas[clave]
        df = t.cargar()
        if formato == "csv":
            contenido = df.to_csv(index=False).encode("utf-8-sig")       # BOM → Excel abre bien las tildes
        elif formato == "json":
            contenido = df.to_json(orient="records", force_ascii=False, indent=2, date_format="iso").encode("utf-8")
        elif formato == "xlsx":
            contenido = self._xlsx({t.clave: (t, df)})
        else:
            contenido = self._pdf([(t, df)], titulo=t.titulo, limite=limite or LIMITE_PDF_TABLA)
        media, ext = FORMATOS[formato]
        return contenido, media, f"{clave}.{ext}"

    def _exportar_completa(self, formato: str, limite: int | None) -> tuple[bytes, str, str]:
        hojas = {k: (t, t.cargar()) for k, t in self.tablas.items()}
        if formato == "xlsx":
            return self._xlsx(hojas), FORMATOS["xlsx"][0], "base_datos.xlsx"
        if formato == "pdf":
            return (self._pdf(list(hojas.values()), titulo="Base de datos completa", limite=limite or LIMITE_PDF_COMPLETO),
                    FORMATOS["pdf"][0], "base_datos.pdf")
        if formato in ("csv", "zip"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for k, (t, df) in hojas.items():
                    z.writestr(f"{k}.csv", df.to_csv(index=False).encode("utf-8-sig"))
                z.writestr("LEEME.txt", self._leeme(hojas))
            return buf.getvalue(), FORMATOS["zip"][0], "base_datos.zip"
        if formato == "sqlite":
            return self._sqlite(hojas), FORMATOS["sqlite"][0], "base_datos.sqlite"
        if formato == "json":
            datos = {k: json.loads(df.to_json(orient="records", force_ascii=False, date_format="iso")) for k, (t, df) in hojas.items()}
            cuerpo = {"generado": _ahora(), "backend": self.ctx.db.backend, "tablas": datos}
            return json.dumps(cuerpo, ensure_ascii=False, indent=2).encode("utf-8"), FORMATOS["json"][0], "base_datos.json"
        raise ValueError(formato)

    def _sqlite(self, hojas: dict[str, tuple[Tabla, pd.DataFrame]]) -> bytes:
        """Archivo SQLite descargable: copia consistente de la BD en uso (backup online) o, con PostgreSQL, copia portable."""
        fd, ruta = tempfile.mkstemp(suffix=".sqlite", prefix="mlops_export_")
        os.close(fd)
        try:
            db = self.ctx.db
            if db.backend == "sqlite" and db._conn is not None:
                with db._lock:
                    destino = sqlite3.connect(ruta)
                    try:
                        db._conn.backup(destino)     # snapshot consistente aunque haya escrituras concurrentes
                    finally:
                        destino.close()
            else:
                con = sqlite3.connect(ruta)
                try:
                    for k, (t, df) in hojas.items():
                        _preparar_para_excel(df).to_sql(k, con, index=False, if_exists="replace")
                finally:
                    con.close()
            con = sqlite3.connect(ruta)
            try:   # tabla de metadatos de la exportación + tablas derivadas (dataset y resultado no viven en la BD)
                con.execute("CREATE TABLE IF NOT EXISTS export_info (campo TEXT, valor TEXT)")
                con.execute("DELETE FROM export_info")
                con.executemany("INSERT INTO export_info VALUES (?, ?)", [
                    ("proyecto", "Práctica MLOps"), ("generado", _ahora()), ("backend_origen", db.backend),
                    ("modo", "backup del archivo SQLite en uso" if db.backend == "sqlite" else "copia portable desde PostgreSQL")])
                for k in ("datos", "resultado"):
                    if k in hojas:
                        _preparar_para_excel(hojas[k][1]).to_sql(k, con, index=False, if_exists="replace")
                con.commit()
                con.execute("VACUUM")
            finally:
                con.close()
            return Path(ruta).read_bytes()
        finally:
            try:
                os.remove(ruta)
            except OSError:
                pass

    # -- copias estáticas (funcionan sin la API: visor de archivos, repositorio, file://) --
    def generar_estaticas(self, destino: Path | None = None) -> dict:
        """Escribe todas las exportaciones en output/exportaciones/ más un index.json con el catálogo."""
        destino = destino or (self.s.base_dir / "output" / "exportaciones")
        destino.mkdir(parents=True, exist_ok=True)
        archivos: list[dict] = []
        combinaciones = [(k, f) for k in self.tablas for f in ("csv", "xlsx", "pdf", "json")] + \
                        [("base_datos", f) for f in ("xlsx", "pdf", "zip", "sqlite", "json")]
        for clave, formato in combinaciones:
            try:
                contenido, media, nombre = self.exportar(clave, formato)
                (destino / nombre).write_bytes(contenido)
                archivos.append({"archivo": nombre, "tabla": clave, "formato": formato, "bytes": len(contenido), "media_type": media})
            except Exception as exc:  # noqa: BLE001 - una exportación fallida no impide las demás
                log.warning("Exportación estática %s.%s falló: %s", clave, formato, exc)
                archivos.append({"archivo": f"{clave}.{formato}", "tabla": clave, "formato": formato, "error": str(exc)})
        catalogo = self.catalogo()
        indice = {"generado": _ahora(), "backend": catalogo["backend"], "carpeta": str(destino.relative_to(self.s.base_dir)) if destino.is_relative_to(self.s.base_dir) else str(destino),
                  "tablas": [{k: v for k, v in t.items() if k != "descargas"} for t in catalogo["tablas"]],
                  "total_filas": catalogo["completa"]["filas"], "archivos": archivos}
        (destino / "index.json").write_text(json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Exportaciones estáticas: %d archivos en %s", sum(1 for a in archivos if "error" not in a), destino)
        return indice

    @staticmethod
    def leer_indice_estaticas(base_dir: Path) -> dict | None:
        ruta = base_dir / "output" / "exportaciones" / "index.json"
        if not ruta.exists():
            return None
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _leeme(self, hojas: dict[str, tuple[Tabla, pd.DataFrame]]) -> str:
        lineas = [f"Práctica MLOps · exportación de la base de datos ({self.ctx.db.backend}) · {_ahora()}", ""]
        for k, (t, df) in hojas.items():
            lineas.append(f"- {k}.csv: {t.titulo} · {len(df)} filas · fuente {t.fuente}")
        return "\n".join(lineas) + "\n"

    # -- XLSX -----------------------------------------------------------------
    def _xlsx(self, hojas: dict[str, tuple[Tabla, pd.DataFrame]]) -> bytes:
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            # hoja de portada
            info = pd.DataFrame([
                {"campo": "proyecto", "valor": "Práctica MLOps"},
                {"campo": "generado", "valor": _ahora()},
                {"campo": "backend de persistencia", "valor": self.ctx.db.backend},
                {"campo": "modelo", "valor": f"{self.ctx.predictor.info().get('modelo')} v{self.ctx.predictor.info().get('version')} ({self.ctx.predictor.info().get('hash')})"},
                *[{"campo": f"hoja '{k}'", "valor": f"{t.titulo} · {len(df)} filas · {t.fuente}"} for k, (t, df) in hojas.items()],
            ])
            info.to_excel(writer, sheet_name="Info", index=False)
            for k, (t, df) in hojas.items():
                _preparar_para_excel(df).to_excel(writer, sheet_name=k[:31], index=False)
            # formato
            cabecera = Font(bold=True, color="FFFFFF")
            relleno = PatternFill("solid", fgColor="2546E8")
            for ws in writer.book.worksheets:
                for celda in ws[1]:
                    celda.font, celda.fill, celda.alignment = cabecera, relleno, Alignment(vertical="center")
                ws.freeze_panes = "A2"
                ws.auto_filter.ref = ws.dimensions
                for idx, col in enumerate(ws.iter_cols(min_row=1, max_row=min(ws.max_row, 500)), start=1):
                    ancho = max((len(str(c.value)) for c in col if c.value is not None), default=8)
                    ws.column_dimensions[get_column_letter(idx)].width = min(max(ancho + 2, 8), 60)
        return buf.getvalue()

    # -- PDF ------------------------------------------------------------------
    def _pdf(self, secciones: list[tuple[Tabla, pd.DataFrame]], titulo: str, limite: int) -> bytes:
        meta = {"generado": _ahora(), "backend": self.ctx.db.backend,
                "modelo": f"{self.ctx.predictor.info().get('modelo')} v{self.ctx.predictor.info().get('version')}"}
        try:
            return _pdf_reportlab(secciones, titulo, meta, limite)
        except ImportError:
            log.warning("reportlab no está instalado; PDF generado con matplotlib (pip install reportlab para el formato completo)")
            return _pdf_matplotlib(secciones, titulo, meta, limite)


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #
def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _preparar_para_excel(df: pd.DataFrame) -> pd.DataFrame:
    """Excel no admite tz-aware ni objetos; todo lo raro se pasa a texto."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].map(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
    return out


def _celda(v, max_len: int = 38) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, bool):
        return "sí" if v else "no"
    if isinstance(v, float):
        s = f"{v:.4f}".rstrip("0").rstrip(".")
    else:
        s = str(v)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _pdf_reportlab(secciones, titulo: str, meta: dict, limite: int) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    pagina = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=pagina, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Práctica MLOps · {titulo}", author="Práctica MLOps")
    estilos = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=estilos["Title"], fontSize=17, spaceAfter=4, alignment=0)
    h2 = ParagraphStyle("h2", parent=estilos["Heading2"], fontSize=12.5, spaceBefore=2, spaceAfter=2, textColor=colors.HexColor("#1e3a8a"))
    sub = ParagraphStyle("sub", parent=estilos["Normal"], fontSize=8.5, textColor=colors.HexColor("#64748b"), spaceAfter=6)
    ancho_util = pagina[0] - doc.leftMargin - doc.rightMargin

    cuerpo = [Paragraph(f"Práctica MLOps · {titulo}", h1),
              Paragraph(f"Generado el {meta['generado']} · persistencia: {meta['backend']} · modelo: {meta['modelo']}", sub)]
    for i, (t, df) in enumerate(secciones):
        if i:
            cuerpo.append(PageBreak())
        total = len(df)
        vista = df.head(limite)
        nota = f" · mostrando las primeras {len(vista)} de {total} filas" if total > len(vista) else ""
        cuerpo.append(Paragraph(t.titulo, h2))
        cuerpo.append(Paragraph(f"{t.descripcion} Fuente: {t.fuente} · {total} filas · {len(df.columns)} columnas{nota}", sub))
        if vista.empty:
            cuerpo.append(Paragraph("Sin filas.", sub))
            continue
        cabeceras = [str(c) for c in vista.columns]
        filas = [[_celda(v) for v in fila] for fila in vista.itertuples(index=False, name=None)]
        n_col = len(cabeceras)
        fuente = 8 if n_col <= 8 else (7 if n_col <= 12 else 6)
        # anchos proporcionales al contenido (acotados) que llenan el ancho útil
        largos = [max(len(h), *(len(f[j]) for f in filas[:300])) for j, h in enumerate(cabeceras)]
        largos = [min(max(l, 4), 38) for l in largos]
        anchos = [ancho_util * l / sum(largos) for l in largos]
        tabla = Table([cabeceras, *filas], colWidths=anchos, repeatRows=1)
        tabla.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), fuente),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2546e8")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ]))
        cuerpo.append(tabla)
        cuerpo.append(Spacer(1, 4))

    def pie(canvas, documento):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(doc.leftMargin, 8 * mm, f"Práctica MLOps · {titulo} · {meta['generado']}")
        canvas.drawRightString(pagina[0] - doc.rightMargin, 8 * mm, f"página {documento.page}")
        canvas.restoreState()

    doc.build(cuerpo, onFirstPage=pie, onLaterPages=pie)
    return buf.getvalue()


def _pdf_matplotlib(secciones, titulo: str, meta: dict, limite: int) -> bytes:
    """Respaldo sin reportlab: tablas paginadas con matplotlib (menos vistoso, mismo contenido)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    buf = io.BytesIO()
    filas_pagina = 32
    with PdfPages(buf) as pdf:
        for t, df in secciones:
            vista = df.head(limite)
            cabeceras = [str(c) for c in vista.columns]
            datos = [[_celda(v, 22) for v in fila] for fila in vista.itertuples(index=False, name=None)] or [["(sin filas)"] + [""] * (len(cabeceras) - 1)]
            for inicio in range(0, len(datos), filas_pagina):
                fig, ax = plt.subplots(figsize=(11.69, 8.27))
                ax.axis("off")
                fig.text(0.04, 0.95, f"Práctica MLOps · {titulo} — {t.titulo}", fontsize=13, weight="bold")
                fig.text(0.04, 0.92, f"{t.fuente} · {len(df)} filas · generado {meta['generado']} · {meta['backend']}", fontsize=8, color="#64748b")
                tabla = ax.table(cellText=datos[inicio:inicio + filas_pagina], colLabels=cabeceras, loc="upper center", cellLoc="left")
                tabla.auto_set_font_size(False)
                tabla.set_fontsize(6.5 if len(cabeceras) > 8 else 8)
                tabla.scale(1, 1.15)
                for (r, c), celda in tabla.get_celld().items():
                    celda.set_edgecolor("#cbd5e1")
                    if r == 0:
                        celda.set_facecolor("#2546e8"); celda.get_text().set_color("white"); celda.get_text().set_weight("bold")
                    elif r % 2 == 0:
                        celda.set_facecolor("#f1f5f9")
                pdf.savefig(fig)
                plt.close(fig)
    return buf.getvalue()
