"""
api/core/model.py
-----------------
Predictor: carga `models/modelo.joblib`, `models/metricas.json` y el dataset de
referencia, y expone predicción, información del modelo, recarga en caliente y
la superficie de probabilidad (heatmap).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import joblib
import numpy as np
import pandas as pd

from ..config import Settings

log = logging.getLogger("api.model")


class Predictor:
    def __init__(self, settings: Settings):
        self.s = settings
        self.modelo: Any = None
        self.metricas: dict = {}
        self.dataset: pd.DataFrame | None = None
        self.categorias: list[str] = []
        self.ciudades: list[str] = []
        self.ciudad_por_cultivo: dict[str, str] = dict(settings.ciudad_por_cultivo)
        self.version: str = "desconocida"
        self.hash: str = ""
        self.cargado_en: float | None = None
        self.recargas: int = 0

    # ------------------------------------------------------------------ carga
    def load(self) -> "Predictor":
        if not self.s.model_path.exists():
            raise RuntimeError(f"No existe {self.s.model_path}. Ejecuta notebooks/entrenamiento.ipynb para generar el modelo.")
        self.modelo = joblib.load(self.s.model_path)
        self.hash = hashlib.sha256(self.s.model_path.read_bytes()).hexdigest()[:12]
        log.info("Modelo cargado desde %s (sha256 %s)", self.s.model_path, self.hash)

        self.metricas = {}
        if self.s.metrics_path.exists():
            self.metricas = json.loads(self.s.metrics_path.read_text(encoding="utf-8"))
            self.categorias = list(self.metricas.get("categorias_cultivo", []))
            self.ciudades = list(self.metricas.get("categorias_ciudad", []))
            if self.metricas.get("ciudad_por_cultivo"):
                self.ciudad_por_cultivo = {str(k).lower(): str(v).lower() for k, v in self.metricas["ciudad_por_cultivo"].items()}
            log.info("Métricas de entrenamiento cargadas (%s)", self.metricas.get("fecha_entrenamiento"))
        self.version = str(self.metricas.get("version") or f"joblib-{self.hash}")

        if self.s.data_path.exists():
            df = pd.read_csv(self.s.data_path)
            df["resultado"] = df["resultado"].astype(str).str.strip().str.upper()
            df[self.s.feature_cat] = df[self.s.feature_cat].astype(str).str.strip().str.lower()
            # `ciudad` acompaña al cultivo: si el CSV no la trae se deduce (cafe→chanchamayo, papa→huancayo, uva→ica)
            if self.s.feature_ciudad not in df.columns:
                df.insert(df.columns.get_loc(self.s.feature_cat) + 1, self.s.feature_ciudad,
                          df[self.s.feature_cat].map(self.ciudad_por_cultivo))
            df[self.s.feature_ciudad] = df[self.s.feature_ciudad].astype(str).str.strip().str.lower()
            df = df.dropna(subset=self.s.features_num + [self.s.feature_cat, "resultado"]).reset_index(drop=True)
            self.dataset = df
            if not self.categorias:
                self.categorias = sorted(df[self.s.feature_cat].unique().tolist())
            if not self.ciudades:
                self.ciudades = sorted(df[self.s.feature_ciudad].dropna().unique().tolist())
            mapa_csv = {str(c): str(v) for c, v in df.groupby(self.s.feature_cat)[self.s.feature_ciudad].first().items()}
            if not self.metricas.get("ciudad_por_cultivo"):
                self.ciudad_por_cultivo.update(mapa_csv)
            log.info("Dataset de referencia cargado: %d filas", len(df))
        self.cargado_en = time.time()
        return self

    def reload(self) -> dict:
        anterior = self.hash
        self.load()
        self.recargas += 1
        return {"ok": True, "hash_anterior": anterior, "hash_actual": self.hash, "cambio": anterior != self.hash,
                "version": self.version, "recargas": self.recargas}

    # ------------------------------------------------------------------ predicción
    @property
    def columnas(self) -> list[str]:
        return self.s.columnas_modelo

    def validar_cultivo(self, cultivo: str) -> str:
        c = str(cultivo).strip().lower()
        if self.categorias and c not in self.categorias:
            raise ValueError(f"cultivo '{c}' no reconocido. Valores válidos: {self.categorias}")
        return c

    def ciudad_de(self, cultivo: str) -> str | None:
        """Ciudad asociada al cultivo (cafe→chanchamayo, papa→huancayo, uva→ica)."""
        return self.ciudad_por_cultivo.get(str(cultivo).strip().lower())

    def completar_ciudad(self, features: dict) -> dict:
        """Normaliza cultivo y ciudad. Si `ciudad` falta se deduce del cultivo; si viene, debe coincidir."""
        f = dict(features)
        cultivo = self.validar_cultivo(f[self.s.feature_cat])
        esperada = self.ciudad_de(cultivo)
        ciudad = f.get(self.s.feature_ciudad)
        ciudad = None if ciudad is None or str(ciudad).strip() == "" else str(ciudad).strip().lower()
        if ciudad is None:
            ciudad = esperada
        elif self.ciudades and ciudad not in self.ciudades:
            raise ValueError(f"ciudad '{ciudad}' no reconocida. Valores válidos: {self.ciudades}")
        elif esperada and ciudad != esperada:
            raise ValueError(f"la ciudad '{ciudad}' no corresponde al cultivo '{cultivo}' (se espera '{esperada}')")
        f[self.s.feature_cat], f[self.s.feature_ciudad] = cultivo, ciudad
        return f

    def _asegurar_ciudad(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.s.feature_ciudad not in df.columns:
            df = df.copy()
            df[self.s.feature_ciudad] = df[self.s.feature_cat].map(self.ciudad_de)
        return df

    def predict_df(self, df: pd.DataFrame, umbral: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
        df = self._asegurar_ciudad(df)
        proba = self.modelo.predict_proba(df[self.columnas])[:, 1]
        return proba, (proba >= umbral).astype(int)

    def predict_one(self, features: dict, umbral: float = 0.5) -> tuple[float, int, float]:
        """→ (probabilidad_si, prediccion, latencia_ms)."""
        t0 = time.perf_counter()
        proba, pred = self.predict_df(pd.DataFrame([features]), umbral)
        return float(proba[0]), int(pred[0]), (time.perf_counter() - t0) * 1000

    # ------------------------------------------------------------------ información
    def info(self) -> dict:
        m = self.metricas
        return {
            "modelo": m.get("modelo", type(self.modelo).__name__ if self.modelo is not None else None),
            "version": self.version,
            "hash": self.hash,
            "fecha_entrenamiento": m.get("fecha_entrenamiento"),
            "sklearn_version": m.get("sklearn_version"),
            "features_numericas": self.s.features_num,
            "feature_categorica": self.s.feature_cat,
            "feature_ciudad": self.s.feature_ciudad,
            "features_categoricas": self.s.features_cat,
            "categorias_cultivo": self.categorias,
            "categorias_ciudad": self.ciudades,
            "ciudad_por_cultivo": self.ciudad_por_cultivo,
            "clases": self.s.clases,
            "rangos": m.get("rangos", {}),
            "medias_entrenamiento": m.get("medias_entrenamiento", {}),
            "n_filas": m.get("n_filas", len(self.dataset) if self.dataset is not None else None),
            "ruta_modelo": str(self.s.model_path.relative_to(self.s.base_dir)),
            "tamano_bytes": self.s.model_path.stat().st_size if self.s.model_path.exists() else None,
            "cargado_en": self.cargado_en,
            "recargas": self.recargas,
            "pipeline": self._describir_pipeline(),
        }

    def _describir_pipeline(self) -> list[dict]:
        pasos = []
        try:
            for nombre, paso in getattr(self.modelo, "steps", []):
                pasos.append({"nombre": nombre, "clase": type(paso).__name__})
        except Exception:  # noqa: BLE001
            pass
        return pasos

    def rangos(self) -> dict[str, list[float]]:
        return self.metricas.get("rangos") or {
            f: [float(self.dataset[f].min()), float(self.dataset[f].max())] for f in self.s.features_num
        }

    def medias(self) -> dict[str, float]:
        return self.metricas.get("medias_entrenamiento") or {f: float(self.dataset[f].mean()) for f in self.s.features_num}

    def desviaciones(self) -> dict[str, float]:
        return self.metricas.get("desviaciones_entrenamiento") or {f: float(self.dataset[f].std()) for f in self.s.features_num}

    # ------------------------------------------------------------------ heatmap
    def heatmap(self, cultivo: str, x: str, y: str, resolucion: int = 20) -> dict:
        cultivo = self.validar_cultivo(cultivo)
        fn = self.s.features_num
        if x not in fn or y not in fn or x == y:
            raise ValueError(f"x e y deben ser distintos y pertenecer a {fn}")
        rangos, medias = self.rangos(), self.medias()
        xs = np.linspace(rangos[x][0], rangos[x][1], resolucion)
        ys = np.linspace(rangos[y][0], rangos[y][1], resolucion)
        gx, gy = np.meshgrid(xs, ys)
        df = pd.DataFrame({f: np.full(gx.size, medias[f]) for f in fn})
        df[x], df[y], df[self.s.feature_cat] = gx.ravel(), gy.ravel(), cultivo
        df[self.s.feature_ciudad] = self.ciudad_de(cultivo)
        proba = self.modelo.predict_proba(df[self.columnas])[:, 1].reshape(resolucion, resolucion)
        return {"cultivo": cultivo, "ciudad": self.ciudad_de(cultivo), "x": x, "y": y, "xs": [round(float(v), 2) for v in xs],
                "ys": [round(float(v), 2) for v in ys], "z": np.round(proba, 4).tolist(),
                "fijas": {f: medias[f] for f in fn if f not in (x, y)}}
