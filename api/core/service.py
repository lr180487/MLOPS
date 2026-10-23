"""
api/core/service.py
-------------------
Servicio de predicción y feedback: orquesta Predictor → Cache Manager →
Monitor → Persistencia → SSE. Es el único punto por el que pasan las
predicciones (API, lotes y simulador), de modo que todas quedan cacheadas,
registradas, persistidas y difundidas de la misma forma.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid

import pandas as pd

from ..config import Settings
from .cache import CacheManager
from .database import Database
from .events import EventBus
from .model import Predictor
from .monitor import Monitor, ahora_iso

log = logging.getLogger("api.service")


class PredictionService:
    def __init__(self, settings: Settings, predictor: Predictor, monitor: Monitor, db: Database,
                 cache: CacheManager, bus: EventBus):
        self.s = settings
        self.predictor = predictor
        self.monitor = monitor
        self.db = db
        self.cache = cache
        self.bus = bus

    # ------------------------------------------------------------------ helpers
    def _clave_features(self, features: dict, umbral: float) -> str:
        base = json.dumps({**features, "umbral": umbral, "modelo": self.predictor.hash}, sort_keys=True)
        return f"pred:feat:{hashlib.sha1(base.encode()).hexdigest()[:20]}"

    def _fila_a_dict(self, f: dict) -> dict:
        s = self.s
        return {
            "id": f["id"], "timestamp": f["ts"], "origen": f["origen"],
            "features": {**{k: f.get(k) for k in s.features_num}, s.feature_cat: f.get("cultivo"),
                         s.feature_ciudad: f.get("ciudad") or self.predictor.ciudad_de(f.get("cultivo") or "")},
            "probabilidad_si": f.get("probabilidad_si"),
            "probabilidad_no": None if f.get("probabilidad_si") is None else round(1 - float(f["probabilidad_si"]), 4),
            "prediccion": s.clases[int(f["prediccion"])], "prediccion_idx": int(f["prediccion"]),
            "umbral": f.get("umbral"),
            "real": None if f.get("etiqueta_real") is None else s.clases[int(f["etiqueta_real"])],
            "latencia_ms": f.get("latencia_ms"), "modelo_version": f.get("modelo_version"), "cache_hit": bool(f.get("cache_hit")),
        }

    # ------------------------------------------------------------------ predicción
    async def predecir(self, features: dict, umbral: float = 0.5, origen: str = "api", real: int | None = None,
                       difundir: bool = True) -> dict:
        """Predice una observación y devuelve el evento registrado (formato del monitor)."""
        s = self.s
        features = self.predictor.completar_ciudad(features)       # normaliza cultivo y deduce/valida ciudad
        features = {k: features.get(k) for k in s.columnas_modelo}

        # 1) caché de inferencia (misma entrada + mismo umbral + mismo modelo → mismo resultado)
        clave = self._clave_features(features, umbral)
        t0 = time.perf_counter()
        ok, cacheado, nivel = await self.cache.get(clave)
        if ok:
            proba, pred = float(cacheado["probabilidad_si"]), int(cacheado["prediccion"])
            latencia = (time.perf_counter() - t0) * 1000
            cache_hit = True
        else:
            proba, pred, latencia = await asyncio.to_thread(self.predictor.predict_one, features, umbral)
            await self.cache.set(clave, {"probabilidad_si": round(proba, 6), "prediccion": pred})
            cache_hit, nivel = False, None

        # 2) evento para el monitor / SSE
        evento = {
            "id": uuid.uuid4().hex[:12], "timestamp": ahora_iso(), "t": time.time(), "origen": origen,
            "features": features, "probabilidad_si": round(proba, 4), "prediccion": pred, "real": real,
            "umbral": umbral, "latencia_ms": round(latencia, 3), "cache_hit": cache_hit, "cache_nivel": nivel,
            "modelo_version": self.predictor.version,
        }
        self.monitor.registrar(evento)

        # 3) persistencia
        await asyncio.to_thread(self._guardar_prediccion, evento)
        await self.cache.set(f"pred:id:{evento['id']}", self._evento_publico(evento), ttl=3600)

        # 4) difusión en tiempo real
        if difundir:
            await self.bus.publish("prediccion", {"evento": evento})
        return evento

    def _guardar_prediccion(self, e: dict) -> None:
        s, f = self.s, e["features"]
        self.db.execute(
            """INSERT INTO predictions (id, ts, origen, cultivo, ciudad, temperatura, humedad, radiacion_solar, precipitacion, viento,
                                        probabilidad_si, prediccion, umbral, etiqueta_real, latencia_ms, modelo_version, cache_hit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (e["id"], e["timestamp"], e["origen"], f[s.feature_cat], f.get(s.feature_ciudad), f["temperatura"], f["humedad"], f["radiacion_solar"],
             f["precipitacion"], f["viento"], e["probabilidad_si"], e["prediccion"], e["umbral"], e["real"],
             e["latencia_ms"], e["modelo_version"], 1 if e["cache_hit"] else 0),
        )

    def _evento_publico(self, e: dict) -> dict:
        s = self.s
        return {
            "id": e["id"], "timestamp": e["timestamp"], "origen": e["origen"], "features": e["features"],
            "prediccion": s.clases[e["prediccion"]], "prediccion_idx": e["prediccion"],
            "probabilidad_si": e["probabilidad_si"], "probabilidad_no": round(1 - e["probabilidad_si"], 4),
            "umbral": e["umbral"], "real": None if e["real"] is None else s.clases[e["real"]],
            "latencia_ms": e["latencia_ms"], "cache_hit": e["cache_hit"], "cache_nivel": e.get("cache_nivel"),
            "modelo_version": e["modelo_version"],
        }

    async def predecir_lote(self, filas: list[dict], umbral: float, origen: str = "api-batch") -> list[dict]:
        salida = []
        for fila in filas:
            salida.append(self._evento_publico(await self.predecir(fila, umbral, origen=origen, difundir=False)))
        await self.difundir_metricas()
        return salida

    async def obtener(self, prediction_id: str) -> dict | None:
        ok, valor, nivel = await self.cache.get(f"pred:id:{prediction_id}")
        if ok:
            return {**valor, "cache_nivel": nivel, "desde_cache": True}
        fila = await asyncio.to_thread(self.db.execute, "SELECT * FROM predictions WHERE id = ?", (prediction_id,), "one")
        if fila is None:
            return None
        d = self._fila_a_dict(fila)
        await self.cache.set(f"pred:id:{prediction_id}", d, ttl=3600)
        return {**d, "desde_cache": False}

    async def listar(self, limit: int = 50, offset: int = 0, cultivo: str | None = None, con_feedback: bool | None = None,
                     origen: str | None = None, ciudad: str | None = None) -> dict:
        cond, params = [], []
        if cultivo:
            cond.append("cultivo = ?"); params.append(cultivo.strip().lower())
        if ciudad:
            cond.append("ciudad = ?"); params.append(ciudad.strip().lower())
        if origen:
            cond.append("origen = ?"); params.append(origen)
        if con_feedback is True:
            cond.append("etiqueta_real IS NOT NULL")
        elif con_feedback is False:
            cond.append("etiqueta_real IS NULL")
        where = f"WHERE {' AND '.join(cond)}" if cond else ""
        total = (await asyncio.to_thread(self.db.execute, f"SELECT COUNT(*) AS n FROM predictions {where}", params, "one"))["n"]
        filas = await asyncio.to_thread(self.db.execute, f"SELECT * FROM predictions {where} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
                                        [*params, limit, offset], "all")
        return {"total": int(total), "limit": limit, "offset": offset, "items": [self._fila_a_dict(f) for f in filas]}

    # ------------------------------------------------------------------ feedback
    async def feedback(self, prediction_id: str, real_label: str, comentario: str | None = None, origen: str = "api") -> dict:
        s = self.s
        real = s.clases.index(real_label)
        evento = self.monitor.etiquetar(prediction_id, real)
        if evento is None:
            fila = await asyncio.to_thread(self.db.execute, "SELECT * FROM predictions WHERE id = ?", (prediction_id,), "one")
            if fila is None:
                raise LookupError("prediction_id no encontrado")
            if fila.get("etiqueta_real") is not None:
                raise ValueError("la predicción ya tiene feedback")
            evento = {"id": fila["id"], "prediccion": int(fila["prediccion"]), "real": real, "features": None,
                      "probabilidad_si": fila.get("probabilidad_si"), "timestamp": fila["ts"]}
            self.monitor._actualizar_matriz(evento["prediccion"], real)  # cuenta aunque no esté en memoria

        fb = {"id": uuid.uuid4().hex[:12], "prediction_id": prediction_id, "timestamp": ahora_iso(),
              "real": real_label, "prediccion": s.clases[int(evento["prediccion"])],
              "acierto": int(evento["prediccion"]) == real, "comentario": comentario, "origen": origen}
        await asyncio.to_thread(self._guardar_feedback, fb, real)
        await self.cache.delete(f"pred:id:{prediction_id}")
        await self.cache.delete("metrics:summary")
        log.info("feedback prediction_id=%s real=%s pred=%s", prediction_id, real_label, fb["prediccion"])
        await self.bus.publish("feedback", {"evento": evento, "feedback": fb})
        await self.difundir_metricas()
        return fb

    def _guardar_feedback(self, fb: dict, real: int) -> None:
        self.db.execute(
            "INSERT INTO feedback (id, prediction_id, ts, etiqueta_real, prediccion, acierto, comentario, origen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (fb["id"], fb["prediction_id"], fb["timestamp"], real, self.s.clases.index(fb["prediccion"]), 1 if fb["acierto"] else 0,
             fb["comentario"], fb["origen"]),
        )
        self.db.execute("UPDATE predictions SET etiqueta_real = ? WHERE id = ?", (real, fb["prediction_id"]))

    async def listar_feedback(self, limit: int = 50, offset: int = 0) -> dict:
        total = (await asyncio.to_thread(self.db.execute, "SELECT COUNT(*) AS n FROM feedback", (), "one"))["n"]
        filas = await asyncio.to_thread(self.db.execute, "SELECT * FROM feedback ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?", (limit, offset), "all")
        return {"total": int(total), "limit": limit, "offset": offset, "items": [self._fb_a_dict(f) for f in filas]}

    async def obtener_feedback(self, feedback_id: str) -> dict | None:
        fila = await asyncio.to_thread(self.db.execute, "SELECT * FROM feedback WHERE id = ?", (feedback_id,), "one")
        return self._fb_a_dict(fila) if fila else None

    def _fb_a_dict(self, f: dict) -> dict:
        return {"id": f["id"], "prediction_id": f["prediction_id"], "timestamp": f["ts"], "real": self.s.clases[int(f["etiqueta_real"])],
                "prediccion": self.s.clases[int(f["prediccion"])], "acierto": bool(f["acierto"]), "comentario": f.get("comentario"),
                "origen": f.get("origen")}

    # ------------------------------------------------------------------ métricas
    async def difundir_metricas(self) -> dict:
        m = self.monitor.metricas()
        await self.bus.publish("metricas", {"metricas": m})
        return m

    async def resumen(self) -> dict:
        """Resumen combinado (entrenamiento + producción + persistencia + caché), cacheado 5 s."""
        async def calcular() -> dict:
            live = self.monitor.metricas()
            train = self.predictor.metricas
            filas = await asyncio.to_thread(self.db.execute,
                """SELECT COUNT(*) AS total, SUM(CASE WHEN etiqueta_real IS NOT NULL THEN 1 ELSE 0 END) AS etiquetadas,
                          SUM(CASE WHEN etiqueta_real IS NOT NULL AND etiqueta_real = prediccion THEN 1 ELSE 0 END) AS aciertos,
                          AVG(latencia_ms) AS latencia_media, SUM(cache_hit) AS cache_hits
                   FROM predictions""", (), "one")
            por_cultivo = await asyncio.to_thread(self.db.execute,
                "SELECT cultivo, COUNT(*) AS n, AVG(probabilidad_si) AS p_si_media, SUM(prediccion) AS pred_si FROM predictions GROUP BY cultivo ORDER BY cultivo", (), "all")
            etiquetadas = int(filas["etiquetadas"] or 0)
            return {
                "timestamp": ahora_iso(),
                "modelo": {"nombre": train.get("modelo"), "version": self.predictor.version, "hash": self.predictor.hash},
                "entrenamiento": {"holdout": train.get("holdout"), "cv": train.get("cv"), "fecha": train.get("fecha_entrenamiento")},
                "produccion": {"ventana": live["ventana"], "acumulado": live["acumulado"], "latencia_ms": live["latencia_ms"],
                                "throughput_por_min": live["throughput_por_min"], "tasa_prediccion_si": live["tasa_prediccion_si"],
                                "deriva": live["deriva"]},
                "persistencia": {"backend": self.db.backend, "total_predicciones": int(filas["total"] or 0), "etiquetadas": etiquetadas,
                                  "accuracy_historica": round(int(filas["aciertos"] or 0) / etiquetadas, 4) if etiquetadas else None,
                                  "latencia_media_ms": round(float(filas["latencia_media"] or 0), 3), "cache_hits": int(filas["cache_hits"] or 0),
                                  "por_cultivo": [{"cultivo": r["cultivo"], "n": int(r["n"]), "p_si_media": round(float(r["p_si_media"] or 0), 4),
                                                   "pred_si": int(r["pred_si"] or 0)} for r in por_cultivo]},
                "cache": self.cache.stats(),
                "sse": self.bus.stats(),
            }
        valor, hit, nivel = await self.cache.get_or_compute("metrics:summary", calcular, ttl=5)
        return {**valor, "cache_hit": hit, "cache_nivel": nivel}

    # ------------------------------------------------------------------ rehidratación
    async def rehidratar_monitor(self, n: int = 200) -> int:
        filas = await asyncio.to_thread(self.db.execute,
            "SELECT * FROM (SELECT * FROM predictions ORDER BY ts DESC, id DESC LIMIT ?) sub ORDER BY ts ASC, id ASC", (n,), "all")
        return self.monitor.rehidratar(filas)
