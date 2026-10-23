"""
api/core/cache.py
-----------------
Cache Manager de dos niveles:

    L1  LocalLRUCache   → en memoria del proceso (OrderedDict + TTL). Siempre activa.
    L2  UpstashRedis    → Redis distribuido vía API REST (UPSTASH_REDIS_REST_URL/TOKEN).
                          Opcional; si no está configurado o falla, el manager sigue
                          funcionando solo con L1 (circuit breaker de 60 s tras errores).

Lectura:  L1 → L2 → (miss).  Un acierto en L2 se copia a L1.
Escritura: L1 y L2 (si está disponible).  Los valores se guardan como JSON.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable

from ..config import Settings

log = logging.getLogger("api.cache")


# --------------------------------------------------------------------------- #
# L1: LRU local
# --------------------------------------------------------------------------- #
class LocalLRUCache:
    def __init__(self, max_items: int = 2048, default_ttl: int = 300):
        self.max_items = max_items
        self.default_ttl = default_ttl
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self.hits = self.misses = self.evictions = self.expirations = self.sets = 0

    def get(self, key: str) -> tuple[bool, Any]:
        item = self._data.get(key)
        if item is None:
            self.misses += 1
            return False, None
        expira, valor = item
        if expira and expira < time.time():
            del self._data[key]
            self.expirations += 1
            self.misses += 1
            return False, None
        self._data.move_to_end(key)
        self.hits += 1
        return True, valor

    def set(self, key: str, valor: Any, ttl: int | None = None) -> None:
        ttl = self.default_ttl if ttl is None else ttl
        expira = time.time() + ttl if ttl > 0 else 0.0
        self._data[key] = (expira, valor)
        self._data.move_to_end(key)
        self.sets += 1
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)
            self.evictions += 1

    def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    def clear(self, prefix: str | None = None) -> int:
        if not prefix:
            n = len(self._data)
            self._data.clear()
            return n
        claves = [k for k in self._data if k.startswith(prefix)]
        for k in claves:
            del self._data[k]
        return len(claves)

    def ttl(self, key: str) -> int | None:
        item = self._data.get(key)
        if item is None:
            return None
        expira = item[0]
        return -1 if not expira else max(0, int(expira - time.time()))

    def keys(self, prefix: str = "", limit: int = 100) -> list[str]:
        return [k for k in reversed(self._data) if k.startswith(prefix)][:limit]

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "tipo": "lru-local", "activa": True, "items": len(self._data), "max_items": self.max_items,
            "hits": self.hits, "misses": self.misses, "sets": self.sets, "evictions": self.evictions,
            "expirations": self.expirations, "hit_ratio": round(self.hits / total, 4) if total else None,
            "ttl_por_defecto_s": self.default_ttl,
        }


# --------------------------------------------------------------------------- #
# L2: Upstash Redis (REST)
# --------------------------------------------------------------------------- #
class UpstashRedis:
    """Cliente mínimo de la API REST de Upstash (https://upstash.com/docs/redis/features/restapi).

    Cada comando es un POST con el array JSON del comando, p. ej. ["SET", "k", "v", "EX", 60].
    """

    BREAKER_S = 60

    def __init__(self, url: str | None, token: str | None, timeout: float = 3.0):
        self.url = url.rstrip("/") if url else None
        self.token = token
        self.timeout = timeout
        self.configurado = bool(url and token)
        self.hits = self.misses = self.sets = self.errores = 0
        self.ultimo_error: str | None = None
        self._abierto_hasta = 0.0  # circuit breaker
        self._client = None

    @property
    def disponible(self) -> bool:
        return self.configurado and time.time() >= self._abierto_hasta

    async def _cmd(self, *args: Any) -> Any:
        import httpx

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, headers={"Authorization": f"Bearer {self.token}"})
        try:
            r = await self._client.post(self.url, json=[str(a) if not isinstance(a, (int, float)) else a for a in args])
            r.raise_for_status()
            datos = r.json()
            if "error" in datos:
                raise RuntimeError(datos["error"])
            return datos.get("result")
        except Exception as exc:  # noqa: BLE001
            self.errores += 1
            self.ultimo_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            self._abierto_hasta = time.time() + self.BREAKER_S
            log.warning("Upstash no disponible (%s); circuito abierto %ss", self.ultimo_error, self.BREAKER_S)
            raise

    async def get(self, key: str) -> tuple[bool, Any]:
        try:
            raw = await self._cmd("GET", key)
        except Exception:  # noqa: BLE001
            return False, None
        if raw is None:
            self.misses += 1
            return False, None
        self.hits += 1
        try:
            return True, json.loads(raw)
        except (TypeError, ValueError):
            return True, raw

    async def set(self, key: str, valor: Any, ttl: int | None) -> bool:
        try:
            args: list[Any] = ["SET", key, json.dumps(valor, ensure_ascii=False)]
            if ttl and ttl > 0:
                args += ["EX", int(ttl)]
            await self._cmd(*args)
            self.sets += 1
            return True
        except Exception:  # noqa: BLE001
            return False

    async def delete(self, key: str) -> bool:
        try:
            return bool(await self._cmd("DEL", key))
        except Exception:  # noqa: BLE001
            return False

    async def clear(self, prefix: str) -> int:
        borradas, cursor = 0, "0"
        try:
            while True:
                cursor, claves = await self._cmd("SCAN", cursor, "MATCH", f"{prefix}*", "COUNT", 500)
                if claves:
                    borradas += int(await self._cmd("DEL", *claves) or 0)
                if str(cursor) == "0":
                    break
        except Exception:  # noqa: BLE001
            pass
        return borradas

    async def ping(self) -> dict:
        if not self.configurado:
            return {"activa": False, "detalle": "UPSTASH_REDIS_REST_URL/TOKEN no configurados"}
        if not self.disponible:
            return {"activa": False, "detalle": f"circuito abierto ({self.ultimo_error})",
                    "reintento_en_s": int(self._abierto_hasta - time.time())}
        t0 = time.perf_counter()
        try:
            res = await self._cmd("PING")
            return {"activa": res == "PONG", "latencia_ms": round((time.perf_counter() - t0) * 1000, 2)}
        except Exception:  # noqa: BLE001
            return {"activa": False, "detalle": self.ultimo_error}

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "tipo": "upstash-redis", "configurado": self.configurado, "activa": self.disponible,
            "url": (self.url.split("//")[-1].split(".")[0] + ".upstash.io") if self.url else None,
            "hits": self.hits, "misses": self.misses, "sets": self.sets, "errores": self.errores,
            "ultimo_error": self.ultimo_error, "hit_ratio": round(self.hits / total, 4) if total else None,
        }

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


# --------------------------------------------------------------------------- #
# Cache Manager
# --------------------------------------------------------------------------- #
class CacheManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.prefix = settings.cache_prefix
        self.l1 = LocalLRUCache(settings.cache_max_items, settings.cache_ttl_s)
        self.l2 = UpstashRedis(settings.upstash_url, settings.upstash_token)
        self.creado = time.time()
        self._locks: dict[str, asyncio.Lock] = {}

    # ---------------------------------------------------------------- básicos
    def _k(self, key: str) -> str:
        return key if key.startswith(self.prefix) else f"{self.prefix}{key}"

    async def get(self, key: str) -> tuple[bool, Any, str | None]:
        """Devuelve (encontrado, valor, nivel) donde nivel ∈ {'local', 'upstash', None}."""
        k = self._k(key)
        ok, valor = self.l1.get(k)
        if ok:
            return True, valor, "local"
        if self.l2.disponible:
            ok, valor = await self.l2.get(k)
            if ok:
                self.l1.set(k, valor)
                return True, valor, "upstash"
        return False, None, None

    async def set(self, key: str, valor: Any, ttl: int | None = None) -> dict:
        k = self._k(key)
        ttl = self.settings.cache_ttl_s if ttl is None else ttl
        self.l1.set(k, valor, ttl)
        en_l2 = await self.l2.set(k, valor, ttl) if self.l2.disponible else False
        return {"key": k, "ttl_s": ttl, "niveles": ["local"] + (["upstash"] if en_l2 else [])}

    async def delete(self, key: str) -> dict:
        k = self._k(key)
        local = self.l1.delete(k)
        remoto = await self.l2.delete(k) if self.l2.disponible else False
        return {"key": k, "eliminada": local or remoto, "niveles": {"local": local, "upstash": remoto}}

    async def clear(self, prefix: str | None = None) -> dict:
        p = self._k(prefix) if prefix else self.prefix
        local = self.l1.clear(p)
        remoto = await self.l2.clear(p) if self.l2.disponible else 0
        return {"prefijo": p, "eliminadas": {"local": local, "upstash": remoto}}

    async def get_or_compute(self, key: str, fn: Callable[[], Awaitable[Any] | Any], ttl: int | None = None) -> tuple[Any, bool, str | None]:
        """Patrón cache-aside con lock por clave para evitar estampidas."""
        ok, valor, nivel = await self.get(key)
        if ok:
            return valor, True, nivel
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            ok, valor, nivel = await self.get(key)
            if ok:
                return valor, True, nivel
            valor = fn()
            if asyncio.iscoroutine(valor):
                valor = await valor
            await self.set(key, valor, ttl)
            return valor, False, None

    def ttl(self, key: str) -> int | None:
        return self.l1.ttl(self._k(key))

    def keys(self, prefix: str = "", limit: int = 100) -> list[str]:
        return self.l1.keys(self._k(prefix) if prefix else self.prefix, limit)

    # ---------------------------------------------------------------- estado
    def stats(self) -> dict:
        s1, s2 = self.l1.stats(), self.l2.stats()
        hits = s1["hits"] + s2["hits"]
        misses = s1["misses"] if not s2["configurado"] else s2["misses"]
        total = hits + misses
        grupos: dict[str, int] = {}
        for k in self.l1.keys(self.prefix, limit=100000):
            g = k[len(self.prefix):].split(":", 1)[0]
            grupos[g] = grupos.get(g, 0) + 1
        return {
            "prefijo": self.prefix, "estrategia": "cache-aside L1 (LRU local) → L2 (Upstash Redis)",
            "hit_ratio_global": round(hits / total, 4) if total else None,
            "niveles": {"local": s1, "upstash": s2}, "claves_por_grupo": grupos,
            "uptime_s": round(time.time() - self.creado, 1),
        }

    async def health(self) -> dict:
        l2 = await self.l2.ping()
        status = "ok" if (not self.l2.configurado or l2.get("activa")) else "degraded"
        return {"status": status, "niveles": {"local": {"activa": True, "items": len(self.l1._data)}, "upstash": {**l2, "configurado": self.l2.configurado}}}

    async def close(self) -> None:
        await self.l2.close()
