"""
api/config.py
-------------
Configuración centralizada de la API. Todo se lee de variables de entorno (o de
un archivo `.env` en la raíz del proyecto) y tiene valores por defecto que
funcionan en local sin ningún servicio externo:

    DATABASE_URL              postgresql://usuario:clave@host:5432/mlops  (opcional → SQLite)
    SQLITE_PATH               storage/mlops.sqlite3                       (fallback)
    UPSTASH_REDIS_REST_URL    https://xxxx.upstash.io                     (opcional → solo LRU local)
    UPSTASH_REDIS_REST_TOKEN  token REST de Upstash
    CACHE_TTL_S               300      TTL por defecto de la caché (segundos)
    CACHE_MAX_ITEMS           2048     tamaño máximo de la LRU local
    SIMULATOR_ENABLED         1        arranca el simulador de tráfico
    SIMULATOR_INTERVAL_S      2.0      segundos entre eventos simulados
    LOG_LEVEL                 INFO
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """Carga un .env sencillo (CLAVE=valor) sin sobrescribir variables ya definidas."""
    if not path.exists():
        return
    for linea in path.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave, valor = clave.strip(), valor.strip().strip('"').strip("'")
        os.environ.setdefault(clave, valor)


load_dotenv(BASE_DIR / ".env")


def _ruta_relativa(ruta: Path, base: Path) -> str:
    """Ruta relativa a la base si está dentro; si no (p. ej. SQLITE_PATH absoluto), la ruta tal cual."""
    try:
        return str(ruta.relative_to(base))
    except ValueError:
        return str(ruta)


def _bool(nombre: str, por_defecto: bool) -> bool:
    v = os.getenv(nombre)
    return por_defecto if v is None else v.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _float(nombre: str, por_defecto: float) -> float:
    try:
        return float(os.getenv(nombre, por_defecto))
    except ValueError:
        return por_defecto


def _int(nombre: str, por_defecto: int) -> int:
    try:
        return int(os.getenv(nombre, por_defecto))
    except ValueError:
        return por_defecto


@dataclass
class Settings:
    app_name: str = "Práctica MLOps – API"
    app_version: str = "2.1.0"
    base_dir: Path = BASE_DIR

    # artefactos
    model_path: Path = BASE_DIR / "models" / "modelo.joblib"
    metrics_path: Path = BASE_DIR / "models" / "metricas.json"
    data_path: Path = BASE_DIR / "data" / "datos.csv"
    result_path: Path = BASE_DIR / "output" / "resultado.json"
    logs_dir: Path = BASE_DIR / "logs"
    dashboard_dir: Path = BASE_DIR / "dashboard"

    # persistencia
    database_url: str | None = os.getenv("DATABASE_URL") or None
    sqlite_path: Path = BASE_DIR / os.getenv("SQLITE_PATH", "storage/mlops.sqlite3")
    db_connect_timeout_s: int = _int("DB_CONNECT_TIMEOUT_S", 5)

    # caché
    upstash_url: str | None = os.getenv("UPSTASH_REDIS_REST_URL") or None
    upstash_token: str | None = os.getenv("UPSTASH_REDIS_REST_TOKEN") or None
    cache_ttl_s: int = _int("CACHE_TTL_S", 300)
    cache_max_items: int = _int("CACHE_MAX_ITEMS", 2048)
    cache_prefix: str = os.getenv("CACHE_PREFIX", "mlops:")


    # monitoreo / simulador
    window: int = _int("METRICS_WINDOW", 50)
    history_max: int = _int("METRICS_HISTORY", 500)
    simulator_enabled: bool = _bool("SIMULATOR_ENABLED", True)
    static_exports: bool = _bool("STATIC_EXPORTS", True)      # copias en output/exportaciones al arrancar
    analysis_precompute: bool = _bool("ANALISIS_PRECALCULAR", True)   # precalcula /api/analisis/* por defecto al arrancar
    simulator_interval_s: float = _float("SIMULATOR_INTERVAL_S", 2.0)
    warmup_events: int = _int("WARMUP_EVENTS", 30)

    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

    features_num: list[str] = field(default_factory=lambda: ["temperatura", "humedad", "radiacion_solar", "precipitacion", "viento"])
    feature_cat: str = "cultivo"
    feature_ciudad: str = "ciudad"                    # variable predictora asociada 1:1 al cultivo
    ciudad_por_cultivo: dict[str, str] = field(default_factory=lambda: {"cafe": "chanchamayo", "papa": "huancayo", "uva": "ica"})
    clases: list[str] = field(default_factory=lambda: ["NO", "SI"])

    @property
    def features_cat(self) -> list[str]:
        return [self.feature_cat, self.feature_ciudad]

    @property
    def columnas_modelo(self) -> list[str]:
        return self.features_num + self.features_cat

    def resumen_publico(self) -> dict:
        """Configuración sin secretos, para /api/system/info."""
        return {
            "database_url_configurada": bool(self.database_url),
            "sqlite_path": _ruta_relativa(self.sqlite_path, self.base_dir),
            "upstash_configurado": bool(self.upstash_url and self.upstash_token),
            "cache_ttl_s": self.cache_ttl_s,
            "cache_max_items": self.cache_max_items,
            "window": self.window,
            "history_max": self.history_max,
            "simulator_enabled": self.simulator_enabled,
            "static_exports": self.static_exports,
            "analysis_precompute": self.analysis_precompute,
            "simulator_interval_s": self.simulator_interval_s,
        }


settings = Settings()
