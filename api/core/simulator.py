"""
api/core/simulator.py
---------------------
Simulador de tráfico de producción: toma filas reales del dataset, les añade
ruido gaussiano (y ~5 % de ruido de etiqueta) y las envía por el mismo
PredictionService que usa la API, de modo que llegan ya etiquetadas y las
métricas en vivo se mueven.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

from ..config import Settings
from .model import Predictor
from .service import PredictionService

log = logging.getLogger("api.simulator")


class Simulator:
    def __init__(self, settings: Settings, predictor: Predictor, service: PredictionService):
        self.s = settings
        self.predictor = predictor
        self.service = service
        self.activo = False
        self.intervalo = settings.simulator_interval_s
        self.generados = 0
        self.rafagas = 0
        self.iniciado_en: float | None = None
        self.ultimo_evento: str | None = None
        self._tarea: asyncio.Task | None = None
        self._rng = random.Random()
        self._sync()

    # ------------------------------------------------------------------ generación
    def observacion_sintetica(self, rng: random.Random | None = None) -> tuple[dict, int]:
        rng = rng or self._rng
        df = self.predictor.dataset
        fila = df.iloc[rng.randrange(len(df))]
        desv = self.predictor.desviaciones()
        obs = {self.s.feature_cat: str(fila[self.s.feature_cat])}
        ciudad = fila.get(self.s.feature_ciudad) if hasattr(fila, "get") else None
        obs[self.s.feature_ciudad] = str(ciudad) if isinstance(ciudad, str) and ciudad else self.predictor.ciudad_de(obs[self.s.feature_cat])
        for f in self.s.features_num:
            sd = float(desv.get(f) or df[f].std() or 1.0)
            v = float(fila[f]) + rng.gauss(0, 0.15 * sd)
            lo, hi = float(df[f].min()), float(df[f].max())
            obs[f] = round(min(max(v, max(0.0, lo * 0.9) if lo >= 0 else lo * 1.1), hi * 1.1), 2)
        real = 1 if str(fila["resultado"]).upper() == "SI" else 0
        if rng.random() < 0.05:
            real = 1 - real
        return obs, real

    async def generar(self, rng: random.Random | None = None, difundir: bool = True) -> dict:
        obs, real = self.observacion_sintetica(rng)
        evento = await self.service.predecir(obs, umbral=0.5, origen="simulador", real=real, difundir=difundir)
        self.generados += 1
        self.ultimo_evento = evento["timestamp"]
        return evento

    async def calentar(self, n: int, semilla: int = 7) -> int:
        """Genera n eventos iniciales (sin SSE) para que el dashboard no arranque vacío."""
        rng = random.Random(semilla)
        for _ in range(n):
            await self.generar(rng, difundir=False)
        self.service.monitor.serie.append(self.service.monitor.punto_serie())
        return n

    async def rafaga(self, cantidad: int) -> dict:
        for _ in range(cantidad):
            await self.generar(difundir=False)
        self.rafagas += 1
        self.service.monitor.serie.append(self.service.monitor.punto_serie())
        await self.service.difundir_metricas()
        return self.status()

    # ------------------------------------------------------------------ bucle
    async def _bucle(self) -> None:
        log.info("Simulador de tráfico iniciado (intervalo=%.1fs)", self.intervalo)
        contador = 0
        try:
            while self.activo:
                try:
                    if self.predictor.modelo is not None and self.predictor.dataset is not None:
                        await self.generar()
                        contador += 1
                        if contador % 3 == 0:
                            self.service.monitor.serie.append(self.service.monitor.punto_serie())
                        await self.service.difundir_metricas()
                except Exception as exc:  # noqa: BLE001
                    log.exception("Error en el simulador: %s", exc)
                    await asyncio.sleep(2)
                await asyncio.sleep(self.intervalo)
        except asyncio.CancelledError:
            pass
        finally:
            log.info("Simulador detenido (%d eventos)", self.generados)

    def _sync(self) -> None:
        self.service.monitor.simulador_estado = {"activo": self.activo, "intervalo_s": self.intervalo}

    async def start(self, intervalo: float | None = None) -> dict:
        if intervalo is not None:
            self.intervalo = intervalo
        if not self.activo:
            self.activo = True
            self.iniciado_en = time.time()
            self._tarea = asyncio.create_task(self._bucle())
        self._sync()
        await self.service.difundir_metricas()
        return self.status()

    async def stop(self) -> dict:
        self.activo = False
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._tarea = None
        self._sync()
        await self.service.difundir_metricas()
        return self.status()

    def status(self) -> dict:
        return {"activo": self.activo, "intervalo_s": self.intervalo, "eventos_generados": self.generados,
                "rafagas": self.rafagas, "ultimo_evento": self.ultimo_evento,
                "activo_desde_s": round(time.time() - self.iniciado_en, 1) if (self.activo and self.iniciado_en) else None,
                "ruido_features": "gauss(0, 0.15·σ_entrenamiento)", "ruido_etiqueta": 0.05}
