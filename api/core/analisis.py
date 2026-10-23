"""
api/core/analisis.py — Analizador del dataset con varios tipos de algoritmos.

Cinco familias, cada una con varios algoritmos y sus métricas propias:

  1. Regresión (supervisado)        → predecir una variable numérica
     lineal · Ridge · Random Forest · Gradient Boosting           · MAE, RMSE, R²
  2. Clasificación (supervisado)    → asignar una categoría (SI/NO o cultivo)
     logística · árbol · Random Forest · SVM · Gradient Boosting  · precision, recall, F1, ROC-AUC
  3. Clustering (no supervisado)    → descubrir grupos sin etiquetas
     K-Means · DBSCAN · jerárquico                                 · silhouette, Davies–Bouldin
  4. Detección de anomalías         → registros inusuales
     Isolation Forest · LOF · z-score                              · precision / recall si hay anomalías etiquetadas
  5. Series temporales              → tendencia y pronóstico
     media móvil · suavizado exponencial · Holt · ARIMA · regresión con variables temporales · MAE, RMSE, MAPE

Todo devuelve diccionarios JSON-serializables (sin numpy) para `/api/analisis/*`
y para la CLI `analizar_datos.py`. Los cálculos son deterministas (semilla fija).
"""

from __future__ import annotations

import hashlib
import math
import time
import warnings
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, AgglomerativeClustering, KMeans
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.ensemble import (GradientBoostingClassifier, GradientBoostingRegressor, IsolationForest,
                              RandomForestClassifier, RandomForestRegressor)
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge
from sklearn.metrics import (accuracy_score, adjusted_rand_score, confusion_matrix, davies_bouldin_score, f1_score,
                             mean_absolute_error, mean_squared_error, precision_score, r2_score, recall_score,
                             roc_auc_score, roc_curve, silhouette_score)
from sklearn.model_selection import KFold, StratifiedKFold, cross_validate, train_test_split
from sklearn.neighbors import LocalOutlierFactor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

try:  # statsmodels es opcional: sin él, Holt usa una implementación propia y ARIMA se declara no disponible
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.holtwinters import Holt

    STATSMODELS = True
except ImportError:  # pragma: no cover
    STATSMODELS = False

NUMERICAS = ["temperatura", "humedad", "radiacion_solar", "precipitacion", "viento"]
UNIDADES = {"temperatura": "°C", "humedad": "%", "radiacion_solar": "MJ/m²", "precipitacion": "mm", "viento": "km/h"}
ETIQUETAS = {"temperatura": "Temperatura", "humedad": "Humedad", "radiacion_solar": "Radiación solar",
             "precipitacion": "Precipitación", "viento": "Viento", "cultivo": "Cultivo (y su ciudad)"}
MINIMOS = {"temperatura": -10.0, "humedad": 0.0, "radiacion_solar": 0.0, "precipitacion": 0.0, "viento": 0.0}
MAXIMOS = {"temperatura": 50.0, "humedad": 100.0, "radiacion_solar": 45.0, "precipitacion": 200.0, "viento": 120.0}

# --------------------------------------------------------------------------- #
# Catálogo (lo consume la página para construir las tarjetas y los controles)
# --------------------------------------------------------------------------- #
CATALOGO: dict[str, dict[str, Any]] = {
    "regresion": {
        "orden": 1, "titulo": "Regresión", "subtitulo": "predecir valores numéricos", "aprendizaje": "Aprendizaje supervisado",
        "para_que": "Estima ventas, precios, demanda, temperaturas o valores futuros. Aquí: predecir una variable climática "
                    "a partir de las demás y del cultivo.",
        "algoritmos": [
            {"id": "lineal", "nombre": "Regresión lineal", "descripcion": "Suma ponderada de las variables: sencilla y fácil de explicar."},
            {"id": "ridge", "nombre": "Ridge", "descripcion": "Regresión lineal con freno (regularización) para no exagerar ningún coeficiente."},
            {"id": "random_forest", "nombre": "Random Forest Regressor", "descripcion": "Promedio de muchos árboles de decisión; capta relaciones no lineales."},
            {"id": "gradient_boosting", "nombre": "Gradient Boosting Regressor", "descripcion": "Árboles encadenados que corrigen los errores del anterior."},
        ],
        "metricas": [
            {"id": "mae", "nombre": "MAE", "descripcion": "Error medio en las unidades de la variable: cuánto se equivoca, en promedio, cada predicción."},
            {"id": "rmse", "nombre": "RMSE", "descripcion": "Parecido al MAE pero castiga más los errores grandes."},
            {"id": "r2", "nombre": "R²", "descripcion": "Parte de la variación que el modelo explica: 1 es perfecto, 0 equivale a predecir siempre el promedio."},
        ],
    },
    "clasificacion": {
        "orden": 2, "titulo": "Clasificación", "subtitulo": "asignar categorías", "aprendizaje": "Aprendizaje supervisado",
        "para_que": "Clasifica registros como fraude/no fraude, aprobado/rechazado o riesgo alto/medio/bajo. Aquí: resultado SI/NO "
                    "o el cultivo de cada registro.",
        "algoritmos": [
            {"id": "logistica", "nombre": "Regresión logística", "descripcion": "Modelo lineal que da una probabilidad; es el que usa el dashboard principal."},
            {"id": "arbol", "nombre": "Árbol de decisión", "descripcion": "Reglas encadenadas del tipo «si la temperatura supera X…»."},
            {"id": "random_forest", "nombre": "Random Forest", "descripcion": "Votación de muchos árboles entrenados con distintas muestras."},
            {"id": "svm", "nombre": "SVM", "descripcion": "Busca la frontera que separa mejor las clases, con un margen amplio."},
            {"id": "gradient_boosting", "nombre": "Gradient Boosting", "descripcion": "Árboles encadenados que corrigen los errores del anterior."},
        ],
        "metricas": [
            {"id": "precision", "nombre": "Precision", "descripcion": "De las veces que el modelo dice «SI», cuántas acierta."},
            {"id": "recall", "nombre": "Recall", "descripcion": "De todos los «SI» reales, cuántos detecta."},
            {"id": "f1", "nombre": "F1", "descripcion": "Equilibrio entre precision y recall en una sola cifra."},
            {"id": "roc_auc", "nombre": "ROC-AUC", "descripcion": "Capacidad de ordenar bien los casos: 0.5 es azar, 1 es perfecto."},
        ],
    },
    "clustering": {
        "orden": 3, "titulo": "Clustering", "subtitulo": "descubrir grupos", "aprendizaje": "Aprendizaje no supervisado",
        "para_que": "Agrupa clientes, documentos, productos o comportamientos similares sin necesitar etiquetas previas. Aquí: "
                    "agrupa los registros solo por su clima y comprueba si los grupos coinciden con los cultivos.",
        "algoritmos": [
            {"id": "kmeans", "nombre": "K-Means", "descripcion": "Reparte los registros en k grupos alrededor de k centros."},
            {"id": "dbscan", "nombre": "DBSCAN", "descripcion": "Forma grupos por densidad y deja fuera (ruido) los puntos aislados."},
            {"id": "jerarquico", "nombre": "Clustering jerárquico", "descripcion": "Une los registros más parecidos paso a paso hasta formar los grupos."},
        ],
        "metricas": [
            {"id": "silhouette", "nombre": "Silhouette", "descripcion": "De −1 a 1: cuanto más alto, más compactos y separados están los grupos."},
            {"id": "davies_bouldin", "nombre": "Davies–Bouldin", "descripcion": "Cuanto más bajo, mejor separados están los grupos."},
        ],
    },
    "anomalias": {
        "orden": 4, "titulo": "Detección de anomalías", "subtitulo": "encontrar comportamientos inusuales", "aprendizaje": "No supervisado",
        "para_que": "Identifica transacciones atípicas, errores de sensores, valores extremos o posibles fraudes. Aquí: registros con "
                    "un clima que no se parece al resto.",
        "algoritmos": [
            {"id": "isolation_forest", "nombre": "Isolation Forest", "descripcion": "Aísla cada registro con cortes aleatorios: los raros se aíslan con pocos cortes."},
            {"id": "lof", "nombre": "Local Outlier Factor (LOF)", "descripcion": "Compara la densidad de cada punto con la de sus vecinos."},
            {"id": "zscore", "nombre": "Desviación estándar (z-score)", "descripcion": "Marca los valores que se alejan más de N desviaciones del promedio."},
        ],
        "metricas": [
            {"id": "precision", "nombre": "Precision", "descripcion": "De los registros señalados, cuántos eran anomalías de verdad (solo con anomalías etiquetadas)."},
            {"id": "recall", "nombre": "Recall", "descripcion": "De las anomalías reales, cuántas se detectaron (solo con anomalías etiquetadas)."},
        ],
    },
    "series": {
        "orden": 5, "titulo": "Series temporales", "subtitulo": "analizar y pronosticar tendencias", "aprendizaje": "Pronóstico",
        "para_que": "Predice demanda, ventas, producción, temperatura o carga de trabajo a partir del historial temporal. Aquí: la "
                    "actividad de predicciones del sistema, una variable del dataset en orden de registro o una serie simulada.",
        "algoritmos": [
            {"id": "media_movil", "nombre": "Media móvil", "descripcion": "Promedio de los últimos N valores."},
            {"id": "suavizado", "nombre": "Suavizado exponencial", "descripcion": "Promedio que da más peso a lo reciente (nivel)."},
            {"id": "holt", "nombre": "Holt (nivel + tendencia)", "descripcion": "Suavizado exponencial que además sigue la tendencia."},
            {"id": "arima", "nombre": "ARIMA", "descripcion": "Modelo clásico que combina autorregresión, diferenciación y medias móviles."},
            {"id": "regresion_temporal", "nombre": "Regresión con variables temporales", "descripcion": "Regresión sobre el tiempo, los valores anteriores y la estacionalidad."},
        ],
        "metricas": [
            {"id": "mae", "nombre": "MAE", "descripcion": "Error medio del pronóstico en las unidades de la serie."},
            {"id": "rmse", "nombre": "RMSE", "descripcion": "Como el MAE pero castiga más los errores grandes."},
            {"id": "mape", "nombre": "MAPE", "descripcion": "Error medio en porcentaje (solo cuando la serie no tiene ceros)."},
        ],
    },
}


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def _f(x: Any, nd: int = 4) -> float | None:
    """float redondeado o None si no es finito."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(v) else round(v, nd)


def limpiar(obj: Any) -> Any:
    """Convierte numpy/pandas a tipos nativos y NaN/inf a None (apto para JSON)."""
    if isinstance(obj, dict):
        return {str(k): limpiar(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [limpiar(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [limpiar(v) for v in obj.tolist()]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return v if math.isfinite(v) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _nombres_salida(pre: ColumnTransformer) -> list[str]:
    nombres = []
    for n in pre.get_feature_names_out():
        n = n.split("__", 1)[-1]
        nombres.append(n)
    return nombres


def nombre_variable(v: str) -> str:
    """Nombre legible para la lectura automática: temperatura → temperatura; cultivo_papa → cultivo papa."""
    if v in ETIQUETAS:
        return ETIQUETAS[v].lower()
    if v.startswith("cultivo_"):
        return "cultivo " + v.split("_", 1)[1]
    return v.replace("_", " ")


def _rmse(y, p) -> float:
    return float(math.sqrt(mean_squared_error(y, p)))


def _mape(y, p) -> float | None:
    y = np.asarray(y, float); p = np.asarray(p, float)
    mask = np.abs(y) > 1e-9
    if mask.sum() < max(3, 0.5 * len(y)):
        return None
    return float(np.mean(np.abs((y[mask] - p[mask]) / y[mask])) * 100)


def _submuestra(idx: np.ndarray, n: int, semilla: int) -> np.ndarray:
    if len(idx) <= n:
        return idx
    rng = np.random.default_rng(semilla)
    return np.sort(rng.choice(idx, size=n, replace=False))


# --------------------------------------------------------------------------- #
# Analizador
# --------------------------------------------------------------------------- #
class Analizador:
    def __init__(self, df: pd.DataFrame, semilla: int = 42):
        d = df.copy()
        d["cultivo"] = d["cultivo"].astype(str).str.strip().str.lower()
        d["resultado"] = d["resultado"].astype(str).str.strip().str.upper()
        if "id" not in d.columns:
            d.insert(0, "id", range(1, len(d) + 1))
        d = d.dropna(subset=NUMERICAS + ["cultivo", "resultado"]).reset_index(drop=True)
        self.df = d
        self.semilla = semilla
        self.huella = hashlib.md5(pd.util.hash_pandas_object(d[["id", "cultivo", "resultado"] + NUMERICAS], index=False).values.tobytes()).hexdigest()[:10]

    # ------------------------------------------------------------------ comunes
    def _cabecera(self, tipo: str, t0: float, **extra) -> dict:
        return {"tipo": tipo, "titulo": CATALOGO[tipo]["titulo"], "n_filas": int(len(self.df)), "huella_datos": self.huella,
                "semilla": self.semilla, "duracion_s": round(time.perf_counter() - t0, 2), **extra}

    @staticmethod
    def _rec(prioridad: str, accion: str, porque: str) -> dict:
        """Recomendación en lenguaje sencillo: prioridad alta / media / baja, qué hacer y en qué cifra se apoya."""
        return {"prioridad": prioridad, "accion": accion, "porque": porque}

    def _cv(self, n: int) -> KFold:
        return KFold(n_splits=n, shuffle=True, random_state=self.semilla)

    def _scv(self, n: int) -> StratifiedKFold:
        return StratifiedKFold(n_splits=n, shuffle=True, random_state=self.semilla)

    # ================================================================== 1. REGRESIÓN
    def regresion(self, objetivo: str = "temperatura", test_size: float = 0.25, cv_folds: int = 5) -> dict:
        t0 = time.perf_counter()
        if objetivo not in NUMERICAS:
            raise ValueError(f"objetivo debe ser una de {NUMERICAS}")
        feats = [c for c in NUMERICAS if c != objetivo]
        X = self.df[feats + ["cultivo"]]
        y = self.df[objetivo].astype(float)
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=test_size, random_state=self.semilla)

        def pre() -> ColumnTransformer:
            return ColumnTransformer([("num", StandardScaler(), feats), ("cat", OneHotEncoder(handle_unknown="ignore"), ["cultivo"])])

        modelos = {
            "lineal": LinearRegression(),
            "ridge": Ridge(alpha=1.0),
            "random_forest": RandomForestRegressor(n_estimators=200, min_samples_leaf=2, random_state=self.semilla, n_jobs=-1),
            "gradient_boosting": GradientBoostingRegressor(random_state=self.semilla),
        }
        base_pred = np.full(len(y_te), float(y_tr.mean()))
        base = {"nombre": "Predecir siempre el promedio", "mae": _f(mean_absolute_error(y_te, base_pred)), "rmse": _f(_rmse(y_te, base_pred)),
                "r2": _f(r2_score(y_te, base_pred))}
        idx_muestra = _submuestra(np.arange(len(y_te)), 200, self.semilla)
        resultados = {}
        nombres = {a["id"]: a["nombre"] for a in CATALOGO["regresion"]["algoritmos"]}
        for mid, est in modelos.items():
            pipe = Pipeline([("pre", pre()), ("m", est)])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                cv = cross_validate(pipe, X, y, cv=self._cv(cv_folds), scoring=["neg_mean_absolute_error", "neg_root_mean_squared_error", "r2"])
                pipe.fit(X_tr, y_tr)
            pred = pipe.predict(X_te)
            nombres_f = _nombres_salida(pipe.named_steps["pre"])
            m = pipe.named_steps["m"]
            if hasattr(m, "feature_importances_"):
                imp = [{"variable": n, "valor": _f(v), "signo": None} for n, v in zip(nombres_f, m.feature_importances_)]
                tipo_imp = "importancia"
            else:
                coef = np.asarray(m.coef_).ravel()
                tot = float(np.abs(coef).sum()) or 1.0
                imp = [{"variable": n, "valor": _f(abs(c) / tot), "signo": "+" if c >= 0 else "−", "coeficiente": _f(c)} for n, c in zip(nombres_f, coef)]
                tipo_imp = "coeficiente"
            imp.sort(key=lambda d: -(d["valor"] or 0))
            resid = y_te.values - pred
            resultados[mid] = {
                "nombre": nombres[mid],
                "mae": _f(mean_absolute_error(y_te, pred)), "rmse": _f(_rmse(y_te, pred)), "r2": _f(r2_score(y_te, pred)),
                "cv": {"mae": _f(-cv["test_neg_mean_absolute_error"].mean()), "mae_std": _f(cv["test_neg_mean_absolute_error"].std()),
                       "rmse": _f(-cv["test_neg_root_mean_squared_error"].mean()), "r2": _f(cv["test_r2"].mean()), "r2_std": _f(cv["test_r2"].std()), "folds": cv_folds},
                "importancia": imp, "tipo_importancia": tipo_imp,
                "dispersion": {"real": [_f(v, 2) for v in y_te.values[idx_muestra]], "pred": [_f(v, 2) for v in pred[idx_muestra]]},
                "residuos": {"media": _f(resid.mean(), 3), "desviacion": _f(resid.std(), 3), "max_abs": _f(np.abs(resid).max(), 2)},
            }
        ranking = sorted(resultados, key=lambda k: resultados[k]["mae"] if resultados[k]["mae"] is not None else 1e9)
        unidad = UNIDADES[objetivo]
        mejor = resultados[ranking[0]]
        peor = resultados[ranking[-1]]
        mejora = (1 - mejor["mae"] / base["mae"]) * 100 if base["mae"] else 0
        lectura = (
            f"Para predecir la {ETIQUETAS[objetivo].lower()} a partir del resto del clima y del cultivo, el mejor algoritmo fue "
            f"{mejor['nombre']} con un error medio (MAE) de {mejor['mae']:.2f} {unidad} y un R² de {mejor['r2']:.2f}; el que peor lo hizo, "
            f"{peor['nombre']}, se quedó en {peor['mae']:.2f} {unidad}. Predecir siempre el promedio daría un error de {base['mae']:.2f} {unidad}, "
            f"así que el mejor modelo lo reduce un {mejora:.0f} %. "
        )
        rango_mae = (peor["mae"] - mejor["mae"]) / (base["mae"] or 1)
        if rango_mae < 0.05:
            lectura += "Los cuatro algoritmos quedan muy parecidos: la relación entre variables es sencilla y los modelos más complejos no aportan mucho. "
        else:
            lectura += "Hay diferencias claras entre algoritmos: conviene quedarse con el mejor y comprobar que su validación cruzada lo confirma. "
        r2m = mejor["r2"] or 0
        lectura += ("Un R² por debajo de 0.3 indica que el clima restante explica poco esta variable; " if r2m < 0.3 else
                    "Un R² entre 0.3 y 0.7 indica una relación útil pero con bastante ruido; " if r2m < 0.7 else
                    "Un R² alto indica que esta variable se deduce bien de las demás; ")
        top = [d for d in mejor["importancia"][:2]]
        if top:
            lectura += "las variables que más pesan en el mejor modelo son " + " y ".join(nombre_variable(d["variable"]) for d in top) + "."
        recs = []
        nombre_obj = ETIQUETAS[objetivo].lower()
        if mejora < 10:
            recs.append(self._rec("alta", f"No usar estas predicciones de {nombre_obj}: quedarse con el promedio por cultivo",
                                  f"el mejor modelo solo reduce el error un {mejora:.0f} % frente a predecir el promedio."))
        elif r2m < 0.7:
            recs.append(self._rec("alta", f"Usar la predicción de {nombre_obj} solo como estimación orientativa, con un margen de ±{mejor['mae']:.1f} {unidad}",
                                  f"R² {r2m:.2f}: el modelo explica una parte de la variación, pero el error típico sigue siendo de {mejor['mae']:.2f} {unidad}."))
        else:
            recs.append(self._rec("media", f"La {nombre_obj} puede estimarse a partir del resto del clima cuando falte la medición",
                                  f"R² {r2m:.2f} y error medio de {mejor['mae']:.2f} {unidad}: una imputación razonable."))
        if rango_mae < 0.05:
            simple = next((resultados[k] for k in ("lineal", "ridge") if k in resultados), None)
            if simple:
                recs.append(self._rec("media", f"Quedarse con el algoritmo más simple ({simple['nombre']})",
                                      f"rinde prácticamente igual (MAE {simple['mae']:.2f} frente a {mejor['mae']:.2f} {unidad}) y es más fácil de explicar y mantener."))
        else:
            recs.append(self._rec("media", f"Adoptar {mejor['nombre']} solo si la validación cruzada confirma su ventaja",
                                  f"en validación cruzada su MAE es {mejor['cv']['mae']:.2f} ± {mejor['cv']['mae_std']:.2f} {unidad}; si el intervalo se solapa con el del siguiente, la diferencia no es fiable."))
        if top and any(str(d["variable"]).startswith("cultivo") for d in top):
            recs.append(self._rec("media", "Interpretar el resultado como «clima típico de cada zona», no como una ley física",
                                  "el cultivo (y por tanto la ciudad) está entre las variables que más pesan: el modelo aprende sobre todo el perfil climático de cada lugar."))
        if mejor["residuos"]["max_abs"] and mejor["residuos"]["max_abs"] > 3 * mejor["mae"]:
            recs.append(self._rec("baja", "Revisar los registros con mayor error de predicción",
                                  f"el error máximo ({mejor['residuos']['max_abs']:.1f} {unidad}) multiplica por {mejor['residuos']['max_abs']/mejor['mae']:.0f} al error medio: pueden ser mediciones atípicas o un patrón que el modelo no capta."))
        recs.append(self._rec("baja", f"Para mejorar la predicción de {nombre_obj}, añadir variables nuevas antes que algoritmos nuevos",
                              "los cuatro algoritmos parten de la misma información; el techo lo marcan los datos, no la técnica." if rango_mae < 0.05 else
                              "el salto entre algoritmos ya está aprovechado; el siguiente avance vendrá de información que hoy no se registra (fecha, altitud, suelo)."))
        return limpiar(self._cabecera("regresion", t0, objetivo=objetivo, unidad=unidad, variables=feats + ["cultivo"],
                                      n_train=int(len(y_tr)), n_test=int(len(y_te)), baseline=base, algoritmos=resultados, ranking=ranking,
                                      criterio_ranking="mae", lectura=lectura, recomendaciones=recs))

    # ================================================================== 2. CLASIFICACIÓN
    def clasificacion(self, objetivo: str = "resultado", test_size: float = 0.25, cv_folds: int = 5, umbral: float | None = None) -> dict:
        """`umbral=None` usa la decisión nativa de cada algoritmo (la misma que la validación cruzada);
        un umbral explícito (solo binario) se aplica sobre la probabilidad de SI."""
        t0 = time.perf_counter()
        if objetivo == "resultado":
            y = (self.df["resultado"] == "SI").astype(int).values
            clases = ["NO", "SI"]
            feats_num, feats_cat = NUMERICAS, ["cultivo"]
        elif objetivo == "cultivo":
            clases = sorted(self.df["cultivo"].unique().tolist())
            y = self.df["cultivo"].map({c: i for i, c in enumerate(clases)}).values
            feats_num, feats_cat = NUMERICAS, []
        else:
            raise ValueError("objetivo debe ser 'resultado' o 'cultivo'")
        binario = len(clases) == 2
        X = self.df[feats_num + feats_cat]
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=test_size, random_state=self.semilla, stratify=y)

        def pre() -> ColumnTransformer:
            trs = [("num", StandardScaler(), feats_num)]
            if feats_cat:
                trs.append(("cat", OneHotEncoder(handle_unknown="ignore"), feats_cat))
            return ColumnTransformer(trs)

        modelos = {
            "logistica": LogisticRegression(class_weight="balanced", max_iter=2000, random_state=self.semilla),
            "arbol": DecisionTreeClassifier(max_depth=5, class_weight="balanced", random_state=self.semilla),
            "random_forest": RandomForestClassifier(n_estimators=200, min_samples_leaf=2, class_weight="balanced_subsample", random_state=self.semilla, n_jobs=-1),
            "svm": SVC(probability=True, class_weight="balanced", random_state=self.semilla),
            "gradient_boosting": GradientBoostingClassifier(random_state=self.semilla),
        }
        avg = "binary" if binario else "macro"
        scoring = (["accuracy", "precision", "recall", "f1", "roc_auc"] if binario
                   else ["accuracy", "precision_macro", "recall_macro", "f1_macro", "roc_auc_ovr"])
        nombres = {a["id"]: a["nombre"] for a in CATALOGO["clasificacion"]["algoritmos"]}
        prevalencia = float(np.mean(y_te == 1)) if binario else None
        mayoritaria = int(np.bincount(y_te).argmax())
        base = {"nombre": f"Decir siempre «{clases[mayoritaria]}»", "accuracy": _f(np.mean(y_te == mayoritaria)),
                "precision": _f(prevalencia) if binario and mayoritaria == 1 else 0.0, "recall": 1.0 if (binario and mayoritaria == 1) else 0.0,
                "f1": None, "roc_auc": 0.5}
        if binario:
            base["siempre_si"] = {"precision": _f(prevalencia), "recall": 1.0, "f1": _f(2 * prevalencia / (1 + prevalencia)) if prevalencia else None}
        resultados = {}
        for mid, est in modelos.items():
            pipe = Pipeline([("pre", pre()), ("m", est)])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                cv = cross_validate(pipe, X, y, cv=self._scv(cv_folds), scoring=scoring)
                pipe.fit(X_tr, y_tr)
                proba = pipe.predict_proba(X_te)
                if binario:
                    p1 = proba[:, 1]
                    pred = (p1 >= umbral).astype(int) if umbral is not None else pipe.predict(X_te)
                    auc = roc_auc_score(y_te, p1)
                    fpr, tpr, _ = roc_curve(y_te, p1)
                    sel = np.unique(np.linspace(0, len(fpr) - 1, min(len(fpr), 60)).astype(int))
                    roc = {"fpr": [_f(v, 3) for v in fpr[sel]], "tpr": [_f(v, 3) for v in tpr[sel]]}
                else:
                    pred = proba.argmax(axis=1)
                    auc = roc_auc_score(y_te, proba, multi_class="ovr", average="macro")
                    roc = None
                perm = permutation_importance(pipe, X_te, y_te, scoring="f1" if binario else "f1_macro", n_repeats=8, random_state=self.semilla, n_jobs=1)
            cm = confusion_matrix(y_te, pred, labels=list(range(len(clases))))
            imp = sorted([{"variable": c, "valor": _f(max(v, 0.0)), "desviacion": _f(s)} for c, v, s in zip(X.columns, perm.importances_mean, perm.importances_std)],
                         key=lambda d: -(d["valor"] or 0))
            resultados[mid] = {
                "nombre": nombres[mid],
                "accuracy": _f(accuracy_score(y_te, pred)),
                "precision": _f(precision_score(y_te, pred, average=avg, zero_division=0)),
                "recall": _f(recall_score(y_te, pred, average=avg, zero_division=0)),
                "f1": _f(f1_score(y_te, pred, average=avg, zero_division=0)),
                "roc_auc": _f(auc),
                "cv": {k.replace("_macro", "").replace("_ovr", ""): _f(cv[f"test_{k}"].mean()) for k in scoring}
                      | {"f1_std": _f(cv[f"test_{'f1' if binario else 'f1_macro'}"].std()), "folds": cv_folds},
                "matriz": cm.tolist(), "roc": roc, "importancia": imp,
            }
        ranking = sorted(resultados, key=lambda k: -(resultados[k]["f1"] or 0))
        mejor = resultados[ranking[0]]
        peor = resultados[ranking[-1]]
        if binario:
            lectura = (
                f"Para distinguir SI de NO, el algoritmo con mejor equilibrio (F1) fue {mejor['nombre']}: detecta el {mejor['recall']*100:.0f} % de los SI "
                f"reales y acierta el {mejor['precision']*100:.0f} % de las veces que dice SI (ROC-AUC {mejor['roc_auc']:.2f}). "
                f"El peor en F1 fue {peor['nombre']} ({peor['f1']:.2f}). Decir siempre «NO» acertaría el {base['accuracy']*100:.0f} % de los casos "
                f"sin detectar ningún SI, por eso el acierto global engaña y conviene mirar recall y F1. "
            )
            bajos = [r["nombre"] for r in resultados.values() if (r["recall"] or 0) < 0.4]
            if bajos:
                lectura += ("Algunos algoritmos (" + ", ".join(bajos) + ") detectan pocos SI con su decisión estándar: con una clase tan minoritaria "
                            "tienden a predecir NO; bajar el umbral de decisión o dar más peso a los SI mejoraría su recall a costa de más falsas alarmas. ")
            aucs = [r["roc_auc"] for r in resultados.values() if r["roc_auc"] is not None]
            if max(aucs) - min(aucs) < 0.06:
                lectura += "En ROC-AUC todos quedan parecidos: la información disponible (clima + cultivo) marca el techo, no el algoritmo."
            else:
                lectura += f"En ROC-AUC el mejor es {max(resultados.values(), key=lambda r: r['roc_auc'] or 0)['nombre']}."
        else:
            lectura = (
                f"Para reconocer el cultivo solo por el clima, el mejor algoritmo fue {mejor['nombre']} con un acierto del {mejor['accuracy']*100:.0f} % "
                f"y un F1 (promedio de las {len(clases)} clases) de {mejor['f1']:.2f}; el peor, {peor['nombre']}, llegó a {peor['accuracy']*100:.0f} %. "
                f"Adivinar siempre la clase más frecuente acertaría el {base['accuracy']*100:.0f} %. "
                "Como cada cultivo tiene un clima característico, esta tarea es mucho más fácil que predecir SI/NO."
            )
        top = mejor["importancia"][:2]
        if top:
            lectura += " Las variables que más ayudan al mejor modelo son " + " y ".join(nombre_variable(d["variable"]) for d in top) + "."
        recs = []
        if binario:
            mejor_auc = max(resultados.values(), key=lambda r: r["roc_auc"] or 0)
            fp_por_tp = (mejor["matriz"][0][1] / mejor["matriz"][1][1]) if mejor["matriz"][1][1] else None
            if (mejor["precision"] or 0) < 0.5:
                recs.append(self._rec("alta", "Usar cualquiera de estos clasificadores como filtro de prioridades, nunca como decisión final",
                                      f"el mejor acierta el {mejor['precision']*100:.0f} % de sus avisos de SI"
                                      + (f": ≈ {fp_por_tp:.1f} falsas alarmas por cada SI detectado." if fp_por_tp is not None else ".")))
            recs.append(self._rec("alta", "Elegir el algoritmo por recall y F1, nunca por acierto global",
                                  f"decir siempre «NO» ya acierta el {base['accuracy']*100:.0f} %; un algoritmo con acierto alto y recall bajo no sirve para encontrar SI."))
            if bajos:
                recs.append(self._rec("media", "Bajar el umbral de decisión (o dar más peso a la clase SI) en " + ", ".join(bajos),
                                      "con la decisión estándar detectan menos del 40 % de los SI; su ROC-AUC indica que ordenan los casos mejor de lo que su umbral aprovecha."))
            if max(aucs) - min(aucs) < 0.06:
                recs.append(self._rec("media", "Invertir en información nueva antes que en algoritmos más complejos",
                                      f"todos quedan entre ROC-AUC {min(aucs):.2f} y {max(aucs):.2f}: el techo lo pone la información disponible (clima + cultivo), no la técnica."))
            else:
                recs.append(self._rec("media", f"Tomar {mejor_auc['nombre']} como candidato y ajustar su umbral según el coste de cada error",
                                      f"es el que mejor ordena los casos (ROC-AUC {mejor_auc['roc_auc']:.2f}); el umbral decide el equilibrio entre SI detectados y falsas alarmas."))
            recs.append(self._rec("media", "Antes de reemplazar el modelo en uso, comparar al candidato con él sobre la misma partición de prueba y en validación cruzada",
                                  f"{mejor['nombre']} obtiene F1 {mejor['f1']:.2f} en la prueba y {mejor['cv']['f1']:.2f} ± {mejor['cv']['f1_std']:.2f} en validación cruzada; solo una mejora estable justifica el cambio."))
            recs.append(self._rec("baja", "Reevaluar cuando cambie la proporción de SI",
                                  f"con {int((y_te == 1).sum())} SI entre {int(len(y_te))} registros de prueba, pocos casos nuevos pueden mover estas cifras."))
        else:
            cm_ = np.array(mejor["matriz"])
            off = [(cm_[i, j], i, j) for i in range(len(clases)) for j in range(len(clases)) if i != j]
            peor_par = max(off) if off else None
            recs.append(self._rec("alta", "No usar este análisis para decidir nada en producción: el cultivo ya se conoce",
                                  "es una comprobación de que el clima registrado es característico de cada cultivo y ciudad."))
            if (mejor["accuracy"] or 0) >= 0.8:
                recs.append(self._rec("media", "Probar el modelo SI/NO sin la variable cultivo y comparar",
                                      f"si el clima reconoce el cultivo el {mejor['accuracy']*100:.0f} % de las veces, parte de la información del cultivo ya está en el clima; medirlo evita atribuir al cultivo un efecto que es del clima."))
            if peor_par and peor_par[0] > 0:
                recs.append(self._rec("media", f"Revisar los registros de {clases[peor_par[1]]} que se confunden con {clases[peor_par[2]]}",
                                      f"es la confusión más frecuente ({int(peor_par[0])} casos en la prueba): pueden ser registros con clima atípico para su zona."))
            recs.append(self._rec("baja", "Registrar un mismo cultivo en más de una ciudad antes de sacar conclusiones sobre el cultivo",
                                  "hoy cultivo y ciudad son la misma información, así que «reconocer el cultivo» equivale a reconocer la ciudad."))
        return limpiar(self._cabecera("clasificacion", t0, objetivo=objetivo, clases=clases, binario=binario, umbral=umbral,
                                      variables=list(X.columns), n_train=int(len(y_tr)), n_test=int(len(y_te)),
                                      distribucion_test={clases[i]: int((y_te == i).sum()) for i in range(len(clases))},
                                      baseline=base, algoritmos=resultados, ranking=ranking, criterio_ranking="f1", lectura=lectura, recomendaciones=recs))

    # ================================================================== 3. CLUSTERING
    def clustering(self, k: int = 3, eps: float = 1.0, min_samples: int = 10, n_clusters: int = 3, enlace: str = "ward",
                   variables: list[str] | None = None) -> dict:
        t0 = time.perf_counter()
        vars_ = [v for v in (variables or NUMERICAS) if v in NUMERICAS] or NUMERICAS
        if enlace not in ("ward", "average", "complete", "single"):
            raise ValueError("enlace debe ser ward, average, complete o single")
        Xo = self.df[vars_].values.astype(float)
        X = StandardScaler().fit_transform(Xo)
        pca = PCA(n_components=2, random_state=self.semilla)
        coords = pca.fit_transform(X)
        etiq = {
            "kmeans": KMeans(n_clusters=k, n_init=10, random_state=self.semilla).fit_predict(X),
            "dbscan": DBSCAN(eps=eps, min_samples=min_samples).fit_predict(X),
            "jerarquico": AgglomerativeClustering(n_clusters=n_clusters, linkage=enlace).fit_predict(X),
        }
        cultivos = self.df["cultivo"].values
        si = (self.df["resultado"] == "SI").values
        nombres = {a["id"]: a["nombre"] for a in CATALOGO["clustering"]["algoritmos"]}
        resultados = {}
        for mid, lab in etiq.items():
            lab = np.asarray(lab)
            mask = lab >= 0
            grupos = sorted(set(lab[mask].tolist()))
            n_ruido = int((~mask).sum())
            sil = db = None
            if len(grupos) >= 2 and mask.sum() > len(grupos):
                sil = _f(silhouette_score(X[mask], lab[mask]))
                db = _f(davies_bouldin_score(X[mask], lab[mask]))
            ari = _f(adjusted_rand_score(cultivos[mask], lab[mask])) if len(grupos) >= 1 and mask.sum() else None
            perfiles = []
            pureza_total = 0
            for g in grupos:
                m = lab == g
                conteo = pd.Series(cultivos[m]).value_counts()
                dominante = str(conteo.index[0])
                pureza_total += int(conteo.iloc[0])
                perfiles.append({
                    "cluster": int(g), "tamano": int(m.sum()), "pct": _f(m.mean() * 100, 1),
                    "medias": {v: _f(self.df.loc[m, v].mean(), 2) for v in vars_},
                    "tasa_si": _f(si[m].mean(), 3), "cultivo_dominante": dominante, "pct_dominante": _f(conteo.iloc[0] / m.sum() * 100, 1),
                    "cultivos": {str(c): int(n) for c, n in conteo.items()},
                })
            if n_ruido:
                m = ~mask
                perfiles.append({"cluster": -1, "tamano": n_ruido, "pct": _f(m.mean() * 100, 1), "medias": {v: _f(self.df.loc[m, v].mean(), 2) for v in vars_},
                                 "tasa_si": _f(si[m].mean(), 3), "cultivo_dominante": None, "pct_dominante": None,
                                 "cultivos": {str(c): int(n) for c, n in pd.Series(cultivos[m]).value_counts().items()}, "ruido": True})
            resultados[mid] = {"nombre": nombres[mid], "n_clusters": len(grupos), "n_ruido": n_ruido, "silhouette": sil, "davies_bouldin": db,
                               "ari_cultivo": ari, "pureza_cultivo": _f(pureza_total / max(mask.sum(), 1), 3), "perfiles": perfiles}
        # barrido de k para K-Means (codo + silhouette)
        barrido = []
        for kk in range(2, 9):
            km = KMeans(n_clusters=kk, n_init=10, random_state=self.semilla).fit(X)
            barrido.append({"k": kk, "inercia": _f(km.inertia_, 1), "silhouette": _f(silhouette_score(X, km.labels_))})
        puntos = [{"x": _f(coords[i, 0], 3), "y": _f(coords[i, 1], 3), "cultivo": str(cultivos[i]), "si": bool(si[i]),
                   "kmeans": int(etiq["kmeans"][i]), "dbscan": int(etiq["dbscan"][i]), "jerarquico": int(etiq["jerarquico"][i])}
                  for i in range(len(self.df))]
        ranking = sorted(resultados, key=lambda m: -(resultados[m]["silhouette"] if resultados[m]["silhouette"] is not None else -9))
        mejor = resultados[ranking[0]]
        mejor_k = max(barrido, key=lambda b: b["silhouette"] or -1)
        lectura = (
            f"Agrupando los registros solo por su clima, el método con grupos más nítidos (silhouette) fue {mejor['nombre']} con "
            f"{mejor['n_clusters']} grupos y silhouette {mejor['silhouette']:.2f}" if mejor["silhouette"] is not None else
            f"Ningún método produjo al menos dos grupos evaluables con los parámetros actuales"
        )
        lectura += ". "
        if mejor.get("ari_cultivo") is not None:
            ari = mejor["ari_cultivo"]
            lectura += (f"Sus grupos coinciden {'mucho' if ari > 0.6 else 'parcialmente' if ari > 0.25 else 'poco'} con los cultivos (coincidencia ajustada {ari:.2f}; "
                        f"el {mejor['pureza_cultivo']*100:.0f} % de los registros cae en un grupo donde domina su propio cultivo)"
                        + (": el clima ya «sabe» de qué cultivo se trata aunque nadie se lo diga. " if ari > 0.4 else ". "))
        dbs = resultados["dbscan"]
        if dbs["n_clusters"] <= 1:
            lectura += (f"DBSCAN encontró {'un único grupo denso' if dbs['n_clusters'] == 1 else 'ningún grupo denso'} y dejó {dbs['n_ruido']} registros como ruido "
                        f"({dbs['n_ruido']/len(self.df)*100:.0f} %): en estos datos el clima forma una nube continua, sin huecos de densidad entre cultivos, así que "
                        "DBSCAN sirve aquí sobre todo para señalar registros aislados. Con un radio (eps) menor aparecen varios grupos, pero la mayoría de registros queda como ruido. ")
        elif dbs["n_ruido"]:
            lectura += (f"DBSCAN formó {dbs['n_clusters']} grupos y dejó {dbs['n_ruido']} registros como ruido ({dbs['n_ruido']/len(self.df)*100:.0f} %): puntos aislados que no "
                        "encajan en ningún grupo denso; con un radio (eps) mayor o menos vecinos mínimos los grupos serían más grandes. ")
        lectura += (f"El barrido de K-Means sugiere k = {mejor_k['k']} como número de grupos más natural (silhouette {mejor_k['silhouette']:.2f}); "
                    f"la curva de inercia muestra el «codo» a partir del cual añadir grupos aporta poco.")
        recs = []
        sil = mejor["silhouette"] if mejor["silhouette"] is not None else 0
        ari = mejor.get("ari_cultivo")
        if ari is not None and ari > 0.4:
            recs.append(self._rec("alta", "No esperar segmentos nuevos: los grupos reproducen en gran medida los cultivos y ciudades",
                                  f"coincidencia ajustada con el cultivo de {ari:.2f} y pureza del {mejor['pureza_cultivo']*100:.0f} %; el agrupamiento confirma que cada zona tiene un clima propio."))
        elif ari is not None:
            recs.append(self._rec("alta", "Describir cada grupo por su clima promedio antes de darle un nombre",
                                  f"los grupos coinciden poco con los cultivos (coincidencia ajustada {ari:.2f}): captan otra cosa, probablemente regímenes de clima que cruzan cultivos."))
        if sil < 0.25:
            recs.append(self._rec("media", "Tomar las fronteras entre grupos como orientativas",
                                  f"silhouette {sil:.2f}: los grupos se solapan; un registro cercano a la frontera podría caer en cualquiera de los dos."))
        if mejor_k["k"] != k:
            recs.append(self._rec("media", f"Repetir el análisis con k = {mejor_k['k']} grupos",
                                  f"es el número que produce los grupos más nítidos en el barrido (silhouette {mejor_k['silhouette']:.2f} frente a {resultados['kmeans']['silhouette']:.2f} con k = {k})."))
        if dbs["n_clusters"] <= 1:
            recs.append(self._rec("media", "Usar DBSCAN solo para detectar registros aislados; para segmentar, K-Means o el jerárquico",
                                  f"con los parámetros actuales DBSCAN no separa grupos y deja {dbs['n_ruido']} registros como ruido: el clima forma una nube continua."))
        else:
            recs.append(self._rec("media", f"Revisar los {dbs['n_ruido']} registros que DBSCAN deja como ruido",
                                  "son puntos que no encajan en ningún grupo denso: candidatos a anomalía o a error de medición."))
        recs.append(self._rec("baja", "Si los grupos se usan para algo (por ejemplo, reglas de riego por zona), fijar el método y los parámetros y no cambiarlos sin reevaluar",
                              "cada método y cada k produce una partición distinta; comparar resultados entre fechas exige la misma configuración."))
        return limpiar(self._cabecera("clustering", t0, variables=vars_, parametros={"k": k, "eps": eps, "min_samples": min_samples, "n_clusters": n_clusters, "enlace": enlace},
                                      varianza_pca=[_f(v, 3) for v in pca.explained_variance_ratio_], algoritmos=resultados, ranking=ranking,
                                      criterio_ranking="silhouette", barrido_kmeans=barrido, puntos=puntos, lectura=lectura, recomendaciones=recs))

    # ================================================================== 4. ANOMALÍAS
    def anomalias(self, contaminacion: float = 0.05, umbral_z: float = 3.0, vecinos: int = 20, inyectar: int = 0) -> dict:
        t0 = time.perf_counter()
        contaminacion = float(min(max(contaminacion, 0.005), 0.3))
        base = self.df[["id", "cultivo", "resultado"] + NUMERICAS].copy()
        base["inyectada"] = False
        if inyectar > 0:
            rng = np.random.default_rng(self.semilla)
            std = base[NUMERICAS].std()
            filas = []
            for j in range(int(inyectar)):
                f = base.iloc[int(rng.integers(len(base)))].copy()
                n_vars = int(rng.integers(1, 3))
                for v in rng.choice(NUMERICAS, size=n_vars, replace=False):
                    signo = 1 if rng.random() < 0.5 else -1
                    f[v] = float(np.clip(f[v] + signo * (4 + 3 * rng.random()) * std[v], MINIMOS[v], MAXIMOS[v]))
                    if abs(f[v] - base.iloc[0][v]) < 1e-9:  # si el recorte la devolvió al rango normal, empuja hacia el otro lado
                        f[v] = float(np.clip(f[v] - signo * (4 + 3 * rng.random()) * std[v], MINIMOS[v], MAXIMOS[v]))
                f["id"] = -(j + 1)
                f["inyectada"] = True
                filas.append(f)
            base = pd.concat([base, pd.DataFrame(filas)], ignore_index=True)
        X = base[NUMERICAS].values.astype(float)
        mu, sd = X.mean(axis=0), X.std(axis=0)
        sd[sd == 0] = 1.0
        Z = (X - mu) / sd
        Xs = Z
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            iso = IsolationForest(n_estimators=200, contamination=contaminacion, random_state=self.semilla).fit(Xs)
            iso_flag = iso.predict(Xs) == -1
            iso_score = -iso.score_samples(Xs)
            lof = LocalOutlierFactor(n_neighbors=int(vecinos), contamination=contaminacion)
            lof_flag = lof.fit_predict(Xs) == -1
            lof_score = -lof.negative_outlier_factor_
        zmax = np.abs(Z).max(axis=1)
        z_flag = zmax > umbral_z
        flags = {"isolation_forest": iso_flag, "lof": lof_flag, "zscore": z_flag}
        scores = {"isolation_forest": iso_score, "lof": lof_score, "zscore": zmax}
        pca = PCA(n_components=2, random_state=self.semilla)
        coords = pca.fit_transform(Xs)
        nombres = {a["id"]: a["nombre"] for a in CATALOGO["anomalias"]["algoritmos"]}
        var_principal = np.array(NUMERICAS)[np.abs(Z).argmax(axis=1)]
        etiq = base["inyectada"].values.astype(bool)
        resultados = {}
        for mid in flags:
            fl, sc = flags[mid], scores[mid]
            orden = np.argsort(-sc)
            top = []
            for i in orden[:15]:
                if not fl[i]:
                    continue
                r = base.iloc[i]
                top.append({"id": int(r["id"]), "cultivo": str(r["cultivo"]), "resultado": str(r["resultado"]), "inyectada": bool(r["inyectada"]),
                            "puntuacion": _f(sc[i], 3), "variable_principal": str(var_principal[i]), "z_principal": _f(Z[i].ravel()[NUMERICAS.index(var_principal[i])], 2),
                            **{v: _f(r[v], 1) for v in NUMERICAS}})
            por_cultivo = {str(c): int(n) for c, n in base.loc[fl, "cultivo"].value_counts().items()}
            por_variable = {str(c): int(n) for c, n in pd.Series(var_principal[fl]).value_counts().items()}
            ev = None
            if inyectar > 0:
                ev = {"precision": _f(precision_score(etiq, fl, zero_division=0)), "recall": _f(recall_score(etiq, fl, zero_division=0)),
                      "f1": _f(f1_score(etiq, fl, zero_division=0)), "detectadas": int((etiq & fl).sum()), "inyectadas": int(etiq.sum())}
            resultados[mid] = {"nombre": nombres[mid], "n_anomalias": int(fl.sum()), "pct": _f(fl.mean() * 100, 1), "por_cultivo": por_cultivo,
                               "por_variable": por_variable, "top": top, "evaluacion": ev,
                               "tasa_si_anomalias": _f((base.loc[fl, "resultado"] == "SI").mean(), 3) if fl.any() else None}
        ids = list(flags)
        coincidencias = {f"{a}|{b}": int((flags[a] & flags[b]).sum()) for i, a in enumerate(ids) for b in ids[i + 1:]}
        en_todos = int((iso_flag & lof_flag & z_flag).sum())
        en_alguno = int((iso_flag | lof_flag | z_flag).sum())
        puntos = [{"x": _f(coords[i, 0], 3), "y": _f(coords[i, 1], 3), "id": int(base.iloc[i]["id"]), "cultivo": str(base.iloc[i]["cultivo"]),
                   "isolation_forest": bool(iso_flag[i]), "lof": bool(lof_flag[i]), "zscore": bool(z_flag[i]), "inyectada": bool(etiq[i])}
                  for i in range(len(base))]
        n = len(base)
        lectura = (
            f"Isolation Forest y LOF se configuraron para señalar alrededor del {contaminacion*100:.0f} % de los registros como anómalos "
            f"({resultados['isolation_forest']['n_anomalias']} y {resultados['lof']['n_anomalias']} de {n}); la regla de desviación estándar "
            f"(|z| > {umbral_z:g}) marcó {resultados['zscore']['n_anomalias']}. {en_todos} registros fueron señalados por los tres métodos a la vez y "
            f"{en_alguno} por al menos uno: cuando varios métodos coinciden, la anomalía es más creíble. "
        )
        pv = resultados["isolation_forest"]["por_variable"]
        if pv:
            v_top = max(pv, key=pv.get)
            lectura += f"La variable que con más frecuencia hace «raro» a un registro es {ETIQUETAS[v_top].lower()}. "
        if inyectar > 0:
            mejor = max(resultados.values(), key=lambda r: r["evaluacion"]["f1"] or 0)
            lectura += (f"Con {inyectar} anomalías artificiales inyectadas (valores a más de 4 desviaciones del promedio), el método que mejor las recupera es "
                        f"{mejor['nombre']}: recall {mejor['evaluacion']['recall']*100:.0f} % y precision {mejor['evaluacion']['precision']*100:.0f} % "
                        f"(la precision baja porque también señala registros reales extremos, que cuentan como «falsas alarmas» aunque sean atípicos de verdad).")
        else:
            lectura += ("El dataset no tiene anomalías etiquetadas, así que no se puede medir precision ni recall reales; activa la inyección de anomalías "
                        "artificiales para evaluar cuántas recupera cada método.")
        recs = []
        if en_todos:
            recs.append(self._rec("alta", f"Revisar primero los {en_todos} registros señalados por los tres métodos a la vez",
                                  "cuando métodos distintos coinciden, la anomalía es mucho más creíble; son los mejores candidatos a error de medición o a caso excepcional."))
        else:
            recs.append(self._rec("alta", "Revisar primero los registros señalados por al menos dos métodos",
                                  "ningún registro fue marcado por los tres a la vez; la coincidencia entre dos ya los hace más creíbles que los señalados por uno solo."))
        recs.append(self._rec("alta", "Tratar las anomalías como casos a verificar, no a borrar",
                              f"{en_alguno} registros ({en_alguno/n*100:.0f} %) fueron señalados por algún método; borrarlos sin comprobar eliminaría también casos extremos reales, que son justamente los más informativos."))
        if pv:
            recs.append(self._rec("media", f"Comprobar cómo se mide y se carga la {ETIQUETAS[v_top].lower()}",
                                  "es la variable que con más frecuencia vuelve «raro» a un registro: un instrumento o una unidad distinta producirían exactamente ese patrón."))
        if inyectar > 0:
            recs.append(self._rec("media", f"Para valores fuera de rango, basta con {mejor['nombre']}",
                                  f"recupera el {mejor['evaluacion']['recall']*100:.0f} % de las anomalías artificiales; los métodos más complejos aportan sobre todo para anomalías de combinación (valores normales por separado pero raros juntos)."))
        else:
            recs.append(self._rec("media", "Activar la inyección de anomalías artificiales para comparar los métodos con una referencia",
                                  "sin anomalías confirmadas no se puede saber cuántas recupera cada método ni cuántas falsas alarmas genera."))
        recs.append(self._rec("media", "Convertir la detección en una comprobación automática al cargar datos nuevos (poner en cuarentena, no rechazar)",
                              f"hoy el proceso solo descarta valores vacíos o no numéricos; una regla de desviación (|z| > {umbral_z:g}) detectaría además los valores imposibles antes de que entren al modelo."))
        recs.append(self._rec("baja", f"Ajustar la proporción esperada de anomalías ({contaminacion*100:.0f} %) a la realidad del proceso",
                              "Isolation Forest y LOF marcan siempre aproximadamente esa proporción, haya o no anomalías: si se espera menos, bajarla reduce falsas alarmas."))
        return limpiar(self._cabecera("anomalias", t0, parametros={"contaminacion": contaminacion, "umbral_z": umbral_z, "vecinos": vecinos, "inyectar": inyectar},
                                      n_total=n, varianza_pca=[_f(v, 3) for v in pca.explained_variance_ratio_], algoritmos=resultados, ranking=ids,
                                      coincidencias=coincidencias, en_todos=en_todos, en_alguno=en_alguno, puntos=puntos, lectura=lectura, recomendaciones=recs))

    # ================================================================== 5. SERIES TEMPORALES
    # ---- construcción de series ----
    def serie_dataset(self, variable: str = "temperatura", bloque: int = 10) -> dict:
        if variable not in NUMERICAS:
            raise ValueError(f"variable debe ser una de {NUMERICAS}")
        bloque = int(max(1, bloque))
        d = self.df.sort_values("id").reset_index(drop=True)
        vals = d[variable].values.astype(float)
        if bloque > 1:
            n_b = len(vals) // bloque
            vals_b = vals[: n_b * bloque].reshape(n_b, bloque).mean(axis=1)
            etiquetas = [f"Reg. {i*bloque+1}–{(i+1)*bloque}" for i in range(n_b)]
            vals = vals_b
        else:
            etiquetas = [f"Reg. {int(i)}" for i in d["id"].values]
        return {"valores": [_f(v, 3) for v in vals], "etiquetas": etiquetas, "unidad": UNIDADES[variable],
                "descripcion": f"{ETIQUETAS[variable]} del dataset en orden de registro" + (f", promediada en bloques de {bloque} registros" if bloque > 1 else ""),
                "nota": "El dataset no tiene fecha: el eje temporal es el orden de registro, no un calendario real.", "fuente": "dataset"}

    def serie_simulada(self, variable: str = "temperatura", n: int = 120, tendencia: float = 1.0, amplitud: float = 1.0,
                       periodo: int = 12, ruido: float = 0.5, semilla: int | None = None) -> dict:
        if variable not in NUMERICAS:
            raise ValueError(f"variable debe ser una de {NUMERICAS}")
        n = int(min(max(n, 24), 1000))
        rng = np.random.default_rng(self.semilla if semilla is None else semilla)
        mu = float(self.df[variable].mean()); sd = float(self.df[variable].std()) or 1.0
        t = np.arange(n)
        y = mu + sd * (tendencia * t / max(n - 1, 1) + amplitud * np.sin(2 * np.pi * t / max(periodo, 2)) + ruido * rng.standard_normal(n))
        y = np.clip(y, MINIMOS[variable], MAXIMOS[variable])
        return {"valores": [_f(v, 3) for v in y], "etiquetas": [f"Periodo {i+1}" for i in range(n)], "unidad": UNIDADES[variable],
                "descripcion": f"Serie simulada de {ETIQUETAS[variable].lower()} ({n} periodos) con tendencia, estacionalidad de {periodo} periodos y ruido, "
                               f"calibrada con el promedio y la dispersión del dataset",
                "nota": "Serie generada a propósito para mostrar cómo responden los métodos cuando hay tendencia y estacionalidad: no son mediciones.",
                "fuente": "simulada"}

    @staticmethod
    def serie_predicciones(filas: list[dict], medida: str = "conteo", intervalo: str = "minuto", max_puntos: int = 300) -> dict:
        """filas: dicts con ts (ISO), prediccion (0/1), probabilidad_si y latencia_ms (opcional)."""
        if not filas:
            raise ValueError("No hay predicciones registradas todavía")
        d = pd.DataFrame(filas)
        d["ts"] = pd.to_datetime(d["ts"], utc=True, errors="coerce")
        d = d.dropna(subset=["ts"]).sort_values("ts")
        reglas = {"minuto": ("min", "minuto"), "10min": ("10min", "10 minutos"), "hora": ("h", "hora"), "dia": ("D", "día")}
        regla, nombre_int = reglas.get(intervalo, reglas["minuto"])
        g = d.set_index("ts")
        if medida == "conteo":
            s = g["prediccion"].resample(regla).size().astype(float)
            s = s[s.index >= s[s > 0].index.min()] if (s > 0).any() else s
            unidad, desc = "predicciones", f"Número de predicciones registradas por {nombre_int} (los intervalos sin actividad cuentan 0)"
        elif medida == "tasa_si":
            s = g["prediccion"].resample(regla).mean().dropna()
            unidad, desc = "proporción de SI", f"Proporción de predicciones SI por {nombre_int} (solo intervalos con actividad)"
        elif medida == "latencia" and "latencia_ms" in g.columns:
            s = pd.to_numeric(g["latencia_ms"], errors="coerce").resample(regla).mean().dropna()
            unidad, desc = "ms", f"Tiempo medio de respuesta por {nombre_int} (solo intervalos con actividad)"
        else:
            s = g["probabilidad_si"].resample(regla).mean().dropna()
            unidad, desc = "probabilidad media", f"Probabilidad media de SI por {nombre_int} (solo intervalos con actividad)"
        if len(s) > max_puntos:
            s = s.iloc[-max_puntos:]
        fmt = "%d/%m %H:%M" if intervalo != "dia" else "%d/%m/%Y"
        return {"valores": [_f(v, 4) for v in s.values], "etiquetas": [ts.strftime(fmt) for ts in s.index], "unidad": unidad, "descripcion": desc,
                "nota": "Historial real del servicio: la actividad depende de cuándo estuvo en marcha, por eso puede ser irregular.", "fuente": "predicciones"}

    # ---- motor de pronóstico ----
    def serie(self, valores: list[float], etiquetas: list[str] | None = None, test_frac: float = 0.2, ventana: int = 5, alpha: float = 0.3,
              arima: tuple[int, int, int] = (1, 1, 1), lags: int = 3, periodo: int = 0, futuro: int | None = None, meta: dict | None = None) -> dict:
        t0 = time.perf_counter()
        y = np.asarray([np.nan if v is None else float(v) for v in valores], float)
        y = pd.Series(y).interpolate(limit_direction="both").values
        n = len(y)
        if n < 20:
            raise ValueError(f"La serie necesita al menos 20 puntos (tiene {n})")
        etiquetas = list(etiquetas) if etiquetas else [str(i + 1) for i in range(n)]
        n_test = int(min(max(4, round(n * test_frac)), n // 2))
        tr, te = y[:-n_test], y[-n_test:]
        h = n_test
        futuro = int(futuro if futuro else min(max(4, round(n * 0.1)), 50))
        ventana = int(min(max(1, ventana), len(tr)))
        alpha = float(min(max(alpha, 0.01), 0.99))
        lags = int(min(max(1, lags), max(1, len(tr) // 4)))
        periodo = int(periodo or 0)
        nombres = {a["id"]: a["nombre"] for a in CATALOGO["series"]["algoritmos"]}

        def metricas(p):
            p = np.asarray(p, float)
            return {"mae": _f(mean_absolute_error(te, p)), "rmse": _f(_rmse(te, p)), "mape": _f(_mape(te, p), 2)}

        resultados: dict[str, dict] = {}

        # --- media móvil ---
        def media_movil(serie: np.ndarray, hh: int):
            ajuste = [None] * len(serie)
            for i in range(ventana, len(serie)):
                ajuste[i] = float(np.mean(serie[i - ventana:i]))
            pron = np.full(hh, float(np.mean(serie[-ventana:])))
            return ajuste, pron
        aj, pr = media_movil(tr, h)
        _, fut = media_movil(y, futuro)
        resultados["media_movil"] = {"nombre": nombres["media_movil"], **metricas(pr), "ajuste": aj, "pronostico_test": pr.tolist(), "futuro": fut.tolist(),
                                     "detalle": {"ventana": ventana}, "error": None}

        # --- suavizado exponencial simple ---
        def ses(serie: np.ndarray, hh: int):
            nivel = float(serie[0]); ajuste = [None]
            for v in serie[1:]:
                ajuste.append(nivel)
                nivel = alpha * float(v) + (1 - alpha) * nivel
            return ajuste, np.full(hh, nivel)
        aj, pr = ses(tr, h)
        _, fut = ses(y, futuro)
        resultados["suavizado"] = {"nombre": nombres["suavizado"], **metricas(pr), "ajuste": aj, "pronostico_test": pr.tolist(), "futuro": fut.tolist(),
                                   "detalle": {"alpha": alpha}, "error": None}

        # --- Holt ---
        def holt(serie: np.ndarray, hh: int):
            if STATSMODELS and len(serie) >= 10:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    res = Holt(serie, initialization_method="estimated").fit(optimized=True)
                return [float(v) for v in res.fittedvalues], np.asarray(res.forecast(hh), float), \
                    {"alpha": _f(res.params.get("smoothing_level"), 3), "beta": _f(res.params.get("smoothing_trend"), 3), "tendencia_por_periodo": _f(res.params.get("initial_trend"), 4)}
            nivel, tend = float(serie[0]), float(serie[1] - serie[0]) if len(serie) > 1 else 0.0
            beta = 0.1; ajuste = [None]
            for v in serie[1:]:
                ajuste.append(nivel + tend)
                nuevo = alpha * float(v) + (1 - alpha) * (nivel + tend)
                tend = beta * (nuevo - nivel) + (1 - beta) * tend
                nivel = nuevo
            return ajuste, np.array([nivel + (i + 1) * tend for i in range(hh)]), {"alpha": alpha, "beta": beta}
        try:
            aj, pr, det = holt(tr, h)
            _, fut, _ = holt(y, futuro)
            resultados["holt"] = {"nombre": nombres["holt"], **metricas(pr), "ajuste": aj, "pronostico_test": pr.tolist(), "futuro": fut.tolist(), "detalle": det, "error": None}
        except Exception as exc:  # noqa: BLE001
            resultados["holt"] = {"nombre": nombres["holt"], "mae": None, "rmse": None, "mape": None, "ajuste": None, "pronostico_test": None, "futuro": None, "detalle": {}, "error": str(exc)}

        # --- ARIMA ---
        p_, d_, q_ = (int(max(0, min(5, v))) for v in arima)
        if not STATSMODELS:
            resultados["arima"] = {"nombre": nombres["arima"], "mae": None, "rmse": None, "mape": None, "ajuste": None, "pronostico_test": None, "futuro": None,
                                   "detalle": {"orden": [p_, d_, q_]}, "error": "ARIMA no disponible en este servidor (falta el paquete statsmodels)."}
        else:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    res = ARIMA(tr, order=(p_, d_, q_)).fit()
                    pr = np.asarray(res.forecast(h), float)
                    aj = [None if i < max(d_, 1) else float(v) for i, v in enumerate(res.fittedvalues)]
                    res_full = ARIMA(y, order=(p_, d_, q_)).fit()
                    fut = np.asarray(res_full.forecast(futuro), float)
                resultados["arima"] = {"nombre": nombres["arima"], **metricas(pr), "ajuste": aj, "pronostico_test": pr.tolist(), "futuro": fut.tolist(),
                                       "detalle": {"orden": [p_, d_, q_], "aic": _f(res.aic, 1)}, "error": None}
            except Exception as exc:  # noqa: BLE001
                resultados["arima"] = {"nombre": nombres["arima"], "mae": None, "rmse": None, "mape": None, "ajuste": None, "pronostico_test": None, "futuro": None,
                                       "detalle": {"orden": [p_, d_, q_]}, "error": f"ARIMA({p_},{d_},{q_}) no pudo ajustarse: {exc}"}

        # --- regresión con variables temporales (tendencia + retardos + estacionalidad) ---
        usa_estacion = periodo >= 2 and len(tr) >= 2 * periodo

        def feats(t_idx: np.ndarray, prev: np.ndarray) -> np.ndarray:
            cols = [t_idx.astype(float)]
            cols += [prev[:, j] for j in range(lags)]
            if usa_estacion:
                fase = t_idx % periodo
                cols += [(fase == s).astype(float) for s in range(1, periodo)]
            return np.column_stack(cols)

        def reg_temporal(serie: np.ndarray, hh: int):
            m = len(serie)
            t_idx = np.arange(lags, m)
            prev = np.column_stack([serie[lags - j - 1: m - j - 1] for j in range(lags)])
            Xr = feats(t_idx, prev)
            modelo = Pipeline([("sc", StandardScaler()), ("m", Ridge(alpha=1.0))]).fit(Xr, serie[lags:])
            ajuste = [None] * lags + [float(v) for v in modelo.predict(Xr)]
            hist = list(serie)
            pron = []
            for k in range(hh):
                t_k = np.array([m + k])
                prev_k = np.array([[hist[-1 - j] for j in range(lags)]])
                v = float(modelo.predict(feats(t_k, prev_k))[0])
                pron.append(v); hist.append(v)
            coef_t = float(modelo.named_steps["m"].coef_[0] / (modelo.named_steps["sc"].scale_[0] or 1))
            return ajuste, np.array(pron), coef_t
        try:
            aj, pr, coef_t = reg_temporal(tr, h)
            _, fut, _ = reg_temporal(y, futuro)
            resultados["regresion_temporal"] = {"nombre": nombres["regresion_temporal"], **metricas(pr), "ajuste": aj, "pronostico_test": pr.tolist(), "futuro": fut.tolist(),
                                                "detalle": {"lags": lags, "estacionalidad": periodo if usa_estacion else 0, "tendencia_por_periodo": _f(coef_t, 4)}, "error": None}
        except Exception as exc:  # noqa: BLE001
            resultados["regresion_temporal"] = {"nombre": nombres["regresion_temporal"], "mae": None, "rmse": None, "mape": None, "ajuste": None, "pronostico_test": None,
                                                "futuro": None, "detalle": {}, "error": str(exc)}

        # --- referencias ---
        naive = np.full(h, float(tr[-1])); media = np.full(h, float(tr.mean()))
        baselines = {"ultimo_valor": {"nombre": "Repetir el último valor", **metricas(naive)}, "promedio": {"nombre": "Promedio histórico", **metricas(media)}}

        validos = [m for m in resultados if resultados[m]["mae"] is not None]
        ranking = sorted(validos, key=lambda m: resultados[m]["mae"]) + [m for m in resultados if m not in validos]
        mejor = resultados[ranking[0]] if validos else None
        unidad = (meta or {}).get("unidad", "")
        lectura = ""
        if mejor:
            ref = min(baselines.values(), key=lambda b: b["mae"])
            lectura = (f"Se reservaron los últimos {h} puntos de la serie para comprobar los pronósticos. El método más preciso fue {mejor['nombre']} "
                       f"con un error medio (MAE) de {mejor['mae']:.3g} {unidad}".rstrip() + f"; la referencia más simple ({ref['nombre'].lower()}) daría {ref['mae']:.3g}. ")
            if mejor["mae"] >= ref["mae"] * 0.98:
                lectura += ("Ningún método supera claramente a la referencia simple: la serie no tiene una tendencia ni un patrón estable que aprovechar "
                            "(o el tramo de prueba es demasiado corto). ")
            else:
                lectura += f"El mejor método reduce el error un {(1 - mejor['mae']/ref['mae'])*100:.0f} % frente a esa referencia: hay estructura temporal aprovechable. "
            tend = resultados.get("regresion_temporal", {}).get("detalle", {}).get("tendencia_por_periodo")
            if tend is not None:
                lectura += (f"La tendencia estimada es de {tend:+.3g} {unidad} por periodo".rstrip() +
                            (" (prácticamente plana). " if abs(tend) * n < 0.05 * (abs(float(np.mean(y))) + 1e-9) else ". "))
            if usa_estacion:
                lectura += f"La regresión temporal incluye estacionalidad de {periodo} periodos. "
            errores = [resultados[m]["nombre"] for m in resultados if resultados[m]["error"]]
            if errores:
                lectura += "No se pudo calcular: " + ", ".join(errores) + "."
        recs = []
        fuente = (meta or {}).get("fuente", "")
        if mejor:
            ref = min(baselines.values(), key=lambda b: b["mae"])
            if mejor["mae"] >= ref["mae"] * 0.98:
                recs.append(self._rec("alta", f"No apoyar decisiones en pronósticos de esta serie: usar la referencia simple ({ref['nombre'].lower()})",
                                      f"ningún método reduce el error frente a ella (mejor MAE {mejor['mae']:.3g} frente a {ref['mae']:.3g} {unidad})."))
            else:
                recs.append(self._rec("alta", f"Usar {mejor['nombre']} solo para el corto plazo ({h} periodos, el tramo en que se comprobó)",
                                      f"reduce el error un {(1 - mejor['mae']/ref['mae'])*100:.0f} % frente a {ref['nombre'].lower()}; más allá del horizonte probado el error crece sin control."))
            tend = resultados.get("regresion_temporal", {}).get("detalle", {}).get("tendencia_por_periodo")
            if tend is not None and abs(tend) * n >= 0.05 * (abs(float(np.mean(y))) + 1e-9):
                recs.append(self._rec("media", "Vigilar la tendencia: si se mantiene, el modelo de predicción trabajará fuera de los rangos con los que se entrenó",
                                      f"tendencia estimada de {tend:+.3g} {unidad} por periodo".rstrip() + f"; acumulada sobre {n} periodos supone un desplazamiento apreciable."))
            if usa_estacion:
                recs.append(self._rec("media", f"Mantener la estacionalidad de {periodo} periodos en cualquier pronóstico",
                                      "la regresión temporal la aprovecha; los métodos que la ignoran quedan por detrás."))
        if fuente == "dataset":
            recs.append(self._rec("alta", "Añadir la fecha real a cada registro antes de sacar conclusiones temporales",
                                  "esta serie sigue el orden de registro, no un calendario: cualquier «tendencia» puede deberse al orden en que se cargaron los datos."))
        elif fuente == "simulada":
            recs.append(self._rec("media", "Usar esta serie solo para entender los métodos, no para decidir",
                                  "es una serie generada con tendencia y estacionalidad conocidas: sirve de banco de pruebas, no de medición."))
        elif fuente == "predicciones":
            recs.append(self._rec("media", "Interpretar los huecos y picos como actividad del servicio, no como fenómeno real",
                                  "la serie refleja cuándo estuvo en marcha el servicio (incluido el tráfico simulado); una caída a cero suele significar que estaba apagado."))
        recs.append(self._rec("baja", "Recalcular la comparación cuando la serie crezca",
                              f"con {h} puntos de prueba las diferencias entre métodos son frágiles; con más historia la elección será más fiable."))
        return limpiar(self._cabecera("series", t0, n=n, n_train=int(len(tr)), n_test=h, futuro=futuro, etiquetas=etiquetas, valores=[_f(v, 4) for v in y],
                                      meta=meta or {}, parametros={"test_frac": test_frac, "ventana": ventana, "alpha": alpha, "arima": [p_, d_, q_], "lags": lags, "periodo": periodo},
                                      baselines=baselines, algoritmos=resultados, ranking=ranking, criterio_ranking="mae", statsmodels=STATSMODELS, lectura=lectura, recomendaciones=recs))


def catalogo_publico(df: pd.DataFrame | None = None) -> dict:
    """Catálogo + opciones de variables para construir la interfaz."""
    tipos = []
    for tid, t in sorted(CATALOGO.items(), key=lambda kv: kv[1]["orden"]):
        tipos.append({"id": tid, **t})
    return {"tipos": tipos, "variables": [{"id": v, "nombre": ETIQUETAS[v], "unidad": UNIDADES[v]} for v in NUMERICAS],
            "objetivos_clasificacion": [{"id": "resultado", "nombre": "Resultado (SI / NO)"}, {"id": "cultivo", "nombre": "Cultivo (café / papa / uva)"}],
            "n_filas": int(len(df)) if df is not None else None, "statsmodels": STATSMODELS}
