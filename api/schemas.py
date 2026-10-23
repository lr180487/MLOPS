"""
api/schemas.py — Esquemas Pydantic de entrada/salida de la API.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------- predicción
class Observacion(BaseModel):
    cultivo: str = Field(..., examples=["cafe"], description="Tipo de cultivo: cafe | papa | uva")
    ciudad: str | None = Field(
        None, examples=["chanchamayo"],
        description="Ciudad asociada al cultivo (cafe→chanchamayo, papa→huancayo, uva→ica). "
                    "Opcional: si se omite se deduce del cultivo; si se envía debe corresponder al cultivo.",
    )
    temperatura: float = Field(..., ge=-10, le=50, examples=[21.0], description="°C")
    humedad: float = Field(..., ge=0, le=100, examples=[80.0], description="% humedad relativa")
    radiacion_solar: float = Field(..., ge=0, le=40, examples=[16.0], description="MJ/m²")
    precipitacion: float = Field(..., ge=0, le=100, examples=[12.0], description="mm")
    viento: float = Field(..., ge=0, le=60, examples=[5.0], description="km/h")

    @field_validator("cultivo")
    @classmethod
    def normalizar_cultivo(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("ciudad")
    @classmethod
    def normalizar_ciudad(cls, v: str | None) -> str | None:
        v = (v or "").strip().lower()
        return v or None


class ObservacionConUmbral(Observacion):
    umbral: float | None = Field(None, ge=0.05, le=0.95, description="Umbral de decisión (por defecto 0.5)")


class PrediccionOut(BaseModel):
    id: str
    prediccion: Literal["SI", "NO"]
    probabilidad_si: float
    probabilidad_no: float
    umbral: float
    latencia_ms: float
    timestamp: str
    cache_hit: bool = False
    cache_nivel: str | None = None
    modelo_version: str | None = None
    features: dict[str, Any] | None = None


class LoteObservaciones(BaseModel):
    observaciones: list[Observacion] = Field(..., min_length=1, max_length=500)
    umbral: float | None = Field(None, ge=0.05, le=0.95)


class FeedbackIn(BaseModel):
    prediction_id: str = Field(..., description="id devuelto por POST /api/predictions")
    real: Literal["SI", "NO"]
    comentario: str | None = Field(None, max_length=500)


class FeedbackLegacy(BaseModel):
    id: str = Field(..., description="id devuelto por /predict")
    real: Literal["SI", "NO"]


# ---------------------------------------------------------------- caché
class CacheValor(BaseModel):
    value: Any = Field(..., description="Valor serializable a JSON")
    ttl: int | None = Field(None, ge=0, le=86400 * 7, description="Segundos de vida (0 = sin expiración)")



# ---------------------------------------------------------------- simulador
class SimuladorStart(BaseModel):
    intervalo: float | None = Field(None, ge=0.2, le=60, description="Segundos entre eventos")


class SimuladorBurst(BaseModel):
    cantidad: int = Field(20, ge=1, le=200)


class ControlSimuladorLegacy(BaseModel):
    accion: Literal["start", "stop", "speed", "burst"]
    intervalo: float | None = Field(None, ge=0.2, le=60)
    cantidad: int | None = Field(None, ge=1, le=200)
