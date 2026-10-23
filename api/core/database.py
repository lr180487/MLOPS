"""
api/core/database.py
--------------------
Capa de persistencia con dos backends intercambiables:

  * PostgreSQL               → si existe DATABASE_URL y la conexión funciona.
  * SQLite                   → fallback automático (desarrollo / contingencia).

Las consultas se escriben una sola vez con marcadores `?`; para PostgreSQL se
traducen a `%s`. Las diferencias de DDL (tipos numéricos/JSON) se resuelven aquí.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from ..config import Settings

log = logging.getLogger("api.db")

# --------------------------------------------------------------------------- #
# Esquema
# --------------------------------------------------------------------------- #
TABLAS = ["predictions", "feedback"]


def ddl(backend: str) -> list[str]:
    real = "DOUBLE PRECISION" if backend == "postgresql" else "REAL"
    return [
        f"""CREATE TABLE IF NOT EXISTS predictions (
                id TEXT PRIMARY KEY,
                ts TEXT NOT NULL,
                origen TEXT NOT NULL,
                cultivo TEXT NOT NULL,
                ciudad TEXT,
                temperatura {real}, humedad {real}, radiacion_solar {real}, precipitacion {real}, viento {real},
                probabilidad_si {real} NOT NULL,
                prediccion INTEGER NOT NULL,
                umbral {real} NOT NULL,
                etiqueta_real INTEGER,
                latencia_ms {real},
                modelo_version TEXT,
                cache_hit INTEGER DEFAULT 0
            )""",
        "CREATE INDEX IF NOT EXISTS ix_predictions_ts ON predictions (ts)",
        "CREATE INDEX IF NOT EXISTS ix_predictions_cultivo ON predictions (cultivo)",
        "CREATE INDEX IF NOT EXISTS ix_predictions_ciudad ON predictions (ciudad)",
        f"""CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                prediction_id TEXT NOT NULL REFERENCES predictions(id) ON DELETE CASCADE,
                ts TEXT NOT NULL,
                etiqueta_real INTEGER NOT NULL,
                prediccion INTEGER NOT NULL,
                acierto INTEGER NOT NULL,
                comentario TEXT,
                origen TEXT
            )""",
        "CREATE INDEX IF NOT EXISTS ix_feedback_prediction ON feedback (prediction_id)",
        # tablas del antiguo asistente RAG (eliminado): se retiran si quedaron de una versión anterior
        "DROP TABLE IF EXISTS embeddings",
        "DROP TABLE IF EXISTS documents",
    ]


# Migraciones aditivas: (tabla, columna, tipo). Se aplican a bases creadas por versiones anteriores.
MIGRACIONES_COLUMNAS = [("predictions", "ciudad", "TEXT")]
# Relleno de `ciudad` para filas antiguas (misma regla que el modelo: cafe→chanchamayo, papa→huancayo, uva→ica)
CIUDAD_POR_CULTIVO = {"cafe": "chanchamayo", "papa": "huancayo", "uva": "ica"}


def _migrar(ejecutar, columnas_existentes, backend: str) -> list[str]:
    """Añade columnas nuevas a tablas ya creadas y rellena `ciudad` donde falte. Devuelve lo aplicado."""
    aplicadas: list[str] = []
    for tabla, columna, tipo in MIGRACIONES_COLUMNAS:
        if columna in columnas_existentes(tabla):
            continue
        ejecutar(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
        aplicadas.append(f"{tabla}.{columna}")
    for cultivo, ciudad in CIUDAD_POR_CULTIVO.items():
        marcador = "%s" if backend == "postgresql" else "?"
        ejecutar(f"UPDATE predictions SET ciudad = {marcador} WHERE ciudad IS NULL AND cultivo = {marcador}", (ciudad, cultivo))
    ejecutar("CREATE INDEX IF NOT EXISTS ix_predictions_ciudad ON predictions (ciudad)")
    return aplicadas


# --------------------------------------------------------------------------- #
# Base de datos
# --------------------------------------------------------------------------- #
class Database:
    """Conexión única protegida con un lock (suficiente para la práctica).

    Uso:
        db = Database(settings); db.connect()
        db.execute("INSERT INTO t (a) VALUES (?)", (1,))
        fila = db.execute("SELECT * FROM t WHERE a = ?", (1,), fetch="one")
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.backend: str = "sqlite"
        self.fallback_reason: str | None = None
        self.dsn_publico: str | None = None
        self.conectado_en: float | None = None
        self._conn: Any = None
        self._lock = threading.RLock()
        self.consultas: int = 0
        self.errores: int = 0

    # ------------------------------------------------------------------ conexión
    def connect(self) -> "Database":
        if self.settings.database_url:
            try:
                self._conectar_postgres(self.settings.database_url)
                log.info("Persistencia: PostgreSQL (%s)", self.dsn_publico)
                return self
            except Exception as exc:  # noqa: BLE001 — cualquier fallo → SQLite
                self.fallback_reason = f"{type(exc).__name__}: {str(exc).strip()[:200]}"
                log.warning("PostgreSQL no disponible (%s). Usando SQLite como fallback.", self.fallback_reason)
        else:
            self.fallback_reason = "DATABASE_URL no configurada"
        self._conectar_sqlite(self.settings.sqlite_path)
        log.info("Persistencia: SQLite (%s)", self.settings.sqlite_path)
        return self

    def _conectar_postgres(self, url: str) -> None:
        import psycopg  # import perezoso: solo hace falta si se usa PostgreSQL
        from psycopg.rows import dict_row

        conn = psycopg.connect(url, autocommit=True, connect_timeout=self.settings.db_connect_timeout_s,
                               row_factory=dict_row)
        with conn.cursor() as cur:
            for sentencia in ddl("postgresql"):
                if "ix_predictions_ciudad" in sentencia:
                    continue  # se crea en _migrar, cuando la columna ya existe
                cur.execute(sentencia)

            def columnas(tabla: str) -> set[str]:
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (tabla,))
                return {r["column_name"] for r in cur.fetchall()}

            aplicadas = _migrar(lambda sql, params=(): cur.execute(sql, params), columnas, "postgresql")
        if aplicadas:
            log.info("Migración aplicada (PostgreSQL): %s", ", ".join(aplicadas))
        self._conn = conn
        self.backend = "postgresql"
        self.conectado_en = time.time()
        self.dsn_publico = self._ocultar_credenciales(url)

    def _conectar_sqlite(self, ruta: Path) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(ruta), check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        for sentencia in ddl("sqlite"):
            if "ix_predictions_ciudad" in sentencia:
                continue  # se crea en _migrar, cuando la columna ya existe
            conn.execute(sentencia)

        def columnas(tabla: str) -> set[str]:
            return {r[1] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}

        aplicadas = _migrar(lambda sql, params=(): conn.execute(sql, params), columnas, "sqlite")
        conn.commit()
        if aplicadas:
            log.info("Migración aplicada (SQLite): %s", ", ".join(aplicadas))
        self._conn = conn
        self.backend = "sqlite"
        self.conectado_en = time.time()
        try:
            self.dsn_publico = f"sqlite:///{ruta.relative_to(self.settings.base_dir)}"
        except ValueError:  # SQLITE_PATH absoluto fuera del proyecto
            self.dsn_publico = f"sqlite:///{ruta}"

    @staticmethod
    def _ocultar_credenciales(url: str) -> str:
        if "@" not in url:
            return url
        esquema, resto = url.split("://", 1) if "://" in url else ("", url)
        credenciales, host = resto.rsplit("@", 1)
        usuario = credenciales.split(":", 1)[0]
        return f"{esquema}://{usuario}:***@{host}"

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None

    # ------------------------------------------------------------------ consultas
    def _adaptar(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.backend == "postgresql" else sql

    def execute(self, sql: str, params: Iterable[Any] = (), fetch: str | None = None) -> Any:
        """Ejecuta una sentencia. fetch: None | 'one' | 'all' (filas como dict)."""
        params = tuple(params)
        with self._lock:
            self.consultas += 1
            try:
                return self._execute(sql, params, fetch)
            except Exception as exc:  # noqa: BLE001
                self.errores += 1
                if self.backend == "postgresql" and self._reconectar_si_procede(exc):
                    return self._execute(sql, params, fetch)
                raise

    def _execute(self, sql: str, params: tuple, fetch: str | None) -> Any:
        if self.backend == "postgresql":
            with self._conn.cursor() as cur:
                cur.execute(self._adaptar(sql), params)
                if fetch == "one":
                    return cur.fetchone()
                if fetch == "all":
                    return cur.fetchall()
                return cur.rowcount
        cur = self._conn.execute(sql, params)
        if fetch == "one":
            fila = cur.fetchone()
            return dict(fila) if fila is not None else None
        if fetch == "all":
            return [dict(f) for f in cur.fetchall()]
        self._conn.commit()
        return cur.rowcount

    def executemany(self, sql: str, filas: Iterable[Iterable[Any]]) -> int:
        filas = [tuple(f) for f in filas]
        if not filas:
            return 0
        with self._lock:
            self.consultas += 1
            if self.backend == "postgresql":
                with self._conn.cursor() as cur:
                    cur.executemany(self._adaptar(sql), filas)
                return len(filas)
            self._conn.executemany(sql, filas)
            self._conn.commit()
            return len(filas)

    def _reconectar_si_procede(self, exc: Exception) -> bool:
        try:
            import psycopg

            if isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
                log.warning("Conexión PostgreSQL perdida (%s); reconectando…", exc)
                self._conectar_postgres(self.settings.database_url)  # type: ignore[arg-type]
                return True
        except Exception as exc2:  # noqa: BLE001
            log.error("No se pudo reconectar a PostgreSQL: %s", exc2)
        return False

    # ------------------------------------------------------------------ utilidades
    def json_dump(self, valor: Any) -> Any:
        """Serializa metadatos según el backend (JSONB acepta str JSON vía psycopg Jsonb)."""
        if valor is None:
            return None
        if self.backend == "postgresql":
            from psycopg.types.json import Jsonb

            return Jsonb(valor)
        return json.dumps(valor, ensure_ascii=False)

    @staticmethod
    def json_load(valor: Any) -> Any:
        if valor is None or isinstance(valor, (dict, list)):
            return valor
        try:
            return json.loads(valor)
        except (TypeError, ValueError):
            return valor

    def ping(self) -> float:
        t0 = time.perf_counter()
        self.execute("SELECT 1", fetch="one")
        return round((time.perf_counter() - t0) * 1000, 3)

    def counts(self) -> dict[str, int]:
        salida = {}
        for t in TABLAS:
            fila = self.execute(f"SELECT COUNT(*) AS n FROM {t}", fetch="one")
            salida[t] = int(fila["n"]) if fila else 0
        return salida

    def health(self) -> dict:
        info = {
            "backend": self.backend,
            "dsn": self.dsn_publico,
            "fallback": self.backend == "sqlite" and bool(self.settings.database_url),
            "fallback_reason": self.fallback_reason,
            "consultas": self.consultas,
            "errores": self.errores,
            "conectado_desde": self.conectado_en,
        }
        try:
            info["latencia_ms"] = self.ping()
            info["tablas"] = self.counts()
            info["status"] = "ok"
            if self.backend == "sqlite":
                ruta = self.settings.sqlite_path
                try:
                    info["archivo"] = str(ruta.relative_to(self.settings.base_dir))
                except ValueError:          # SQLITE_PATH absoluto fuera del proyecto
                    info["archivo"] = str(ruta)
                info["tamano_bytes"] = ruta.stat().st_size if ruta.exists() else 0
        except Exception as exc:  # noqa: BLE001
            info["status"] = "error"
            info["detalle"] = str(exc)
        return info
