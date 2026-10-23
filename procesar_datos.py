"""
procesar_datos.py
-----------------
Etapa de ingesta y validación del pipeline MLOps.

1. Lee  data/datos.csv
2. Valida el esquema y los tipos de datos
3. Convierte las columnas numéricas (coerción -> NaN si es inválido)
4. Calcula estadísticas (promedios, conteos, válidos / inválidos)
5. Escribe output/resultado.json
6. Registra todo en logs/ejecucion.log
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "datos.csv"
META_PATH = DATA_PATH.with_suffix(".meta.json")      # procedencia (lo escribe generar_datos.py, opcional)
OUTPUT_PATH = BASE_DIR / "output" / "resultado.json"
LOG_PATH = BASE_DIR / "logs" / "ejecucion.log"

# Esquema esperado del dataset
COLUMNAS_NUMERICAS = ["temperatura", "humedad", "radiacion_solar", "precipitacion", "viento"]
COLUMNA_CATEGORICA = "cultivo"
COLUMNA_CIUDAD = "ciudad"                       # variable predictora asociada al cultivo
CIUDAD_POR_CULTIVO = {"cafe": "chanchamayo", "papa": "huancayo", "uva": "ica"}
COLUMNA_OBJETIVO = "resultado"
COLUMNAS_REQUERIDAS = ["id", COLUMNA_CATEGORICA, *COLUMNAS_NUMERICAS, COLUMNA_OBJETIVO]

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("procesar_datos")


# --------------------------------------------------------------------------- #
# Funciones
# --------------------------------------------------------------------------- #
def leer_datos(ruta: Path) -> pd.DataFrame:
    """Lee el CSV y falla de forma explícita si no existe."""
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró el dataset en {ruta}")
    df = pd.read_csv(ruta)
    log.info("Dataset leído: %s (%d filas, %d columnas)", ruta.name, *df.shape)
    return df


def validar_esquema(df: pd.DataFrame) -> None:
    """Comprueba que estén todas las columnas necesarias."""
    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in df.columns]
    if faltantes:
        raise ValueError(f"Faltan columnas requeridas: {faltantes}")
    log.info("Esquema validado correctamente (%d columnas requeridas)", len(COLUMNAS_REQUERIDAS))


def convertir_numericos(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Convierte las columnas numéricas y contabiliza valores inválidos."""
    detalle = {}
    for col in COLUMNAS_NUMERICAS:
        original_nulos = int(df[col].isna().sum())
        df[col] = pd.to_numeric(df[col], errors="coerce")
        nuevos_nulos = int(df[col].isna().sum())
        invalidos = nuevos_nulos - original_nulos
        detalle[col] = {
            "validos": int(df[col].notna().sum()),
            "invalidos": invalidos,
            "nulos_originales": original_nulos,
            "promedio": round(float(df[col].mean()), 3) if df[col].notna().any() else None,
            "mediana": round(float(df[col].median()), 3) if df[col].notna().any() else None,
            "desviacion": round(float(df[col].std()), 3) if df[col].notna().sum() > 1 else None,
            "min": round(float(df[col].min()), 3) if df[col].notna().any() else None,
            "max": round(float(df[col].max()), 3) if df[col].notna().any() else None,
        }
        if invalidos:
            log.warning("Columna '%s': %d valores no numéricos convertidos a NaN", col, invalidos)
    return df, detalle


def completar_ciudad(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Añade/valida la columna `ciudad` (cafe→chanchamayo, papa→huancayo, uva→ica).

    Si falta se deduce del cultivo; si existe se normaliza y se cuentan (y corrigen) las filas
    cuya ciudad no corresponde al cultivo.
    """
    df = df.copy()
    df[COLUMNA_CATEGORICA] = df[COLUMNA_CATEGORICA].astype(str).str.strip().str.lower()
    esperada = df[COLUMNA_CATEGORICA].map(CIUDAD_POR_CULTIVO)
    if COLUMNA_CIUDAD not in df.columns:
        df.insert(df.columns.get_loc(COLUMNA_CATEGORICA) + 1, COLUMNA_CIUDAD, esperada)
        log.warning("Columna '%s' ausente: se deduce del cultivo (%s)", COLUMNA_CIUDAD, CIUDAD_POR_CULTIVO)
        inconsistentes = 0
    else:
        df[COLUMNA_CIUDAD] = df[COLUMNA_CIUDAD].astype(str).str.strip().str.lower()
        mal = esperada.notna() & (df[COLUMNA_CIUDAD] != esperada)
        inconsistentes = int(mal.sum())
        if inconsistentes:
            log.warning("%d filas con ciudad distinta a la del cultivo; se corrigen según el mapa", inconsistentes)
            df.loc[mal, COLUMNA_CIUDAD] = esperada[mal]
    log.info("Columna '%s' lista: %s", COLUMNA_CIUDAD, dict(df.groupby(COLUMNA_CATEGORICA)[COLUMNA_CIUDAD].first()))
    return df, {"ciudad_por_cultivo": dict(df.groupby(COLUMNA_CATEGORICA)[COLUMNA_CIUDAD].first()),
                "ciudad_inconsistentes_corregidas": inconsistentes}


def normalizar_objetivo(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza la variable objetivo a mayúsculas sin espacios."""
    df[COLUMNA_OBJETIVO] = df[COLUMNA_OBJETIVO].astype(str).str.strip().str.upper()
    valores_raros = set(df[COLUMNA_OBJETIVO].unique()) - {"SI", "NO"}
    if valores_raros:
        log.warning("Valores inesperados en '%s': %s", COLUMNA_OBJETIVO, sorted(valores_raros))
    return df


def _tercios(df: pd.DataFrame, variable: str) -> dict | None:
    """Tasa de SI cuando la variable está en su tercio bajo / medio / alto (cortes por terciles)."""
    serie = df[variable].dropna()
    if len(serie) < 9:
        return None
    q1, q2 = float(serie.quantile(1 / 3)), float(serie.quantile(2 / 3))
    si = (df[COLUMNA_OBJETIVO] == "SI")
    tramos = {"bajo": df[variable] <= q1, "medio": (df[variable] > q1) & (df[variable] <= q2), "alto": df[variable] > q2}
    salida = {"limites": [round(q1, 2), round(q2, 2)]}
    for nombre, mascara in tramos.items():
        n = int(mascara.sum())
        salida[nombre] = {"n": n, "si": int((mascara & si).sum()), "tasa_si": round(float((mascara & si).sum() / n), 3) if n else None}
    return salida


def analizar_relacion_si(df: pd.DataFrame) -> dict:
    """Relación entre cada variable climática y el resultado SI, en formas fáciles de interpretar:
    tasa de SI por tercio (global y por cultivo), correlación con SI, promedios SI/NO dentro de cada
    cultivo y rango típico (cuartiles 25–75) de los casos SI por cultivo. Alimenta la interpretación
    automática y las recomendaciones de la página de resultados."""
    d = df.dropna(subset=COLUMNAS_NUMERICAS).copy()
    si = (d[COLUMNA_OBJETIVO] == "SI").astype(int)
    correlacion = {}
    for v in COLUMNAS_NUMERICAS:
        c = d[v].corr(si) if d[v].std() > 0 and si.std() > 0 else None
        correlacion[v] = None if c is None or pd.isna(c) else round(float(c), 3)
    tercios = {v: _tercios(d, v) for v in COLUMNAS_NUMERICAS}
    tercios_cultivo, promedio_cr, rango_si = {}, {}, {}
    for cultivo, g in d.groupby(COLUMNA_CATEGORICA):
        tercios_cultivo[cultivo] = {v: _tercios(g, v) for v in COLUMNAS_NUMERICAS}
        promedio_cr[cultivo] = g.groupby(COLUMNA_OBJETIVO)[COLUMNAS_NUMERICAS].mean().round(3).to_dict(orient="index")
        g_si = g[g[COLUMNA_OBJETIVO] == "SI"]
        rango_si[cultivo] = {"n_si": int(len(g_si))}
        if len(g_si) >= 5:
            for v in COLUMNAS_NUMERICAS:
                rango_si[cultivo][v] = [round(float(g_si[v].quantile(0.25)), 2), round(float(g_si[v].quantile(0.75)), 2)]
    return {
        "correlacion_con_si": correlacion,
        "tasa_si_por_tercio": tercios,
        "tasa_si_por_tercio_cultivo": tercios_cultivo,
        "promedio_por_cultivo_resultado": promedio_cr,
        "rango_tipico_si_por_cultivo": rango_si,
    }


def construir_resultado(df: pd.DataFrame, detalle: dict, info_ciudad: dict | None = None) -> dict:
    """Construye el diccionario que se serializa a JSON."""
    info_ciudad = info_ciudad or {}
    filas_validas = int(df.dropna(subset=COLUMNAS_NUMERICAS).shape[0])
    filas_invalidas = int(df.shape[0] - filas_validas)

    distribucion_objetivo = df[COLUMNA_OBJETIVO].value_counts().to_dict()
    distribucion_cultivo = df[COLUMNA_CATEGORICA].value_counts().to_dict()
    promedio_por_cultivo = (
        df.groupby(COLUMNA_CATEGORICA)[COLUMNAS_NUMERICAS].mean().round(3).to_dict(orient="index")
    )
    tasa_si_por_cultivo = (
        df.assign(_si=(df[COLUMNA_OBJETIVO] == "SI").astype(int))
        .groupby(COLUMNA_CATEGORICA)["_si"]
        .mean()
        .round(3)
        .to_dict()
    )
    # comparación SI vs NO (base de la interpretación en la página de resultados)
    promedio_por_resultado = (
        df.groupby(COLUMNA_OBJETIVO)[COLUMNAS_NUMERICAS].mean().round(3).to_dict(orient="index")
    )
    conteo_cultivo_resultado = {
        cultivo: {k: int(v) for k, v in grupo[COLUMNA_OBJETIVO].value_counts().items()}
        for cultivo, grupo in df.groupby(COLUMNA_CATEGORICA)
    }
    distribucion_ciudad = df[COLUMNA_CIUDAD].value_counts().to_dict()
    promedio_por_ciudad = df.groupby(COLUMNA_CIUDAD)[COLUMNAS_NUMERICAS].mean().round(3).to_dict(orient="index")
    tasa_si_por_ciudad = (
        df.assign(_si=(df[COLUMNA_OBJETIVO] == "SI").astype(int)).groupby(COLUMNA_CIUDAD)["_si"].mean().round(3).to_dict()
    )

    origen_datos = None
    if META_PATH.exists():
        try:
            origen_datos = json.loads(META_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:      # el sidecar es opcional: nunca debe romper el pipeline
            log.warning("No se pudo leer %s: %s", META_PATH.name, exc)

    return {
        "fecha_ejecucion": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "archivo_origen": DATA_PATH.name,
        "origen_datos": origen_datos,
        "filas_totales": int(df.shape[0]),
        "filas_validas": filas_validas,
        "filas_invalidas": filas_invalidas,
        "columnas": list(df.columns),
        "columnas_categoricas": [COLUMNA_CATEGORICA, COLUMNA_CIUDAD],
        "columnas_numericas": detalle,
        "promedio_general": {c: detalle[c]["promedio"] for c in COLUMNAS_NUMERICAS},
        "distribucion_resultado": {k: int(v) for k, v in distribucion_objetivo.items()},
        "distribucion_cultivo": {k: int(v) for k, v in distribucion_cultivo.items()},
        "promedio_por_cultivo": promedio_por_cultivo,
        "tasa_si_por_cultivo": tasa_si_por_cultivo,
        "conteo_cultivo_resultado": conteo_cultivo_resultado,
        "promedio_por_resultado": promedio_por_resultado,
        "ciudad_por_cultivo": info_ciudad.get("ciudad_por_cultivo", CIUDAD_POR_CULTIVO),
        "ciudad_inconsistentes_corregidas": info_ciudad.get("ciudad_inconsistentes_corregidas", 0),
        "distribucion_ciudad": {k: int(v) for k, v in distribucion_ciudad.items()},
        "promedio_por_ciudad": promedio_por_ciudad,
        "tasa_si_por_ciudad": tasa_si_por_ciudad,
        **analizar_relacion_si(df),
    }


def guardar_json(resultado: dict, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    log.info("Resultado guardado en %s", ruta)


def main() -> int:
    log.info("=" * 60)
    log.info("Inicio del procesamiento de datos")
    try:
        df = leer_datos(DATA_PATH)
        validar_esquema(df)
        df, detalle = convertir_numericos(df)
        df = normalizar_objetivo(df)
        df, info_ciudad = completar_ciudad(df)
        resultado = construir_resultado(df, detalle, info_ciudad)
        guardar_json(resultado, OUTPUT_PATH)
        log.info(
            "Resumen: %d filas | %d válidas | %d inválidas | resultado=%s",
            resultado["filas_totales"],
            resultado["filas_validas"],
            resultado["filas_invalidas"],
            resultado["distribucion_resultado"],
        )
        log.info("Procesamiento finalizado con éxito")
        return 0
    except Exception as exc:  # noqa: BLE001 - queremos registrar cualquier fallo
        log.exception("Error durante el procesamiento: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
