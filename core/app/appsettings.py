"""What each feature of the app keeps as the owner's settings (ADR-087): one JSON per feature in settings_kv ('app:<key>'), always
returned complete (defaults filled in) so a screen never has to guess. Only known fields are kept; their types are checked here."""

import copy

from . import audit, db


class SettingError(ValueError):
    pass


DEFAULTS: dict[str, dict] = {
    "ibadah": {"city_id": "", "city": "", "reminders": {"subuh": "adzan", "dzuhur": "notif", "ashar": "notif", "maghrib": "notif", "isya": "adzan"},
               "before_min": 0, "sahur_reminder": True, "sahur_time": "03:30", "bekam_reminder": True, "quiet_in_meeting": True},
    "alarm": {"enabled": True, "time": "04:00", "days": [0, 1, 2, 3, 4, 5, 6], "snooze_min": 5, "escalate_after_min": 5, "voice_greeting": True},
    "money": {"payday": 25, "salary": 0, "pots": [], "alert_pct": 80, "goals": "", "savings_pct": 20},
    "coffee": {"enabled": True, "apps": ["kopikenangan", "qpon"], "usual": "", "max_price": 75000, "pickup": True, "outlet": "", "sugar": "less sugar"},
    "invest": {"app": "pluang", "limit": 2000000, "price_guard_pct": 1.0, "targets": {}, "check_day": "monday", "check_at": "08:00", "risk": "sedang",
               "goal": "", "password": True},
    "commute": {"home_station": "", "office_station": "", "walk_min": 6, "arrive_before": "09:00", "leave_after": "17:00",
                "ride_app": "gojek", "ride_to_station": True, "ride_from_station": True},
    "brief": {"enabled": True, "time": "05:45", "topics": [], "speak": False},
    "story": {"child_name": "", "child_age": 5, "themes": ["hewan", "petualangan", "persahabatan"], "length_min": 5, "time": "20:00"},
    "jobs": {"roles": [], "min_salary": 0, "locations": [], "remote_ok": True, "auto_apply": False, "auto_reply_invites": True,
             "undo_min": 5, "min_match": 80, "cv_doc_id": "", "times": ["07:00", "19:00"]},
    "music": {"moods": {"fokus": "lofi fokus kerja", "semangat": "lagu semangat pagi", "olahraga": "musik olahraga energik",
                        "santai": "lagu santai akustik", "tidur": "musik tidur tenang"}},
    "home": {"hidden": []},
    "cinema": {"city": "", "cinemas": [], "max": 4},
    "bisnis": {"businesses": ["Autotoko", "Renature"], "alerts": True, "behind_pct": 60, "unpacked_after": "14:00",
               "profile": "Pemilik Autotoko (SaaS omnichannel marketplace untuk penjual online) dan Renature (jualan online inhaler, mouth spray, produk herbal); "
                          "juga karyawan kantor di Jakarta, tinggal di Bogor.",
               "strategy_day": 0, "strategy_at": "07:30", "opportunity_day": 5, "opportunity_at": "09:00"},
    "quran": {"qari": "05", "target_date": "", "translation": True,
              "routines": [{"surah": 67, "time": "20:30", "days": [0, 1, 2, 3, 4, 5, 6]}, {"surah": 18, "time": "07:00", "days": [4]}]},
}


def merge(defaults: dict, given: dict) -> dict:
    """Defaults with the given values laid over them — only keys the defaults know, each of the same type (ints may stand for floats)."""
    out = copy.deepcopy(defaults)
    for k, v in (given or {}).items():
        if k not in defaults:
            continue
        d = defaults[k]
        if isinstance(d, bool):
            if not isinstance(v, bool):
                raise SettingError(f"{k}: harus ya/tidak")
            out[k] = v
        elif isinstance(d, (int, float)) and not isinstance(d, bool):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise SettingError(f"{k}: harus angka")
            out[k] = v
        elif isinstance(d, str):
            if not isinstance(v, str):
                raise SettingError(f"{k}: harus teks")
            out[k] = v[:500]
        elif isinstance(d, list):
            if not isinstance(v, list):
                raise SettingError(f"{k}: harus daftar")
            out[k] = v[:50]
        elif isinstance(d, dict):
            if not isinstance(v, dict):
                raise SettingError(f"{k}: harus objek")
            out[k] = {**d, **{kk: vv for kk, vv in v.items()}} if d else dict(list(v.items())[:50])
    return out


async def get(key: str) -> dict:
    if key not in DEFAULTS:
        raise SettingError(f"pengaturan tidak dikenal: {key}")
    stored = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", f"app:{key}") or {}
    try:
        return merge(DEFAULTS[key], stored)
    except SettingError:   # something stored long ago no longer fits: the defaults
        return copy.deepcopy(DEFAULTS[key])


async def put(key: str, values: dict, actor: str) -> dict:
    current = await get(key)
    new = merge(DEFAULTS[key], {**current, **(values or {})})
    await db.pool().execute(
        """INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        f"app:{key}", new)
    await audit.record(actor, "app.settings", f"settings:{key}", keys=sorted((values or {}).keys()))
    return new
