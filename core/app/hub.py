"""Live connections to the owner's devices, so background work (workers, reports) can reach the phone
without the phone asking. One owner, possibly several devices: events are broadcast to all of them."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger("jarvis-core.hub")
Sender = Callable[[dict], Awaitable[None]]

_clients: dict[int, Sender] = {}
_next_id = 0
_connected = asyncio.Event()


def register(send: Sender) -> int:
    global _next_id
    _next_id += 1
    _clients[_next_id] = send
    _connected.set()
    return _next_id


def unregister(client_id: int) -> None:
    _clients.pop(client_id, None)
    if not _clients:
        _connected.clear()


def online() -> bool:
    return bool(_clients)


async def broadcast(event: dict) -> int:
    """Send to every connected device; returns how many got it. Dead sockets are dropped."""
    delivered = 0
    for cid, send in list(_clients.items()):
        try:
            await send(event)
            delivered += 1
        except Exception:  # socket closed under us
            log.debug("dropping client %s", cid)
            unregister(cid)
    return delivered


async def wait_online() -> None:
    await _connected.wait()


def reset() -> None:  # tests
    _clients.clear()
    _connected.clear()
