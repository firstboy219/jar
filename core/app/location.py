"""Phone location shared by the APK (opt-in in the app) → context for the agent and quick answers."""

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from . import db


class Location(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)
    age_s: int | None = Field(default=None, ge=0, le=86_400)  # how old the fix was when sent
    address: str | None = Field(default=None, max_length=300)  # reverse-geocoded on the phone

    def describe(self) -> str:
        where = self.address or f"{self.lat:.5f}, {self.lon:.5f}"
        acc = f" ±{round(self.accuracy_m)} m" if self.accuracy_m is not None else ""
        age = ""
        if self.age_s is not None and self.age_s >= 120:
            age = f", diambil {self.age_s // 60} menit lalu"
        return f"{where} ({self.lat:.5f}, {self.lon:.5f}{acc}{age})"

    def maps_url(self) -> str:
        return f"https://maps.google.com/?q={self.lat:.6f},{self.lon:.6f}"


_DAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
_MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
           "Oktober", "November", "Desember"]
WIB = timezone(timedelta(hours=7), "WIB")


def context_prefix(loc: "Location | None", now: datetime | None = None) -> str:
    """Device context prepended to the user's message for Hermes (not stored in the message log)."""
    t = (now or datetime.now(timezone.utc)).astimezone(WIB)
    parts = [f"waktu {_DAYS[t.weekday()]} {t.day} {_MONTHS[t.month - 1]} {t.year} {t:%H:%M} WIB"]
    if loc:
        parts.append(f"lokasi HP pemilik: {loc.describe()}")
    return "[Konteks perangkat — " + "; ".join(parts) + "]\n\n"


async def remember_last(loc: Location) -> None:
    """Latest known owner location (for proactive features); a single row, overwritten each time."""
    await db.pool().execute(
        """INSERT INTO settings_kv (key, value) VALUES ('last_location', $1)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        loc.model_dump() | {"received_at": datetime.now(timezone.utc).isoformat()})
    if loc.age_s is None or loc.age_s < 600:   # the trail of places (ADR-087): only fixes that say where the owner is now
        from . import places
        try:
            await places.observe(loc.lat, loc.lon, loc.accuracy_m)
        except Exception:  # the trail is a convenience; a chat turn never fails on it
            import logging
            logging.getLogger("jarvis-core").exception("place trail failed")


async def last() -> dict | None:
    row = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'last_location'")
    return row
