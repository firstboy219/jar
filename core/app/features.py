"""Every feature module of the app v2 (ADR-087). Importing this registers each one's front-page provider, setup check, clock ticks, habit
actions and API router — the API (appapi) and the clock (appclock) both import it, so nothing is registered twice or forgotten."""

from . import attention, bisnis, brief, coffee, commute, habits, ibadah, invest, meeting_live, money, outlook, quran, recap, weather  # noqa: F401

ROUTERS = [m.router for m in (ibadah, quran, brief, habits, commute, recap, attention, meeting_live, bisnis, money, invest, coffee) if hasattr(m, "router")]
