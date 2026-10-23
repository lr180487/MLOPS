"""
app/gradio_app.py
-----------------
Interfaz web Gradio para el modelo `models/modelo.joblib`.

Pestañas
--------
1. Predicción           – formulario + probabilidad + gauge + contribución de variables
2. Métricas             – KPIs, matriz de confusión interactiva (hold-out / CV / umbral),
                          curva ROC, precision-recall, métricas vs. umbral
3. Mapas de calor       – correlación de Pearson, superficie de decisión P(SI),
                          promedios por cultivo (normalizados)
4. Exploración de datos – distribuciones, box plots, pares de variables, coeficientes
5. Monitoreo en vivo    – simulador de tráfico con métricas y matriz de confusión que se
                          actualizan cada 2 s (gr.Timer)
6. Datos                – tabla del dataset y resumen de procesar_datos.py

Ejecutar desde la raíz del proyecto:

    python app/gradio_app.py            # http://localhost:7860
"""

from __future__ import annotations

import json
import random
import time
from collections import deque
from pathlib import Path

import gradio as gr
import joblib
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sklearn.metrics import (
    accuracy_score,
    auc,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split

# --------------------------------------------------------------------------- #
# Rutas y artefactos
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "models" / "modelo.joblib"
METRICS_PATH = BASE_DIR / "models" / "metricas.json"
DATA_PATH = BASE_DIR / "data" / "datos.csv"
RESULT_PATH = BASE_DIR / "output" / "resultado.json"

FEATURES_NUM = ["temperatura", "humedad", "radiacion_solar", "precipitacion", "viento"]
FEATURE_CAT = "cultivo"
FEATURE_CIUDAD = "ciudad"          # variable predictora asociada 1:1 al cultivo
FEATURES_CAT = [FEATURE_CAT, FEATURE_CIUDAD]
COLUMNAS_MODELO = FEATURES_NUM + FEATURES_CAT
TARGET = "resultado"
LABELS = {
    "temperatura": "Temperatura (°C)",
    "humedad": "Humedad (%)",
    "radiacion_solar": "Radiación solar (MJ/m²)",
    "precipitacion": "Precipitación (mm)",
    "viento": "Viento (km/h)",
}
RANDOM_STATE = 42

modelo = joblib.load(MODEL_PATH)
metricas = json.loads(METRICS_PATH.read_text(encoding="utf-8")) if METRICS_PATH.exists() else {}
resumen = json.loads(RESULT_PATH.read_text(encoding="utf-8")) if RESULT_PATH.exists() else {}

# cafe → chanchamayo, papa → huancayo, uva → ica (se toma de metricas.json si el modelo lo registró)
CIUDAD_POR_CULTIVO = {str(k).lower(): str(v).lower() for k, v in
                      (metricas.get("ciudad_por_cultivo") or {"cafe": "chanchamayo", "papa": "huancayo", "uva": "ica"}).items()}


def ciudad_de(cultivo: str) -> str:
    return CIUDAD_POR_CULTIVO.get(str(cultivo).strip().lower(), "")


def con_ciudad(frame: pd.DataFrame) -> pd.DataFrame:
    """Garantiza la columna `ciudad` (deducida del cultivo) antes de llamar al modelo."""
    if FEATURE_CIUDAD not in frame.columns:
        frame = frame.copy()
        frame[FEATURE_CIUDAD] = frame[FEATURE_CAT].map(ciudad_de)
    return frame


def etiqueta_coef(nombre: str) -> str:
    if nombre in LABELS:
        return LABELS[nombre]
    if nombre.startswith("cultivo_"):
        return "cultivo = " + nombre[len("cultivo_"):]
    if nombre.startswith("ciudad_"):
        return "ciudad = " + nombre[len("ciudad_"):].capitalize()
    return nombre


df = pd.read_csv(DATA_PATH)
df[TARGET] = df[TARGET].astype(str).str.strip().str.upper()
df[FEATURE_CAT] = df[FEATURE_CAT].astype(str).str.strip().str.lower()
if FEATURE_CIUDAD not in df.columns:
    df.insert(df.columns.get_loc(FEATURE_CAT) + 1, FEATURE_CIUDAD, df[FEATURE_CAT].map(ciudad_de))
df[FEATURE_CIUDAD] = df[FEATURE_CIUDAD].astype(str).str.strip().str.lower()
df = df.dropna(subset=FEATURES_NUM + [FEATURE_CAT, TARGET]).reset_index(drop=True)
X = df[COLUMNAS_MODELO]
y = (df[TARGET] == "SI").astype(int).to_numpy()

CULTIVOS = metricas.get("categorias_cultivo") or sorted(df[FEATURE_CAT].unique().tolist())
RANGOS = metricas.get("rangos") or {f: [float(df[f].min()), float(df[f].max())] for f in FEATURES_NUM}
MEDIAS = metricas.get("medias_entrenamiento") or {f: float(df[f].mean()) for f in FEATURES_NUM}
DESV = metricas.get("desviaciones_entrenamiento") or {f: float(df[f].std()) for f in FEATURES_NUM}

# Reproducimos la misma partición del notebook para las probabilidades de hold-out
_, X_test, _, y_test = train_test_split(X, y, test_size=0.25, stratify=y, random_state=RANDOM_STATE)
P_HOLDOUT = modelo.predict_proba(X_test)[:, 1]
Y_HOLDOUT = np.asarray(y_test)

# Probabilidades out-of-fold (validación cruzada estratificada 5×)
_skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
P_CV = cross_val_predict(modelo, X, y, cv=_skf, method="predict_proba")[:, 1]
Y_CV = y

# Paleta corporativa (coherente con el dashboard HTML)
BRAND = "#2546e8"
GREEN, RED, VIOLET, AMBER, SLATE = "#059669", "#e11d48", "#7c3aed", "#d97706", "#64748b"
CULTIVO_COLORS = {"cafe": "#b45309", "papa": "#7c3aed", "uva": "#0e7490"}
PLOT_LAYOUT = dict(
    template="plotly_white",
    font=dict(family="Inter, Segoe UI, sans-serif", size=12, color="#334155"),
    margin=dict(l=40, r=20, t=50, b=40),
    paper_bgcolor="white",
    plot_bgcolor="white",
)


def _fig(fig: go.Figure, height: int = 380, **kw) -> go.Figure:
    """Aplica el layout base; los kwargs explícitos (p. ej. margin) tienen prioridad."""
    fig.update_layout(**{**PLOT_LAYOUT, "height": height, **kw})
    return fig


# --------------------------------------------------------------------------- #
# 1) PREDICCIÓN
# --------------------------------------------------------------------------- #
def _gauge(p_si: float, umbral: float) -> go.Figure:
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=round(p_si * 100, 1),
            number={"suffix": "%", "font": {"size": 40}},
            title={"text": "Probabilidad de SI", "font": {"size": 14}},
            gauge={
                "axis": {"range": [0, 100], "ticksuffix": "%"},
                "bar": {"color": VIOLET if p_si >= umbral else SLATE, "thickness": 0.28},
                "steps": [
                    {"range": [0, umbral * 100], "color": "#f1f5f9"},
                    {"range": [umbral * 100, 100], "color": "#ede9fe"},
                ],
                "threshold": {"line": {"color": RED, "width": 3}, "thickness": 0.9, "value": umbral * 100},
            },
        )
    )
    return _fig(fig, height=280, margin=dict(l=30, r=30, t=60, b=10))


def _contribuciones(entrada: pd.DataFrame) -> go.Figure:
    """Contribución de cada variable al logit (coeficiente × valor estandarizado/one-hot)."""
    pre = modelo.named_steps["pre"]
    clf = modelo.named_steps["clf"]
    z = pre.transform(entrada)
    z = z.toarray() if hasattr(z, "toarray") else z
    nombres = [str(n).replace("num__", "").replace("cat__", "") for n in pre.get_feature_names_out()]
    contrib = (clf.coef_[0] * z[0])
    orden = np.argsort(np.abs(contrib))
    fig = go.Figure(
        go.Bar(
            x=contrib[orden],
            y=[etiqueta_coef(n) for n in np.array(nombres)[orden]],
            orientation="h",
            marker_color=[GREEN if v >= 0 else RED for v in contrib[orden]],
            text=[f"{v:+.2f}" for v in contrib[orden]],
            textposition="outside",
        )
    )
    fig.add_vline(x=0, line_color="#94a3b8")
    return _fig(
        fig, height=320, title="Contribución al logit<br><sup>→ empuja hacia SI · ← hacia NO</sup>",
        xaxis_title="coeficiente × valor transformado", yaxis_title=None,
        margin=dict(l=10, r=40, t=50, b=40),
    )


def predecir(cultivo, temperatura, humedad, radiacion_solar, precipitacion, viento, umbral):
    entrada = pd.DataFrame([{
        "cultivo": cultivo, "ciudad": ciudad_de(cultivo), "temperatura": temperatura, "humedad": humedad,
        "radiacion_solar": radiacion_solar, "precipitacion": precipitacion, "viento": viento,
    }])
    p_si = float(modelo.predict_proba(entrada)[0, 1])
    etiqueta = "SI" if p_si >= umbral else "NO"
    color = VIOLET if etiqueta == "SI" else "#334155"
    detalle = f"""
<div style="border:1px solid #e6eaf0;border-radius:12px;padding:16px 20px;background:#fff">
  <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.06em">Predicción</div>
  <div style="font-size:40px;font-weight:700;color:{color};line-height:1.1">{etiqueta}</div>
  <div style="font-size:13px;color:#475569;margin-top:6px">
    Cultivo: <b>{cultivo}</b> · Ciudad: <b>{ciudad_de(cultivo).capitalize() or "—"}</b><br>
    P(SI) = <b>{p_si:.3f}</b> · P(NO) = <b>{1 - p_si:.3f}</b> · umbral = {umbral:.2f}<br>
    Modelo: {metricas.get('modelo', 'LogisticRegression')} v{metricas.get('version', '1.0.0')}
  </div>
</div>"""
    return {"SI": p_si, "NO": 1 - p_si}, detalle, _gauge(p_si, umbral), _contribuciones(entrada)


def fila_aleatoria():
    r = df.sample(1).iloc[0]
    return (r[FEATURE_CAT], float(r["temperatura"]), float(r["humedad"]), float(r["radiacion_solar"]),
            float(r["precipitacion"]), float(r["viento"]),
            f"Fila #{int(r['id'])} del dataset · resultado real: **{r[TARGET]}**")


# --------------------------------------------------------------------------- #
# 2) MÉTRICAS Y MATRIZ DE CONFUSIÓN
# --------------------------------------------------------------------------- #
def _conjunto(nombre: str):
    return (Y_HOLDOUT, P_HOLDOUT) if nombre.startswith("Hold-out") else (Y_CV, P_CV)


def _metricas_binarias(y_true, y_pred, p) -> dict:
    return {
        "Accuracy": accuracy_score(y_true, y_pred),
        "Precisión": precision_score(y_true, y_pred, zero_division=0),
        "Recall": recall_score(y_true, y_pred, zero_division=0),
        "F1-score": f1_score(y_true, y_pred, zero_division=0),
        "ROC-AUC": roc_auc_score(y_true, p) if len(np.unique(y_true)) > 1 else float("nan"),
    }


def _fig_matriz(cm: np.ndarray, titulo: str, normalizar: bool) -> go.Figure:
    total = cm.sum() or 1
    pct = cm / total
    z = pct if normalizar else cm
    texto = [[f"<b>{cm[i][j]}</b><br>{pct[i][j]:.0%}" for j in range(2)] for i in range(2)]
    fig = go.Figure(
        go.Heatmap(
            z=z, x=["Pred. NO", "Pred. SI"], y=["Real NO", "Real SI"],
            text=texto, texttemplate="%{text}", textfont={"size": 18},
            colorscale=[[0, "#eef2ff"], [1, BRAND]], showscale=normalizar,
            hovertemplate="%{y} / %{x}: %{z}<extra></extra>",
        )
    )
    # etiquetas TN/FP/FN/TP en la esquina de cada celda (color según la intensidad del fondo)
    zmax = float(np.max(z)) or 1.0
    for (i, j, tag) in [(0, 0, "TN"), (0, 1, "FP"), (1, 0, "FN"), (1, 1, "TP")]:
        oscuro = (z[i][j] / zmax) > 0.55
        fig.add_annotation(x=j - 0.44, y=i - 0.40, text=f"<b>{tag}</b>", showarrow=False, xanchor="left",
                           font=dict(size=11, color="#e0e7ff" if oscuro else "#475569"))
    fig.update_yaxes(autorange="reversed")
    return _fig(fig, height=380, title=titulo, xaxis_title="Predicción", yaxis_title="Real",
                title_font_size=14)


def _fig_roc(y_true, p, titulo: str) -> go.Figure:
    fpr, tpr, _ = roc_curve(y_true, p)
    a = auc(fpr, tpr)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=fpr, y=tpr, mode="lines+markers", name=f"ROC (AUC = {a:.3f})",
                             line=dict(color=BRAND, width=2.5), fill="tozeroy", fillcolor="rgba(37,70,232,.08)"))
    fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", name="Azar", line=dict(color="#94a3b8", dash="dash")))
    return _fig(fig, height=360, title=titulo, xaxis_title="FPR (1 − especificidad)", yaxis_title="TPR (recall)",
                legend=dict(x=0.55, y=0.08))


def _fig_pr(y_true, p, titulo: str) -> go.Figure:
    prec, rec, _ = precision_recall_curve(y_true, p)
    base = float(np.mean(y_true))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=rec, y=prec, mode="lines+markers", name=f"PR (AUC = {auc(rec, prec):.3f})",
                             line=dict(color=VIOLET, width=2.5, shape="hv")))
    fig.add_hline(y=base, line_dash="dash", line_color="#94a3b8", annotation_text=f"prevalencia {base:.2f}")
    return _fig(fig, height=360, title=titulo, xaxis_title="Recall", yaxis_title="Precisión",
                yaxis_range=[0, 1.05], legend=dict(x=0.55, y=0.92))


def _fig_umbral(y_true, p, umbral_actual: float) -> go.Figure:
    ts = np.linspace(0.05, 0.95, 91)
    series = {"Accuracy": [], "Precisión": [], "Recall": [], "F1-score": []}
    for t in ts:
        yp = (p >= t).astype(int)
        series["Accuracy"].append(accuracy_score(y_true, yp))
        series["Precisión"].append(precision_score(y_true, yp, zero_division=0))
        series["Recall"].append(recall_score(y_true, yp, zero_division=0))
        series["F1-score"].append(f1_score(y_true, yp, zero_division=0))
    colores = {"Accuracy": GREEN, "Precisión": AMBER, "Recall": RED, "F1-score": BRAND}
    fig = go.Figure()
    for k, v in series.items():
        fig.add_trace(go.Scatter(x=ts, y=v, mode="lines", name=k, line=dict(color=colores[k], width=2)))
    fig.add_vline(x=umbral_actual, line_dash="dash", line_color="#0f172a",
                  annotation_text=f"umbral {umbral_actual:.2f}", annotation_position="top")
    return _fig(fig, height=360, title="Métricas en función del umbral de decisión",
                xaxis_title="Umbral", yaxis_title="Valor", yaxis_range=[0, 1.05],
                legend=dict(orientation="h", y=-0.25))


def _fig_distribucion_probas(y_true, p, umbral: float) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=p[y_true == 0], name="Real NO", nbinsx=20, marker_color=SLATE, opacity=0.75))
    fig.add_trace(go.Histogram(x=p[y_true == 1], name="Real SI", nbinsx=20, marker_color=VIOLET, opacity=0.75))
    fig.add_vline(x=umbral, line_dash="dash", line_color="#0f172a")
    return _fig(fig, height=320, title="Distribución de P(SI) por clase real", barmode="overlay",
                xaxis_title="P(SI)", yaxis_title="Observaciones", xaxis_range=[0, 1])


def _kpis_html(m: dict, cm: np.ndarray, n: int, conjunto: str) -> str:
    (tn, fp), (fn, tp) = cm
    esp = tn / (tn + fp) if (tn + fp) else float("nan")
    items = [
        ("Accuracy", m["Accuracy"], GREEN), ("Precisión", m["Precisión"], AMBER), ("Recall", m["Recall"], RED),
        ("F1-score", m["F1-score"], BRAND), ("ROC-AUC", m["ROC-AUC"], VIOLET), ("Especificidad", esp, SLATE),
    ]
    cards = "".join(
        f'<div style="flex:1;min-width:120px;border:1px solid #e6eaf0;border-top:3px solid {c};border-radius:10px;'
        f'padding:10px 14px;background:#fff"><div style="font-size:11px;color:#64748b;text-transform:uppercase;'
        f'letter-spacing:.05em">{k}</div><div style="font-size:24px;font-weight:600;color:#0f172a">'
        f'{"—" if np.isnan(v) else f"{v:.1%}" if k != "ROC-AUC" else f"{v:.3f}"}</div></div>'
        for k, v, c in items
    )
    return (f'<div style="display:flex;gap:10px;flex-wrap:wrap">{cards}</div>'
            f'<p style="font-size:12px;color:#64748b;margin:8px 2px 0">{conjunto} · n = {n} · '
            f'TN={tn} FP={fp} FN={fn} TP={tp}</p>')


def actualizar_metricas(conjunto: str, umbral: float, normalizar: bool):
    y_true, p = _conjunto(conjunto)
    y_pred = (p >= umbral).astype(int)
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    m = _metricas_binarias(y_true, y_pred, p)
    tabla = pd.DataFrame({"Métrica": list(m.keys()), "Valor": [round(float(v), 4) for v in m.values()]})
    return (
        _kpis_html(m, cm, len(y_true), conjunto),
        _fig_matriz(cm, f"Matriz de confusión<br><sup>{conjunto} · umbral {umbral:.2f}</sup>", normalizar),
        _fig_roc(y_true, p, f"Curva ROC · {conjunto}"),
        _fig_pr(y_true, p, f"Curva Precision-Recall · {conjunto}"),
        _fig_umbral(y_true, p, umbral),
        _fig_distribucion_probas(y_true, p, umbral),
        tabla,
    )


# --------------------------------------------------------------------------- #
# 3) MAPAS DE CALOR
# --------------------------------------------------------------------------- #
def heatmap_correlacion(metodo: str) -> go.Figure:
    d = df[FEATURES_NUM].copy()
    d["resultado (SI=1)"] = y
    corr = d.corr(method=metodo.lower())
    etiquetas = [LABELS.get(c, c) for c in corr.columns]
    fig = go.Figure(
        go.Heatmap(
            z=corr.values, x=etiquetas, y=etiquetas, zmin=-1, zmax=1, colorscale="RdBu_r",
            text=np.round(corr.values, 2), texttemplate="%{text}", textfont={"size": 12},
            colorbar=dict(title="r"), hovertemplate="%{y} × %{x}<br>r = %{z:.3f}<extra></extra>",
        )
    )
    fig.update_yaxes(autorange="reversed")
    return _fig(fig, height=480, title=f"Matriz de correlación ({metodo})", margin=dict(l=40, r=20, t=50, b=80))


def heatmap_decision(cultivo: str, var_x: str, var_y: str, resolucion: int, mostrar_puntos: bool) -> go.Figure:
    if var_x == var_y:
        var_y = next(f for f in FEATURES_NUM if f != var_x)
    xs = np.linspace(RANGOS[var_x][0], RANGOS[var_x][1], resolucion)
    ys = np.linspace(RANGOS[var_y][0], RANGOS[var_y][1], resolucion)
    gx, gy = np.meshgrid(xs, ys)
    rejilla = pd.DataFrame({f: np.full(gx.size, MEDIAS[f]) for f in FEATURES_NUM})
    rejilla[var_x] = gx.ravel()
    rejilla[var_y] = gy.ravel()
    rejilla[FEATURE_CAT] = cultivo
    rejilla[FEATURE_CIUDAD] = ciudad_de(cultivo)
    z = modelo.predict_proba(rejilla[COLUMNAS_MODELO])[:, 1].reshape(resolucion, resolucion)

    fig = go.Figure()
    fig.add_trace(go.Heatmap(x=xs, y=ys, z=z, zmin=0, zmax=1, colorscale="Viridis", colorbar=dict(title="P(SI)"),
                             hovertemplate=f"{LABELS[var_x]}: %{{x:.1f}}<br>{LABELS[var_y]}: %{{y:.1f}}<br>P(SI) = %{{z:.3f}}<extra></extra>"))
    fig.add_trace(go.Contour(x=xs, y=ys, z=z, contours=dict(start=0.5, end=0.5, size=1, coloring="none"),
                             line=dict(color="white", width=2, dash="dash"), showscale=False, name="umbral 0.5",
                             hoverinfo="skip"))
    if mostrar_puntos:
        sub = df[df[FEATURE_CAT] == cultivo]
        for etiqueta, color, simbolo in [("NO", "white", "circle"), ("SI", "#f97316", "circle")]:
            s = sub[sub[TARGET] == etiqueta]
            fig.add_trace(go.Scatter(x=s[var_x], y=s[var_y], mode="markers", name=f"real {etiqueta}",
                                     marker=dict(color=color, size=10, symbol=simbolo, line=dict(color="#0f172a", width=1.2)),
                                     hovertemplate=f"id %{{text}}<br>{LABELS[var_x]}: %{{x}}<br>{LABELS[var_y]}: %{{y}}<extra>{etiqueta}</extra>",
                                     text=s["id"]))
    fijas = " · ".join(f"{LABELS[f].split(' (')[0]} = {MEDIAS[f]:.1f}" for f in FEATURES_NUM if f not in (var_x, var_y))
    return _fig(fig, height=520, title=f"Superficie de decisión · cultivo = {cultivo}<br><sup>Variables fijas en su media: {fijas}</sup>",
                xaxis_title=LABELS[var_x], yaxis_title=LABELS[var_y], legend=dict(orientation="h", y=-0.18))


def heatmap_cultivos() -> go.Figure:
    medias = df.groupby(FEATURE_CAT)[FEATURES_NUM].mean()
    norm = (medias - df[FEATURES_NUM].min()) / (df[FEATURES_NUM].max() - df[FEATURES_NUM].min())
    fig = go.Figure(
        go.Heatmap(
            z=norm.values, x=[LABELS[f] for f in FEATURES_NUM], y=medias.index.tolist(), colorscale="YlGnBu",
            zmin=0, zmax=1, text=np.round(medias.values, 1), texttemplate="%{text}", textfont={"size": 13},
            colorbar=dict(title="escala<br>0–1"), hovertemplate="%{y} · %{x}<br>media = %{text}<extra></extra>",
        )
    )
    return _fig(fig, height=300, title="Promedio de cada variable por cultivo (color normalizado 0–1 por columna)")


def heatmap_tasa_si(var_x: str, var_y: str, bins: int) -> go.Figure:
    """Tasa empírica de SI en celdas 2D del dataset (frecuencia observada, no del modelo)."""
    if var_x == var_y:
        var_y = next(f for f in FEATURES_NUM if f != var_x)
    d = df[[var_x, var_y]].copy()
    d["si"] = y
    d["bx"] = pd.cut(d[var_x], bins=bins)
    d["by"] = pd.cut(d[var_y], bins=bins)
    tasa = d.pivot_table(index="by", columns="bx", values="si", aggfunc="mean", observed=False)
    conteo = d.pivot_table(index="by", columns="bx", values="si", aggfunc="count", observed=False)
    fig = go.Figure(
        go.Heatmap(
            z=tasa.values, x=[f"{iv.left:.1f}–{iv.right:.1f}" for iv in tasa.columns],
            y=[f"{iv.left:.1f}–{iv.right:.1f}" for iv in tasa.index], zmin=0, zmax=1, colorscale="OrRd",
            text=conteo.values, texttemplate="n=%{text}", textfont={"size": 10},
            colorbar=dict(title="tasa SI"), hoverongaps=False,
            hovertemplate="%{x} × %{y}<br>tasa SI = %{z:.2f} (n=%{text})<extra></extra>",
        )
    )
    return _fig(fig, height=420, title="Tasa observada de SI por celda (datos reales)",
                xaxis_title=LABELS[var_x], yaxis_title=LABELS[var_y])


# --------------------------------------------------------------------------- #
# 4) EXPLORACIÓN DE DATOS
# --------------------------------------------------------------------------- #
def fig_distribuciones() -> go.Figure:
    fig = make_subplots(rows=2, cols=3, subplot_titles=[LABELS[f] for f in FEATURES_NUM] + ["Clase objetivo"])
    pos = [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2)]
    for (r, c), f in zip(pos, FEATURES_NUM):
        for etiqueta, color in [("NO", SLATE), ("SI", VIOLET)]:
            fig.add_trace(go.Histogram(x=df.loc[df[TARGET] == etiqueta, f], name=etiqueta, marker_color=color,
                                       opacity=0.7, nbinsx=12, legendgroup=etiqueta, showlegend=(f == "temperatura")),
                          row=r, col=c)
    conteo = df[TARGET].value_counts()
    fig.add_trace(go.Bar(x=conteo.index, y=conteo.values, marker_color=[SLATE if k == "NO" else VIOLET for k in conteo.index],
                         text=conteo.values, textposition="inside", textfont=dict(color="white", size=14), showlegend=False), row=2, col=3)
    return _fig(fig, height=560, title="Distribución de las variables según la clase real", barmode="overlay",
                legend=dict(orientation="h", y=-0.08))


def fig_boxplots(variable: str) -> go.Figure:
    fig = px.box(df, x=FEATURE_CAT, y=variable, color=TARGET, points="all",
                 color_discrete_map={"NO": SLATE, "SI": VIOLET}, category_orders={TARGET: ["NO", "SI"]},
                 labels={variable: LABELS[variable], FEATURE_CAT: "Cultivo", TARGET: "Resultado"})
    return _fig(fig, height=400, title=f"{LABELS[variable]} por cultivo y resultado")


def fig_scatter(var_x: str, var_y: str) -> go.Figure:
    if var_x == var_y:
        var_y = next(f for f in FEATURES_NUM if f != var_x)
    d = df.copy()
    d["P(SI) modelo"] = modelo.predict_proba(X)[:, 1]
    fig = px.scatter(d, x=var_x, y=var_y, color=FEATURE_CAT, symbol=TARGET, size="P(SI) modelo", size_max=18,
                     color_discrete_map=CULTIVO_COLORS, symbol_map={"NO": "circle-open", "SI": "circle"},
                     hover_data=["id", "P(SI) modelo"], labels={var_x: LABELS[var_x], var_y: LABELS[var_y]})
    return _fig(fig, height=460, title=f"{LABELS[var_x]} vs {LABELS[var_y]}<br><sup>color = cultivo · relleno = SI · tamaño = P(SI) del modelo</sup>")


def fig_coeficientes() -> go.Figure:
    coefs = metricas.get("coeficientes")
    if not coefs:
        pre, clf = modelo.named_steps["pre"], modelo.named_steps["clf"]
        coefs = {str(n).replace("num__", "").replace("cat__", ""): float(c) for n, c in zip(pre.get_feature_names_out(), clf.coef_[0])}
    s = pd.Series(coefs).sort_values()
    fig = go.Figure(go.Bar(x=s.values, y=[etiqueta_coef(k) for k in s.index],
                           orientation="h", marker_color=[GREEN if v >= 0 else RED for v in s.values],
                           text=[f"{v:+.3f}" for v in s.values], textposition="outside"))
    fig.add_vline(x=0, line_color="#94a3b8")
    return _fig(fig, height=380, title="Coeficientes de la regresión logística<br><sup>log-odds de SI · variables estandarizadas</sup>",
                xaxis_title="coeficiente", margin=dict(l=10, r=50, t=50, b=40))


def fig_radar_cultivos() -> go.Figure:
    medias = df.groupby(FEATURE_CAT)[FEATURES_NUM].mean()
    norm = (medias - df[FEATURES_NUM].min()) / (df[FEATURES_NUM].max() - df[FEATURES_NUM].min())
    fig = go.Figure()
    for cultivo, fila in norm.iterrows():
        vals = fila.tolist() + [fila.iloc[0]]
        fig.add_trace(go.Scatterpolar(r=vals, theta=[LABELS[f].split(" (")[0] for f in FEATURES_NUM] + [LABELS[FEATURES_NUM[0]].split(" (")[0]],
                                      name=cultivo, fill="toself", line=dict(color=CULTIVO_COLORS.get(cultivo)), opacity=0.8))
    return _fig(fig, height=400, title="Perfil agroclimático medio por cultivo (normalizado)",
                polar=dict(radialaxis=dict(range=[0, 1], showticklabels=False)), legend=dict(orientation="h", y=-0.1))


# --------------------------------------------------------------------------- #
# 5) MONITOREO EN VIVO (simulador)
# --------------------------------------------------------------------------- #
class Monitor:
    """Estado del simulador de tráfico: genera observaciones sintéticas etiquetadas."""

    WINDOW = 50

    def __init__(self) -> None:
        self.rng = random.Random()
        self.eventos: deque = deque(maxlen=400)
        self.serie: deque = deque(maxlen=150)
        self.activo = True
        self.inicio = time.time()

    def generar(self, n: int = 1) -> None:
        for _ in range(n):
            fila = df.iloc[self.rng.randrange(len(df))]
            obs = {FEATURE_CAT: str(fila[FEATURE_CAT]), FEATURE_CIUDAD: str(fila.get(FEATURE_CIUDAD) or ciudad_de(fila[FEATURE_CAT]))}
            for f in FEATURES_NUM:
                v = float(fila[f]) + self.rng.gauss(0, 0.15 * float(DESV[f] or 1.0))
                lo, hi = RANGOS[f]
                obs[f] = round(min(max(v, max(0.0, lo * 0.9)), hi * 1.1), 2)  # sin valores físicamente imposibles
            real = 1 if fila[TARGET] == "SI" else 0
            if self.rng.random() < 0.05:
                real = 1 - real
            t0 = time.perf_counter()
            p = float(modelo.predict_proba(con_ciudad(pd.DataFrame([obs])))[0, 1])
            lat = (time.perf_counter() - t0) * 1000
            self.eventos.append({"hora": time.strftime("%H:%M:%S"), **obs, "p_si": round(p, 3),
                                 "pred": int(p >= 0.5), "real": real, "latencia_ms": round(lat, 2)})
        self._punto()

    def _cm(self, eventos) -> np.ndarray:
        cm = np.zeros((2, 2), dtype=int)
        for e in eventos:
            cm[e["real"]][e["pred"]] += 1
        return cm

    def _punto(self) -> None:
        ventana = list(self.eventos)[-self.WINDOW:]
        if not ventana:
            return
        yt = np.array([e["real"] for e in ventana]); yp = np.array([e["pred"] for e in ventana])
        self.serie.append({"t": time.strftime("%H:%M:%S"), "accuracy": accuracy_score(yt, yp),
                           "f1": f1_score(yt, yp, zero_division=0), "recall": recall_score(yt, yp, zero_division=0),
                           "precision": precision_score(yt, yp, zero_division=0)})

    def reiniciar(self) -> None:
        self.eventos.clear(); self.serie.clear(); self.inicio = time.time()


monitor = Monitor()
monitor.generar(30)


def _fig_serie_vivo() -> go.Figure:
    s = pd.DataFrame(list(monitor.serie))
    fig = go.Figure()
    if not s.empty:
        for k, color in [("accuracy", GREEN), ("f1", BRAND), ("recall", RED), ("precision", AMBER)]:
            fig.add_trace(go.Scatter(x=s["t"], y=s[k], mode="lines", name=k.capitalize(), line=dict(color=color, width=2)))
    return _fig(fig, height=320, title=f"Métricas en vivo · ventana móvil de {monitor.WINDOW} predicciones",
                yaxis_range=[0, 1.05], legend=dict(orientation="h", y=-0.25), xaxis=dict(nticks=8))


def _fig_deriva() -> go.Figure:
    ventana = list(monitor.eventos)[-monitor.WINDOW:]
    zs = []
    for f in FEATURES_NUM:
        media = float(np.mean([e[f] for e in ventana])) if ventana else MEDIAS[f]
        zs.append((media - MEDIAS[f]) / (DESV[f] or 1.0))
    colores = [RED if abs(z) > 2 else AMBER if abs(z) > 1 else GREEN for z in zs]
    fig = go.Figure(go.Bar(x=zs, y=[LABELS[f] for f in FEATURES_NUM], orientation="h", marker_color=colores,
                           text=[f"{z:+.2f}" for z in zs], textposition="outside"))
    for lim in (-2, -1, 1, 2):
        fig.add_vline(x=lim, line_dash="dot", line_color="#cbd5e1")
    return _fig(fig, height=300, title="Deriva de datos<br><sup>z-score de la media reciente vs. entrenamiento</sup>",
                xaxis_title="z", xaxis_range=[-3, 3], margin=dict(l=10, r=40, t=50, b=40))


def refrescar_monitor():
    if monitor.activo:
        monitor.generar(1)
    eventos = list(monitor.eventos)
    ventana = eventos[-monitor.WINDOW:]
    cm_v = monitor._cm(ventana)
    cm_a = monitor._cm(eventos)
    yt = np.array([e["real"] for e in ventana]); yp = np.array([e["pred"] for e in ventana]); p = np.array([e["p_si"] for e in ventana])
    m = _metricas_binarias(yt, yp, p) if len(ventana) else {k: float("nan") for k in ["Accuracy", "Precisión", "Recall", "F1-score", "ROC-AUC"]}
    lat = [e["latencia_ms"] for e in eventos]
    estado = "🟢 activo" if monitor.activo else "🔴 en pausa"
    kpis = _kpis_html(m, cm_v, len(ventana), f"Producción (simulada) · {estado} · total {len(eventos)} · "
                      f"latencia p50 {np.percentile(lat, 50):.2f} ms / p95 {np.percentile(lat, 95):.2f} ms")
    tabla = pd.DataFrame(eventos[::-1][:25])
    if not tabla.empty:
        tabla["pred"] = tabla["pred"].map({0: "NO", 1: "SI"}); tabla["real"] = tabla["real"].map({0: "NO", 1: "SI"})
        tabla["acierto"] = np.where(tabla["pred"] == tabla["real"], "✓", "✗")
        if "ciudad" not in tabla.columns:
            tabla.insert(tabla.columns.get_loc("cultivo") + 1, "ciudad", tabla["cultivo"].map(ciudad_de))
        tabla["ciudad"] = tabla["ciudad"].map(lambda c: str(c).capitalize())
        tabla = tabla.rename(columns={"hora": "Hora", "cultivo": "Cultivo", "ciudad": "Ciudad", "p_si": "P(SI)", "pred": "Pred.",
                                      "real": "Real", "latencia_ms": "ms", "acierto": "OK",
                                      **{f: LABELS[f].split(" (")[0] for f in FEATURES_NUM}})
    return (kpis, _fig_matriz(cm_v, f"Ventana móvil<br><sup>últimas {len(ventana)} predicciones</sup>", False),
            _fig_matriz(cm_a, f"Acumulada<br><sup>{len(eventos)} predicciones desde el inicio</sup>", False),
            _fig_serie_vivo(), _fig_deriva(), tabla)


def alternar_monitor():
    monitor.activo = not monitor.activo
    return "⏸ Pausar" if monitor.activo else "▶ Reanudar"


def rafaga_monitor():
    monitor.generar(25)
    return refrescar_monitor()


def reiniciar_monitor():
    monitor.reiniciar(); monitor.generar(10)
    return refrescar_monitor()


# --------------------------------------------------------------------------- #
# 6) DATOS
# --------------------------------------------------------------------------- #
def tabla_resumen() -> pd.DataFrame:
    if not resumen:
        return pd.DataFrame()
    filas = []
    for f, c in resumen["columnas_numericas"].items():
        fila = {"Variable": LABELS.get(f, f), "Válidos": c["validos"], "Inválidos": c["invalidos"],
                "Mín": c["min"], "Promedio": c["promedio"], "Máx": c["max"]}
        for cu, prom in resumen["promedio_por_cultivo"].items():
            fila[f"μ {cu}"] = prom[f]
        filas.append(fila)
    return pd.DataFrame(filas)


def filtrar_datos(cultivos: list[str], resultado: str) -> pd.DataFrame:
    d = df[df[FEATURE_CAT].isin(cultivos)] if cultivos else df
    if resultado != "Todos":
        d = d[d[TARGET] == resultado]
    d = con_ciudad(d.copy()); d["P(SI) modelo"] = np.round(modelo.predict_proba(d[COLUMNAS_MODELO])[:, 1], 3)
    return d


# --------------------------------------------------------------------------- #
# INTERFAZ
# --------------------------------------------------------------------------- #
CSS = """
.gradio-container { max-width: 1500px !important; margin: 0 auto; }
#titulo h1 { margin-bottom: 0; }
#titulo p { color: #64748b; margin-top: 4px; }
.kpi-html { margin: 4px 0 10px; }
footer { display: none !important; }
"""

hold = metricas.get("holdout", {}); cv = metricas.get("cv", {})
SUBTITULO = (f"Modelo **{metricas.get('modelo', 'LogisticRegression')} v{metricas.get('version', '1.0.0')}** · "
             f"entrenado {str(metricas.get('fecha_entrenamiento', '—'))[:10]} · {len(df)} filas ({int(y.sum())} SI / {int((1 - y).sum())} NO) · "
             f"hold-out: accuracy {hold.get('accuracy', 0):.2f} / F1 {hold.get('f1', 0):.2f} · "
             f"CV 5×: accuracy {cv.get('accuracy', 0):.2f} / F1 {cv.get('f1', 0):.2f}")


def _slider(nombre: str, valor: float, paso: float = 0.1) -> gr.Slider:
    lo, hi = RANGOS[nombre]
    return gr.Slider(minimum=round(lo * 0.9, 1), maximum=round(hi * 1.1, 1), value=valor, step=paso, label=LABELS[nombre])


with gr.Blocks(title="Práctica MLOps · Gradio") as demo:
    gr.Markdown("# 🌱 Práctica MLOps · Panel del modelo\n" + SUBTITULO, elem_id="titulo")

    with gr.Tabs():
        # ───────────────────────── 1. Predicción ─────────────────────────
        with gr.Tab("🔮 Predicción"):
            with gr.Row():
                with gr.Column(scale=2):
                    with gr.Row():
                        cultivo = gr.Dropdown(CULTIVOS, value=CULTIVOS[0], label="Cultivo", scale=1)
                        ciudad_box = gr.Textbox(value=ciudad_de(CULTIVOS[0]).capitalize(), label="Ciudad (según el cultivo)",
                                                interactive=False, scale=1)
                    cultivo.change(lambda c: ciudad_de(c).capitalize(), cultivo, ciudad_box)
                    temperatura = _slider("temperatura", 21.0)
                    humedad = _slider("humedad", 75.0)
                    radiacion = _slider("radiacion_solar", 17.0)
                    precipitacion = _slider("precipitacion", 8.0)
                    viento = _slider("viento", 6.0)
                    umbral_pred = gr.Slider(0.05, 0.95, value=0.5, step=0.05, label="Umbral de decisión")
                    with gr.Row():
                        boton = gr.Button("Predecir", variant="primary", scale=3)
                        btn_azar = gr.Button("🎲 Fila aleatoria", scale=1)
                    nota_azar = gr.Markdown()
                with gr.Column(scale=3):
                    with gr.Row():
                        with gr.Column():
                            salida_html = gr.HTML()
                            salida_label = gr.Label(num_top_classes=2, label="Probabilidades")
                        gauge = gr.Plot(label="Indicador")
                    contrib = gr.Plot(label="Contribución de variables")
            entradas = [cultivo, temperatura, humedad, radiacion, precipitacion, viento, umbral_pred]
            salidas = [salida_label, salida_html, gauge, contrib]
            boton.click(predecir, entradas, salidas)
            btn_azar.click(fila_aleatoria, None, [cultivo, temperatura, humedad, radiacion, precipitacion, viento, nota_azar]).then(predecir, entradas, salidas)
            gr.Examples(
                examples=[["cafe", 24.8, 83.1, 19.3, 13.9, 5.6, 0.5], ["uva", 27.7, 65.0, 21.0, 5.4, 6.2, 0.5], ["papa", 13.2, 86.2, 16.3, 4.8, 6.9, 0.5]],
                inputs=entradas, outputs=salidas, fn=predecir, cache_examples=False, label="Ejemplos",
            )

        # ───────────────────────── 2. Métricas ─────────────────────────
        with gr.Tab("📊 Métricas y matriz de confusión"):
            with gr.Row():
                _opciones_conjunto = [f"Hold-out ({len(Y_HOLDOUT)} filas)",
                                      f"Validación cruzada 5× ({len(Y_CV)} filas, out-of-fold)"]
                conjunto = gr.Radio(_opciones_conjunto, value=_opciones_conjunto[0],
                                    label="Conjunto de evaluación", scale=3)
                umbral_m = gr.Slider(0.05, 0.95, value=0.5, step=0.05, label="Umbral de decisión", scale=2)
                normalizar = gr.Checkbox(False, label="Colorear por proporción", scale=1)
            kpis_html = gr.HTML(elem_classes=["kpi-html"])
            with gr.Row():
                fig_cm = gr.Plot(label="Matriz de confusión")
                fig_roc = gr.Plot(label="Curva ROC")
                fig_pr = gr.Plot(label="Precision-Recall")
            with gr.Row():
                fig_umb = gr.Plot(label="Métricas vs umbral")
                fig_dist_p = gr.Plot(label="Distribución de probabilidades")
                tabla_m = gr.Dataframe(label="Tabla de métricas", interactive=False)
            for comp in (conjunto, umbral_m, normalizar):
                comp.change(actualizar_metricas, [conjunto, umbral_m, normalizar],
                            [kpis_html, fig_cm, fig_roc, fig_pr, fig_umb, fig_dist_p, tabla_m])
            demo.load(actualizar_metricas, [conjunto, umbral_m, normalizar],
                      [kpis_html, fig_cm, fig_roc, fig_pr, fig_umb, fig_dist_p, tabla_m])

        # ───────────────────────── 3. Mapas de calor ─────────────────────────
        with gr.Tab("🔥 Mapas de calor"):
            with gr.Row():
                with gr.Column():
                    metodo = gr.Radio(["Pearson", "Spearman"], value="Pearson", label="Método de correlación")
                    fig_corr = gr.Plot(label="Correlación")
                with gr.Column():
                    fig_cult = gr.Plot(label="Promedios por cultivo")
                    fig_radar = gr.Plot(label="Perfil por cultivo")
            gr.Markdown("### Superficie de decisión del modelo")
            with gr.Row():
                hm_cultivo = gr.Dropdown([(f"{c} · {ciudad_de(c).capitalize()}", c) for c in CULTIVOS], value=CULTIVOS[0], label="Cultivo · ciudad")
                hm_x = gr.Dropdown(FEATURES_NUM, value="temperatura", label="Eje X")
                hm_y = gr.Dropdown(FEATURES_NUM, value="humedad", label="Eje Y")
                hm_res = gr.Slider(10, 60, value=35, step=5, label="Resolución de la rejilla")
                hm_pts = gr.Checkbox(True, label="Mostrar datos reales")
            fig_dec = gr.Plot(label="Superficie de decisión")
            gr.Markdown("### Tasa observada de SI (frecuencia real en el dataset)")
            with gr.Row():
                ts_x = gr.Dropdown(FEATURES_NUM, value="temperatura", label="Eje X")
                ts_y = gr.Dropdown(FEATURES_NUM, value="humedad", label="Eje Y")
                ts_bins = gr.Slider(2, 6, value=4, step=1, label="Celdas por eje")
            fig_tasa = gr.Plot(label="Tasa de SI")

            metodo.change(heatmap_correlacion, metodo, fig_corr)
            for comp in (hm_cultivo, hm_x, hm_y, hm_res, hm_pts):
                comp.change(heatmap_decision, [hm_cultivo, hm_x, hm_y, hm_res, hm_pts], fig_dec)
            for comp in (ts_x, ts_y, ts_bins):
                comp.change(heatmap_tasa_si, [ts_x, ts_y, ts_bins], fig_tasa)
            demo.load(heatmap_correlacion, metodo, fig_corr)
            demo.load(heatmap_cultivos, None, fig_cult)
            demo.load(fig_radar_cultivos, None, fig_radar)
            demo.load(heatmap_decision, [hm_cultivo, hm_x, hm_y, hm_res, hm_pts], fig_dec)
            demo.load(heatmap_tasa_si, [ts_x, ts_y, ts_bins], fig_tasa)

        # ───────────────────────── 4. Exploración ─────────────────────────
        with gr.Tab("🔍 Exploración de datos"):
            fig_hist = gr.Plot(label="Distribuciones")
            with gr.Row():
                with gr.Column():
                    var_box = gr.Dropdown(FEATURES_NUM, value="humedad", label="Variable")
                    fig_box = gr.Plot(label="Box plot")
                with gr.Column():
                    with gr.Row():
                        sc_x = gr.Dropdown(FEATURES_NUM, value="temperatura", label="Eje X")
                        sc_y = gr.Dropdown(FEATURES_NUM, value="radiacion_solar", label="Eje Y")
                    fig_sc = gr.Plot(label="Dispersión")
            fig_coef = gr.Plot(label="Coeficientes")
            var_box.change(fig_boxplots, var_box, fig_box)
            sc_x.change(fig_scatter, [sc_x, sc_y], fig_sc); sc_y.change(fig_scatter, [sc_x, sc_y], fig_sc)
            demo.load(fig_distribuciones, None, fig_hist)
            demo.load(fig_boxplots, var_box, fig_box)
            demo.load(fig_scatter, [sc_x, sc_y], fig_sc)
            demo.load(fig_coeficientes, None, fig_coef)

        # ───────────────────────── 5. Monitoreo en vivo ─────────────────────────
        with gr.Tab("📡 Monitoreo en vivo"):
            gr.Markdown("Simulador de tráfico de producción: cada 2 s llega una observación sintética "
                        "(fila real + ruido gaussiano, ~5 % de ruido de etiqueta). Las métricas se calculan "
                        "sobre una ventana móvil de 50 predicciones.")
            with gr.Row():
                btn_pausa = gr.Button("⏸ Pausar", scale=1)
                btn_rafaga = gr.Button("⚡ Ráfaga +25", scale=1)
                btn_reset = gr.Button("↺ Reiniciar", scale=1)
            kpis_vivo = gr.HTML(elem_classes=["kpi-html"])
            with gr.Row():
                cm_vivo = gr.Plot(label="Ventana móvil")
                cm_acum = gr.Plot(label="Acumulada")
                fig_deriva = gr.Plot(label="Deriva")
            serie_vivo = gr.Plot(label="Serie temporal")
            tabla_vivo = gr.Dataframe(label="Últimas 25 predicciones", interactive=False)
            salidas_vivo = [kpis_vivo, cm_vivo, cm_acum, serie_vivo, fig_deriva, tabla_vivo]
            timer = gr.Timer(2.0)
            timer.tick(refrescar_monitor, None, salidas_vivo)
            btn_pausa.click(alternar_monitor, None, btn_pausa)
            btn_rafaga.click(rafaga_monitor, None, salidas_vivo)
            btn_reset.click(reiniciar_monitor, None, salidas_vivo)
            demo.load(refrescar_monitor, None, salidas_vivo)

        # ───────────────────────── 6. Datos ─────────────────────────
        with gr.Tab("🗂 Datos"):
            gr.Markdown(f"### Resumen de `procesar_datos.py` · ejecutado {resumen.get('fecha_ejecucion', '—')} · "
                        f"filas {resumen.get('filas_totales', len(df))} · válidas {resumen.get('filas_validas', '—')} · "
                        f"inválidas {resumen.get('filas_invalidas', '—')}")
            gr.Dataframe(value=tabla_resumen(), label="Estadísticas por variable", interactive=False)
            with gr.Row():
                filtro_cult = gr.CheckboxGroup(CULTIVOS, value=CULTIVOS, label="Cultivos")
                filtro_res = gr.Radio(["Todos", "SI", "NO"], value="Todos", label="Resultado")
            tabla_datos = gr.Dataframe(value=filtrar_datos(CULTIVOS, "Todos"), label="data/datos.csv (+ P(SI) del modelo)", interactive=False)
            filtro_cult.change(filtrar_datos, [filtro_cult, filtro_res], tabla_datos)
            filtro_res.change(filtrar_datos, [filtro_cult, filtro_res], tabla_datos)


# --------------------------------------------------------------------------- #
# PÁGINA 2: /resultados  → ver y descargar output/resultado.json
# --------------------------------------------------------------------------- #
LOG_EJECUCION = BASE_DIR / "logs" / "ejecucion.log"


def _cargar_resultado() -> dict | None:
    if not RESULT_PATH.exists():
        return None
    return json.loads(RESULT_PATH.read_text(encoding="utf-8"))


def _kpis_resultado_html(r: dict) -> str:
    fecha = str(r.get("fecha_ejecucion", "—")).replace("T", " ")[:19]
    dist = r.get("distribucion_resultado", {})
    tarjetas = [
        ("Filas totales", r.get("filas_totales", "—"), BRAND),
        ("Filas válidas", r.get("filas_validas", "—"), GREEN),
        ("Filas inválidas", r.get("filas_invalidas", "—"), RED),
        ("Resultado SI", dist.get("SI", "—"), VIOLET),
        ("Resultado NO", dist.get("NO", "—"), SLATE),
        ("Cultivos", len(r.get("distribucion_cultivo", {})), AMBER),
    ]
    cards = "".join(
        f'<div style="flex:1;min-width:130px;border:1px solid #e6eaf0;border-top:3px solid {c};border-radius:10px;'
        f'padding:10px 14px;background:#fff"><div style="font-size:11px;color:#64748b;text-transform:uppercase;'
        f'letter-spacing:.05em">{k}</div><div style="font-size:26px;font-weight:600;color:#0f172a">{v}</div></div>'
        for k, v, c in tarjetas
    )
    tam = RESULT_PATH.stat().st_size if RESULT_PATH.exists() else 0
    return (f'<div style="display:flex;gap:10px;flex-wrap:wrap">{cards}</div>'
            f'<p style="font-size:12px;color:#64748b;margin:8px 2px 0">Archivo <code>output/resultado.json</code> · '
            f'{tam:,} bytes · generado por <code>procesar_datos.py</code> el {fecha} · origen: '
            f'<code>{r.get("archivo_origen", "datos.csv")}</code></p>')


def _tabla_columnas(r: dict) -> pd.DataFrame:
    filas = []
    for f, c in r.get("columnas_numericas", {}).items():
        fila = {"Variable": LABELS.get(f, f), "Válidos": c["validos"], "Inválidos": c["invalidos"],
                "Nulos originales": c.get("nulos_originales", 0), "Mín": c["min"], "Promedio": c["promedio"], "Máx": c["max"]}
        for cu, prom in r.get("promedio_por_cultivo", {}).items():
            fila[f"Promedio {cu}"] = prom.get(f)
        filas.append(fila)
    return pd.DataFrame(filas).round(2)


def _tabla_cultivos(r: dict) -> pd.DataFrame:
    dist = r.get("distribucion_cultivo", {})
    tasa = r.get("tasa_si_por_cultivo", {})
    return pd.DataFrame([{"Cultivo": c, "Filas": n, "Tasa de SI": f"{tasa.get(c, 0):.1%}",
                          "SI": round(n * tasa.get(c, 0))} for c, n in sorted(dist.items())])


def _fig_resultado(r: dict) -> go.Figure:
    dist_c = r.get("distribucion_cultivo", {})
    tasa = r.get("tasa_si_por_cultivo", {})
    cultivos = sorted(dist_c)
    fig = make_subplots(rows=1, cols=3, specs=[[{"type": "domain"}, {"type": "xy"}, {"type": "xy"}]],
                        subplot_titles=["Distribución de resultado", "Filas por cultivo", "Tasa de SI por cultivo"])
    dist_r = r.get("distribucion_resultado", {})
    fig.add_trace(go.Pie(labels=list(dist_r.keys()), values=list(dist_r.values()), hole=0.55,
                         marker_colors=[VIOLET if k == "SI" else SLATE for k in dist_r], textinfo="label+percent"), 1, 1)
    fig.add_trace(go.Bar(x=cultivos, y=[dist_c[c] for c in cultivos], marker_color=[CULTIVO_COLORS.get(c, BRAND) for c in cultivos],
                         text=[dist_c[c] for c in cultivos], textposition="outside", showlegend=False), 1, 2)
    fig.add_trace(go.Bar(x=cultivos, y=[tasa.get(c, 0) for c in cultivos], marker_color=[CULTIVO_COLORS.get(c, BRAND) for c in cultivos],
                         text=[f"{tasa.get(c, 0):.0%}" for c in cultivos], textposition="outside", showlegend=False), 1, 3)
    fig.update_yaxes(range=[0, 1], tickformat=".0%", row=1, col=3)
    return _fig(fig, height=340, showlegend=False, title="Resumen visual de resultado.json")


def _fig_promedios(r: dict) -> go.Figure:
    prom = r.get("promedio_por_cultivo", {})
    if not prom:
        return go.Figure()
    d = pd.DataFrame(prom).T[FEATURES_NUM]
    fig = go.Figure()
    for cultivo, fila in d.iterrows():
        fig.add_trace(go.Bar(name=cultivo, x=[LABELS[f] for f in FEATURES_NUM], y=fila.values,
                             marker_color=CULTIVO_COLORS.get(cultivo), text=[f"{v:.1f}" for v in fila.values], textposition="outside"))
    general = r.get("promedio_general", {})
    fig.add_trace(go.Scatter(name="promedio general", x=[LABELS[f] for f in FEATURES_NUM], y=[general.get(f) for f in FEATURES_NUM],
                             mode="markers", marker=dict(symbol="diamond", size=12, color="#0f172a")))
    return _fig(fig, height=360, barmode="group", title="Promedio por cultivo vs. promedio general",
                legend=dict(orientation="h", y=-0.2))


def _tail_log(n: int = 30) -> str:
    if not LOG_EJECUCION.exists():
        return "— logs/ejecucion.log no existe todavía —"
    lineas = LOG_EJECUCION.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lineas[-n:])


def cargar_pagina_resultados():
    """Devuelve todos los componentes de la página /resultados (se ejecuta al cargar y al pulsar Recargar)."""
    r = _cargar_resultado()
    if r is None:
        vacio = pd.DataFrame()
        aviso = ('<div style="border:1px solid #fecdd3;background:#fff1f2;color:#9f1239;border-radius:10px;padding:14px">'
                 '<b>No existe <code>output/resultado.json</code>.</b> Ejecuta <code>python procesar_datos.py</code> '
                 'desde la raíz del proyecto y pulsa <b>Recargar</b>.</div>')
        return (aviso, gr.update(value=None, visible=False), "{}", vacio, vacio, go.Figure(), go.Figure(), _tail_log())
    return (
        _kpis_resultado_html(r),
        gr.update(value=str(RESULT_PATH), visible=True),
        json.dumps(r, ensure_ascii=False, indent=2),
        _tabla_columnas(r),
        _tabla_cultivos(r),
        _fig_resultado(r),
        _fig_promedios(r),
        _tail_log(),
    )


def regenerar_resultado():
    """Vuelve a ejecutar procesar_datos.py (misma lógica que el paso 1 del pipeline) y recarga la página."""
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, str(BASE_DIR / "procesar_datos.py")], capture_output=True, text=True,
                          cwd=str(BASE_DIR), timeout=120)
    global resumen
    resumen = _cargar_resultado() or {}
    salida = cargar_pagina_resultados()
    estado = ("✅ `procesar_datos.py` ejecutado correctamente." if proc.returncode == 0
              else f"❌ `procesar_datos.py` terminó con código {proc.returncode}:\n```\n{proc.stderr[-800:]}\n```")
    return (*salida, estado)


with demo.route("📄 Resultados", "/resultados"):
    gr.Markdown(
        "# 📄 Resultados del procesamiento\n"
        "Contenido de **`output/resultado.json`**, el archivo que genera `procesar_datos.py` tras leer y validar "
        "`data/datos.csv` (filas, valores válidos e inválidos, promedios y fecha de ejecución).",
        elem_id="titulo",
    )
    with gr.Row():
        btn_recargar = gr.Button("🔄 Recargar", scale=1)
        btn_regenerar = gr.Button("⚙️ Volver a ejecutar procesar_datos.py", scale=2)
        descarga = gr.DownloadButton("⬇️ Descargar resultado.json", value=str(RESULT_PATH) if RESULT_PATH.exists() else None,
                                     variant="primary", scale=2)
    estado_md = gr.Markdown()
    kpis_res = gr.HTML(elem_classes=["kpi-html"])
    with gr.Tabs():
        with gr.Tab("📊 Resumen"):
            fig_res = gr.Plot(label="Distribuciones")
            fig_prom = gr.Plot(label="Promedios")
            with gr.Row():
                tabla_cols = gr.Dataframe(label="Estadísticas por variable", interactive=False, scale=3)
                tabla_cult = gr.Dataframe(label="Por cultivo", interactive=False, scale=1)
        with gr.Tab("{ } JSON completo"):
            gr.Markdown("Contenido íntegro del archivo (puedes copiarlo con el botón del visor).")
            json_code = gr.Code(language="json", label="output/resultado.json", lines=30, interactive=False)
        with gr.Tab("🧾 Log de ejecución"):
            gr.Markdown("Últimas líneas de `logs/ejecucion.log` (registro de `procesar_datos.py`).")
            log_code = gr.Code(language=None, label="logs/ejecucion.log", lines=18, interactive=False)

    salidas_res = [kpis_res, descarga, json_code, tabla_cols, tabla_cult, fig_res, fig_prom, log_code]
    demo.load(cargar_pagina_resultados, None, salidas_res)
    btn_recargar.click(cargar_pagina_resultados, None, salidas_res).then(lambda: "🔄 Recargado.", None, estado_md)
    btn_regenerar.click(regenerar_resultado, None, [*salidas_res, estado_md])


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, theme=gr.themes.Soft(primary_hue="indigo", neutral_hue="slate"),
                css=CSS, allowed_paths=[str(BASE_DIR / "output")])
