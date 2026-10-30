"""Is each feature ready, and if not, what to connect first (ADR-087). A feature is never hidden for missing setup: the catalog shows it
with what is still needed ("Hubungkan Outlook", "Isi API bisnis", "Izinkan lokasi"), and the screen itself says how to do it.

Feature modules register their own check with @check('<feature id>'); each returns {"ready": bool, "setup": str, "setup_route": str}."""

import asyncio
import logging

log = logging.getLogger("jarvis-core")
CHECKS: dict = {}


def check(feature: str):
    def wrap(fn):
        CHECKS[feature] = fn
        return fn
    return wrap


def ready() -> dict:
    return {"ready": True, "setup": "", "setup_route": ""}


def needs(text: str, route: str = "") -> dict:
    return {"ready": False, "setup": text, "setup_route": route}


async def all_status() -> dict:
    names = list(CHECKS)
    got = await asyncio.gather(*(asyncio.wait_for(CHECKS[n](), 4.0) for n in names), return_exceptions=True)
    out = {}
    for n, g in zip(names, got):
        if isinstance(g, Exception):
            log.warning("setup check %s failed: %s", n, g)
            out[n] = needs("belum bisa diperiksa")
        else:
            out[n] = g
    return out


@check("berangkat")
async def _commute_out() -> dict:
    from . import places
    have = {p["name"] for p in await places.listing()}
    if not {"rumah", "kantor"} <= have:
        return needs("Izinkan lokasi di HP (JARVIS mempelajari rumah & kantor), atau isi sendiri", "#/kebiasaan")
    return ready()


@check("pulang")
async def _commute_back() -> dict:
    return await _commute_out()


@check("kamera")
async def _camera() -> dict:
    from . import hub
    return ready() if any("measure" in (c.get("caps") or []) for c in hub.clients()) else needs("Perlu aplikasi JARVIS versi baru di HP", "#/kontrol")
