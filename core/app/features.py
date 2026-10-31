"""Every feature module of the app v2 (ADR-087). Importing this registers each one's front-page provider, setup check, clock ticks, habit
actions and API router — the API (appapi) and the clock (appclock) both import it, so nothing is registered twice or forgotten."""

from . import (alur, attention, bengkel, berkas, bimbing, bioskop, bisnis, brief, coffee, commute, diskspace, dongeng, habits, ibadah, invest, karier, meeting_live, money,  # noqa: F401
               musik, musiclibrary, outlook, quran, recap, ukur, video, weather, webagent)

ROUTERS = [m.router for m in (ibadah, quran, brief, habits, commute, recap, attention, meeting_live, bisnis, money, invest, coffee,
                                 musiclibrary, musik, video, berkas, bioskop, dongeng, ukur, bimbing, alur, bengkel, karier, webagent, diskspace) if hasattr(m, "router")]
