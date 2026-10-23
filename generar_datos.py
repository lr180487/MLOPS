"""
generar_datos.py
----------------
Amplía el dataset agroclimático a N filas (por defecto 1000) generando observaciones
sintéticas **calibradas con los datos originales** (data/datos_original_50.csv):

* Los 50 registros originales se conservan tal cual (ids 1-50) y se añaden N-50 sintéticos.
* Proporción de cultivos igual a la original; la ciudad va asociada al cultivo
  (cafe → chanchamayo, papa → huancayo, uva → ica).
* Variables climáticas: muestreo normal multivariante por cultivo (media y covarianza
  de los registros reales, con encogimiento hacia la diagonal) recortado a rangos plausibles.
* Resultado SI/NO: se sorteó con la probabilidad de un modelo logístico ajustado a los 50
  registros reales (sin ponderar), con el término independiente de cada cultivo calibrado para
  que la tasa de SI por cultivo coincida con la observada (cafe 38 %, uva 22 %, papa 5 %).
  Así los datos sintéticos conservan la relación clima ↔ resultado de los originales,
  incluido el ruido: no son separables de forma perfecta.

Uso:
    python generar_datos.py                 # 1000 filas → data/datos.csv (semilla 42)
    python generar_datos.py --n 5000 --semilla 7 --salida data/datos_5000.csv
    python generar_datos.py --sin-originales  # todas las filas sintéticas

Después: python procesar_datos.py  y re-ejecutar notebooks/entrenamiento.ipynb.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

BASE_DIR = Path(__file__).resolve().parent
ORIGINAL_PATH = BASE_DIR / "data" / "datos_original_50.csv"
SALIDA_PATH = BASE_DIR / "data" / "datos.csv"

NUMERICAS = ["temperatura", "humedad", "radiacion_solar", "precipitacion", "viento"]
CIUDAD_POR_CULTIVO = {"cafe": "chanchamayo", "papa": "huancayo", "uva": "ica"}
# límites físicos plausibles (recorte del muestreo normal)
LIMITES = {"temperatura": (-5.0, 45.0), "humedad": (10.0, 100.0), "radiacion_solar": (0.5, 40.0),
           "precipitacion": (0.0, 60.0), "viento": (0.0, 40.0)}


def cargar_originales() -> pd.DataFrame:
    if not ORIGINAL_PATH.exists():          # primera ejecución: el datos.csv actual son los originales
        df = pd.read_csv(SALIDA_PATH)
        if len(df) > 60:
            raise SystemExit(f"No existe {ORIGINAL_PATH} y {SALIDA_PATH} ya no parece el dataset original.")
        df.to_csv(ORIGINAL_PATH, index=False)
        print(f"Copia de seguridad de los datos originales → {ORIGINAL_PATH.relative_to(BASE_DIR)}")
    df = pd.read_csv(ORIGINAL_PATH)
    df["cultivo"] = df["cultivo"].astype(str).str.strip().str.lower()
    df["resultado"] = df["resultado"].astype(str).str.strip().str.upper()
    if "ciudad" not in df.columns:
        df.insert(df.columns.get_loc("cultivo") + 1, "ciudad", df["cultivo"].map(CIUDAD_POR_CULTIVO))
    return df.dropna(subset=NUMERICAS + ["cultivo", "resultado"]).reset_index(drop=True)


def modelo_calibrado(df: pd.DataFrame) -> Pipeline:
    """Regresión logística sin ponderar (probabilidades calibradas a la tasa real de SI)."""
    pre = ColumnTransformer([("num", StandardScaler(), NUMERICAS),
                             ("cat", OneHotEncoder(handle_unknown="ignore"), ["cultivo"])])
    modelo = Pipeline([("pre", pre), ("clf", LogisticRegression(C=3.0, max_iter=2000, random_state=0))])
    modelo.fit(df[NUMERICAS + ["cultivo"]], (df["resultado"] == "SI").astype(int))
    return modelo


def muestrear_clima(df_cultivo: pd.DataFrame, n: int, rng: np.random.Generator) -> pd.DataFrame:
    x = df_cultivo[NUMERICAS].to_numpy(dtype=float)
    media = x.mean(axis=0)
    cov = np.cov(x, rowvar=False)
    cov = 0.7 * cov + 0.3 * np.diag(np.diag(cov))          # encogimiento: covarianzas menos ruidosas
    muestra = rng.multivariate_normal(media, cov, size=n)
    out = pd.DataFrame(muestra, columns=NUMERICAS)
    for col in NUMERICAS:                                     # recorte a rangos plausibles
        lo, hi = LIMITES[col]
        out[col] = out[col].clip(lo, hi)
    return out.round(1)


def calibrar_desplazamiento(logit: np.ndarray, objetivo: float) -> float:
    """Desplazamiento d tal que mean(sigmoid(logit + d)) == objetivo (bisección)."""
    lo, hi = -10.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        p = 1 / (1 + np.exp(-(logit + mid)))
        if p.mean() < objetivo:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def generar(n_total: int, semilla: int, incluir_originales: bool) -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    orig = cargar_originales()
    modelo = modelo_calibrado(orig)
    clf = modelo.named_steps["clf"]

    n_sint = n_total - (len(orig) if incluir_originales else 0)
    if n_sint < 0:
        raise SystemExit(f"--n debe ser ≥ {len(orig)} si se incluyen los originales")

    # reparto de cultivos proporcional al original (los restos se asignan por sorteo)
    prop = orig["cultivo"].value_counts(normalize=True).sort_index()
    cuotas = np.floor(prop.to_numpy() * n_sint).astype(int)
    for _ in range(n_sint - cuotas.sum()):
        cuotas[rng.integers(len(cuotas))] += 1

    bloques = []
    for cultivo, k in zip(prop.index, cuotas):
        if k == 0:
            continue
        sub = orig[orig["cultivo"] == cultivo]
        clima = muestrear_clima(sub, int(k), rng)
        clima.insert(0, "cultivo", cultivo)
        clima.insert(1, "ciudad", CIUDAD_POR_CULTIVO.get(cultivo, ""))
        # probabilidad del modelo + calibración del término independiente por cultivo
        logit = clf.decision_function(modelo.named_steps["pre"].transform(clima[NUMERICAS + ["cultivo"]]))
        tasa_obj = float((sub["resultado"] == "SI").mean())
        d = calibrar_desplazamiento(logit, tasa_obj)
        p = 1 / (1 + np.exp(-(logit + d)))
        clima["resultado"] = np.where(rng.random(len(p)) < p, "SI", "NO")
        bloques.append(clima)

    sint = pd.concat(bloques, ignore_index=True)
    sint = sint.sample(frac=1.0, random_state=semilla).reset_index(drop=True)   # barajar
    columnas = ["id", "cultivo", "ciudad", *NUMERICAS, "resultado"]
    if incluir_originales:
        base = orig[["cultivo", "ciudad", *NUMERICAS, "resultado"]]
        todo = pd.concat([base, sint], ignore_index=True)
    else:
        todo = sint
    todo.insert(0, "id", range(1, len(todo) + 1))
    return todo[columnas]


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera un dataset agroclimático sintético calibrado con los datos originales.")
    ap.add_argument("--n", type=int, default=1000, help="número total de filas (por defecto 1000)")
    ap.add_argument("--semilla", type=int, default=42)
    ap.add_argument("--salida", type=Path, default=SALIDA_PATH)
    ap.add_argument("--sin-originales", action="store_true", help="no conservar los 50 registros originales")
    args = ap.parse_args()

    df = generar(args.n, args.semilla, not args.sin_originales)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.salida, index=False)

    # procedencia del dataset (la lee procesar_datos.py y la muestra la página de resultados)
    n_orig = 0 if args.sin_originales else len(cargar_originales())
    meta = {
        "origen": "sintetico_calibrado",
        "descripcion": "Registros originales conservados más observaciones generadas a partir de ellos "
                       "(muestreo por cultivo de las variables climáticas y resultado sorteado con un modelo "
                       "ajustado a los datos originales).",
        "filas_totales": int(len(df)), "filas_originales": int(n_orig), "filas_generadas": int(len(df) - n_orig),
        "semilla": args.semilla, "generado_en": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "archivo_original": ORIGINAL_PATH.name,
    }
    meta_path = args.salida.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Procedencia registrada → {meta_path}")

    tasa = df.groupby("cultivo")["resultado"].apply(lambda s: round(float((s == "SI").mean()), 3)).to_dict()
    print(f"Dataset generado → {args.salida} ({len(df)} filas; semilla {args.semilla})")
    print(f"  cultivos : {df['cultivo'].value_counts().sort_index().to_dict()}")
    print(f"  SI / NO  : {int((df['resultado'] == 'SI').sum())} / {int((df['resultado'] == 'NO').sum())}"
          f"  (tasa global {(df['resultado'] == 'SI').mean():.3f})")
    print(f"  tasa SI por cultivo: {tasa}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
