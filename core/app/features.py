"""Every feature module of the app v2 (ADR-087). Importing this registers each one's front-page provider, setup check, clock ticks and API
router — the API (appapi) and the clock (appclock) both import it, so nothing is registered twice or forgotten."""

from . import brief, ibadah, quran, weather  # noqa: F401

ROUTERS = [m.router for m in (ibadah, quran, brief) if hasattr(m, "router")]
