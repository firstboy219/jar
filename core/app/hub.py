"""Live connections to the owner's devices, so background work (workers, reports) can reach the phone
without the phone asking. One owner, possibly several devices: events are broadcast to all of them."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger("jarvis-core.hub")
Sender = Callable[[dict], Awaitable[None]]

_clients: dict[int, Sender] = {}
_taps: list[Sender] = []  # server-side listeners (the desk, ADR-051): they see every event, with or without a device online
_meta: dict[int, dict] = {}
_next_id = 0
_connected = asyncio.Event()


def register(send: Sender, **meta) -> int:
    global _next_id
    _next_id += 1
    _clients[_next_id] = send
    _meta[_next_id] = meta
    _connected.set()
    return _next_id


def unregister(client_id: int) -> None:
    _clients.pop(client_id, None)
    _meta.pop(client_id, None)
    if not _clients:
        _connected.clear()


def clients() -> list[dict]:
    return list(_meta.values())


def online() -> bool:
    return bool(_clients)


def tap(listener: Sender) -> None:
    if listener not in _taps:
        _taps.append(listener)


async def broadcast(event: dict) -> int:
    """Send to every connected device; returns how many got it. Dead sockets are dropped."""
    for t in _taps:
        try:
            await t(event)
        except Exception:  # a listener must never stop an event reaching the owner
            log.exception("hub tap failed")
    delivered = 0
    for cid, send in list(_clients.items()):
        try:
            await send(event)
            delivered += 1
        except Exception:  # socket closed under us
            log.debug("dropping client %s", cid)
            unregister(cid)
    return delivered


async def send_cap(cap: str, event: dict) -> bool:
    """Send to the newest connected device that says it can do `cap` (e.g. the phone that operates apps, ADR-077)."""
    for cid in sorted(_clients, reverse=True):
        if cap in (_meta.get(cid, {}).get("caps") or []):
            try:
                await _clients[cid](event)
                return True
            except Exception:
                log.debug("dropping client %s", cid)
                unregister(cid)
    return False


async def wait_online() -> None:
    await _connected.wait()


def reset() -> None:  # tests
    _clients.clear()
    _meta.clear()
    _connected.clear()
