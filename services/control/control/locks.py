"""Contrôle exclusif d'un téléphone : bail renouvelable et numéro de génération (N04, N05, RF09)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .models import Controller


class LeaseLost(RuntimeError):
    pass


@dataclass(frozen=True)
class Lease:
    device_id: str
    owner: str
    kind: Controller
    generation: int


@dataclass
class _Holder:
    lease: Lease
    expires_at: float


class DeviceLocks:
    def __init__(self, ttl_s: float = 30.0):
        self.ttl_s = ttl_s
        self._holders: dict[str, _Holder] = {}
        self._generation: dict[str, int] = {}
        self._cond = asyncio.Condition()

    def _expired(self, device_id: str) -> bool:
        h = self._holders.get(device_id)
        return h is None or h.expires_at < time.monotonic()

    def holder(self, device_id: str) -> Lease | None:
        return None if self._expired(device_id) else self._holders[device_id].lease

    def try_acquire(self, device_id: str, owner: str, kind: Controller) -> Lease | None:
        current = self.holder(device_id)
        if current is not None and current.owner != owner:
            return None
        if current is not None:
            self._holders[device_id].expires_at = time.monotonic() + self.ttl_s
            return current
        gen = self._generation.get(device_id, 0) + 1
        self._generation[device_id] = gen
        lease = Lease(device_id, owner, kind, gen)
        self._holders[device_id] = _Holder(lease, time.monotonic() + self.ttl_s)
        return lease

    async def acquire(
        self, device_id: str, owner: str, kind: Controller, timeout: float | None = None
    ) -> Lease:
        async def _wait() -> Lease:
            async with self._cond:
                while True:
                    lease = self.try_acquire(device_id, owner, kind)
                    if lease:
                        return lease
                    try:
                        await asyncio.wait_for(
                            self._cond.wait(), 1.0
                        )  # réveil périodique pour les baux expirés
                    except TimeoutError:
                        pass

        return await asyncio.wait_for(_wait(), timeout)

    def validate(self, lease: Lease) -> None:
        """À appeler juste avant chaque injection : un ancien détenteur ne peut plus agir."""
        current = self.holder(lease.device_id)
        if current is None or current.generation != lease.generation or current.owner != lease.owner:
            raise LeaseLost(f"contrôle de {lease.device_id} perdu (génération {lease.generation})")

    def renew(self, lease: Lease) -> None:
        self.validate(lease)
        self._holders[lease.device_id].expires_at = time.monotonic() + self.ttl_s

    async def release(self, lease: Lease) -> None:
        async with self._cond:
            h = self._holders.get(lease.device_id)
            if h and h.lease.generation == lease.generation:
                del self._holders[lease.device_id]
            self._cond.notify_all()
