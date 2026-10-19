"""Bus d'événements : identifiants monotones persistés et reprise après reconnexion (E12, U05)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from .db import Store
from .models import Event, EventIn

log = logging.getLogger(__name__)


class EventBus:
    def __init__(self, store: Store):
        self.store = store
        self._subscribers: set[asyncio.Queue[Event]] = set()

    async def emit(self, type: str, summary: str, **kw) -> Event:
        event = await self.store.add_event(EventIn(type=type, summary=summary, **kw))
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("abonné trop lent : événements ignorés, il rattrapera par identifiant")
        return event

    async def stream(self, after_id: int = 0) -> AsyncIterator[Event]:
        """Rejoue depuis la base les événements manqués, puis suit le direct sans doublon."""
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        try:
            last = after_id
            while True:
                backlog = await self.store.events_after(last)
                for e in backlog:
                    last = e.id
                    yield e
                if len(backlog) < 500:
                    break
            while True:
                e = await q.get()
                if e.id <= last:
                    continue
                if e.id > last + 1:  # trou : file saturée ou diffusion désordonnée
                    for missed in await self.store.events_after(last):
                        if missed.id >= e.id:
                            break
                        last = missed.id
                        yield missed
                last = e.id
                yield e
        finally:
            self._subscribers.discard(q)
