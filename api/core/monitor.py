"""
api/core/monitor.py
-------------------
Métricas de producción en memoria: historial de predicciones, matriz de
confusión (ventana móvil y acumulada), latencias, deriva de datos y serie
temporal. Se rehidrata desde la base de datos al arrancar.
"""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone

import numpy as np

from ..config import Settings


def ahora_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def metricas_desde_cm(cm: list[list[int]]) -> dict:
    (tn, fp), (fn, tp) = cm
    total = tn + fp + fn + tp
    acc = (tp + tn) / total if total else None
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    esp = tn / (tn + fp) if (tn + fp) else None
    f1 = (2 * prec * rec / (prec + rec)) if (prec and rec) else (0.0 if total else None)
    r = lambda v: None if v is None else round(v, 4)  # noqa: E731
    return {"accuracy": r(acc), "precision": r(prec), "recall": r(rec), "especificidad": r(esp),
            "f1": r(f1), "n": total, "matriz_confusion": cm}


class Monitor:
    def __init__(self, settings: Settings, medias_train: dict | None = None, desv_train: dict | None = None):
        self.s = settings
        self.inicio = time.time()
        self.eventos: deque[dict] = deque(maxlen=settings.history_max)
        self.pendientes: dict[str, dict] = {}
        self.total_predicciones = 0
        self.total_etiquetadas = 0
        self.cm_acumulada = [[0, 0], [0, 0]]  # [[TN, FP], [FN, TP]]
        self.latencias: deque[float] = deque(maxlen=settings.history_max)
        self.serie: deque[dict] = deque(maxlen=120)
        self.medias_train = medias_train or {}
        self.desv_train = desv_train or {}
        self.cache_hits = 0
        self.simulador_estado: dict = {"activo": False, "intervalo_s": settings.simulator_interval_s}

    # ------------------------------------------------------------------ registro
    def registrar(self, evento: dict) -> None:
        """Añade una predicción (con o sin etiqueta real) al historial."""
        evento.setdefault("t", time.time())
        self.eventos.append(evento)
        if evento.get("latencia_ms") is not None:
            self.latencias.append(float(evento["latencia_ms"]))
        self.total_predicciones += 1
        if evento.get("cache_hit"):
            self.cache_hits += 1
        if evento.get("real") is None:
            self.pendientes[evento["id"]] = evento
        else:
            self._actualizar_matriz(int(evento["prediccion"]), int(evento["real"]))

    def etiquetar(self, prediction_id: str, real: int) -> dict | None:
        evento = self.pendientes.pop(prediction_id, None)
        if evento is None:
            return None
        evento["real"] = real
        self._actualizar_matriz(int(evento["prediccion"]), real)
        self.serie.append(self.punto_serie())
        return evento

    def _actualizar_matriz(self, pred: int, real: int) -> None:
        self.cm_acumulada[real][pred] += 1
        self.total_etiquetadas += 1

    def rehidratar(self, filas: list[dict]) -> int:
        """Reconstruye el historial a partir de filas de la tabla `predictions` (más antiguas primero)."""
        n = 0
        for f in filas:
            evento = {
                "id": f["id"], "timestamp": f["ts"], "origen": f.get("origen", "bd"),
                "features": {**{k: f.get(k) for k in self.s.features_num}, self.s.feature_cat: f.get("cultivo"),
                             self.s.feature_ciudad: f.get("ciudad") or self.s.ciudad_por_cultivo.get(str(f.get("cultivo") or "").lower())},
                "probabilidad_si": f.get("probabilidad_si"), "prediccion": int(f["prediccion"]),
                "real": None if f.get("etiqueta_real") is None else int(f["etiqueta_real"]),
                "latencia_ms": f.get("latencia_ms"), "cache_hit": bool(f.get("cache_hit")), "t": time.time() - 3600,
            }
            self.registrar(evento)
            n += 1
        if n:
            self.serie.append(self.punto_serie())
        return n

    # ------------------------------------------------------------------ métricas
    def metricas(self) -> dict:
        W = self.s.window
        etiquetados = [e for e in self.eventos if e.get("real") is not None]
        ventana = etiquetados[-W:]
        cm_ventana = [[0, 0], [0, 0]]
        for e in ventana:
            cm_ventana[int(e["real"])][int(e["prediccion"])] += 1

        ultimos = list(self.eventos)[-W:]
        lat = list(self.latencias)
        tasa_si = float(np.mean([e["prediccion"] for e in ultimos])) if ultimos else None

        deriva = {}
        if ultimos:
            for f in self.s.features_num:
                vals = [e["features"].get(f) for e in ultimos if e["features"].get(f) is not None]
                if not vals:
                    continue
                media = float(np.mean(vals))
                sd = self.desv_train.get(f) or 1.0
                deriva[f] = {"media_actual": round(media, 3), "media_entrenamiento": self.medias_train.get(f),
                             "z": round((media - self.medias_train.get(f, media)) / sd, 3) if self.medias_train else None}

        por_cultivo: dict[str, dict] = {}
        for e in ultimos:
            c = e["features"].get(self.s.feature_cat)
            d = por_cultivo.setdefault(c, {"total": 0, "si": 0})
            d["total"] += 1
            d["si"] += int(e["prediccion"])

        hace_1min = time.time() - 60
        throughput = sum(1 for e in self.eventos if e.get("t", 0) >= hace_1min)

        return {
            "timestamp": ahora_iso(),
            "uptime_s": round(time.time() - self.inicio, 1),
            "total_predicciones": self.total_predicciones,
            "total_etiquetadas": self.total_etiquetadas,
            "pendientes_feedback": len(self.pendientes),
            "throughput_por_min": throughput,
            "cache_hits": self.cache_hits,
            "latencia_ms": {
                "p50": round(float(np.percentile(lat, 50)), 3) if lat else None,
                "p95": round(float(np.percentile(lat, 95)), 3) if lat else None,
                "max": round(float(np.max(lat)), 3) if lat else None,
            },
            "tasa_prediccion_si": round(tasa_si, 4) if tasa_si is not None else None,
            "ventana": {"tamano": W, **metricas_desde_cm(cm_ventana)},
            "acumulado": metricas_desde_cm([row[:] for row in self.cm_acumulada]),
            "deriva": deriva,
            "por_cultivo": por_cultivo,
            "serie": list(self.serie),
            "simulador": dict(self.simulador_estado),
        }

    def punto_serie(self) -> dict:
        m = self.metricas()
        return {"t": m["timestamp"], "accuracy": m["ventana"]["accuracy"], "f1": m["ventana"]["f1"],
                "recall": m["ventana"]["recall"], "precision": m["ventana"]["precision"],
                "tasa_si": m["tasa_prediccion_si"], "p95": m["latencia_ms"]["p95"]}

    def ultimos(self, n: int) -> list[dict]:
        return list(self.eventos)[-n:][::-1]
