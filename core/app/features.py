"""Every feature module of the app v2 (ADR-087). Importing this registers each one's front-page provider, setup check, clock ticks, habit
actions and API router — the API (appapi) and the clock (appclock) both import it, so nothing is registered twice or forgotten."""

from . import (attention, berkas, bimbing, bioskop, bisnis, brief, coffee, commute, dongeng, habits, ibadah, invest, meeting_live, money,  # noqa: F401
               musik, outlook, quran, recap, ukur, video, weather)

ROUTERS = [m.router for m in (ibadah, quran, brief, habits, commute, recap, attention, meeting_live, bisnis, money, invest, coffee,
                                 musik, video, berkas, bioskop, dongeng, ukur, bimbing) if hasattr(m, "router")]
