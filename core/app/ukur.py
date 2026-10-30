"""Ukur (ADR-087, mockup 7): measuring with the camera. Near things (a table, a door, a room) the phone measures itself with AR — tap two
points, read the distance — and sends the result here to keep. Far things (a house across the street) are estimated from a photo by the
brain's eyes, from objects of known size in the picture (a door ≈ 2 m, a car ≈ 4.5 m, a storey ≈ 3 m), always as a range with how sure.

The photo estimate is a master-flow job with vision (category 'penglihatan')."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import attachments, db, master
from .appauth import owner

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/measure"


class MeasureError(ValueError):
    pass


def clean_estimate(d: dict) -> dict:
    """The eyes' answer kept to numbers in metres with a range. Pure."""
    def num(v):
        try:
            x = float(str(v).replace(",", "."))
            return round(x, 2) if 0 < x < 10_000 else None
        except (TypeError, ValueError):
            return None
    out = {}
    for k in ("lebar", "tinggi", "panjang", "jarak"):
        v = (d or {}).get(k)
        if isinstance(v, dict):
            lo, hi, mid = num(v.get("min")), num(v.get("max")), num(v.get("perkiraan"))
            if mid or (lo and hi):
                out[k] = {"perkiraan": mid or round((lo + hi) / 2, 2), "min": lo or mid, "max": hi or mid}
        elif num(v):
            out[k] = {"perkiraan": num(v), "min": num(v), "max": num(v)}
    yakin = str((d or {}).get("yakin") or "rendah").lower()
    return {"ukuran": out, "acuan": [str(x)[:100] for x in (d or {}).get("acuan") or []][:5], "yakin": yakin if yakin in ("rendah", "sedang", "tinggi") else "rendah",
            "catatan": str((d or {}).get("catatan") or "")[:300], "objek": str((d or {}).get("objek") or "")[:80]}


async def from_photo(attachment_id: str, target: str, reference: str = "") -> dict:
    m = attachments.meta(attachment_id)
    if not m or m["kind"] != "image":
        raise MeasureError("kirim foto (gambar) dulu")
    b64 = attachments.image_b64(attachment_id, 1600)
    msgs = [{"role": "system", "content": (
        "Kamu mata JARVIS yang memperkirakan UKURAN benda di foto dalam meter, memakai benda acuan yang ukurannya umum diketahui (pintu ≈ 2,0–2,1 m tinggi, "
        "orang dewasa ≈ 1,6–1,75 m, mobil ≈ 4,3–4,7 m panjang, motor ≈ 1,9 m, lantai rumah ≈ 3 m, bata ≈ 20 cm, ubin 40/60 cm). Beri RENTANG yang jujur "
        "dan seberapa yakin; jangan pura-pura presisi. JSON: {\"objek\": \"…\", \"lebar\": {\"perkiraan\": 0, \"min\": 0, \"max\": 0}, \"tinggi\": {…}, "
        "\"panjang\": {…} (bila terlihat), \"acuan\": [\"benda yang dipakai sebagai acuan\"], \"yakin\": \"rendah|sedang|tinggi\", \"catatan\": \"…\"}")},
        {"role": "user", "content": [{"type": "text", "text": f"Ukur: {target or 'benda utama di foto'}." + (f" Acuan dari pemilik: {reference}." if reference else "")},
                                     {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]
    r = await master.run(master.Job("kamera", "ukur-foto", f"perkirakan ukuran {target or 'benda'} dari foto", messages=msgs, json_out=True, vision=True,
                                    no_free=True, max_tokens=700))
    if r["status"] != "done" or not isinstance(r["result"], dict):
        raise MeasureError(r.get("error") or "foto tidak bisa diukur (model penglihatan tidak tersedia?)")
    d = clean_estimate(r["result"])
    if not d["ukuran"]:
        raise MeasureError("ukurannya tidak bisa diperkirakan dari foto ini — coba foto yang ada pintu/orang/mobil di dekatnya")
    mid = await db.pool().fetchval("INSERT INTO measures (label, kind, data, attachment_id, run_id) VALUES ($1, 'foto', $2, $3, $4) RETURNING id",
                                   (target or d["objek"])[:80], d, attachment_id, r["run_id"])
    return {"id": mid, "kind": "foto", "label": target or d["objek"], **d, "lane": r.get("lane")}


class ArIn(BaseModel):
    label: str = Field(default="", max_length=80)
    segments: list[float] = Field(min_length=1, max_length=20)   # metres between consecutive taps
    area_m2: float | None = Field(default=None, ge=0, le=100000)
    height_m: float | None = Field(default=None, ge=0, le=1000)


class PhotoIn(BaseModel):
    attachment_id: str = Field(min_length=8, max_length=64)
    target: str = Field(default="", max_length=120)
    reference: str = Field(default="", max_length=200)


@router.get(API)
async def api_list(device: dict = Depends(owner)):
    rows = await db.pool().fetch("SELECT id, label, kind, data, created_at FROM measures ORDER BY id DESC LIMIT 30")
    return {"measures": [dict(r) for r in rows]}


@router.post(API + "/ar")
async def api_ar(body: ArIn, device: dict = Depends(owner)):
    """What the phone's AR ruler measured (the native camera screen sends it)."""
    if any(s <= 0 or s > 200 for s in body.segments):
        raise HTTPException(422, "ukuran tidak masuk akal")
    data = {"segmen": [round(s, 3) for s in body.segments], "total": round(sum(body.segments), 3), "luas": body.area_m2, "tinggi": body.height_m, "unit": "m"}
    async def keep():
        return await db.pool().fetchval("INSERT INTO measures (label, kind, data) VALUES ($1, 'ar', $2) RETURNING id", body.label or "Ukuran AR", data)
    r = await master.run(master.Job("kamera", "ukur-ar", "simpan ukuran AR dari HP", skill=keep))
    return {"id": r.get("result"), **data}


@router.post(API + "/photo")
async def api_photo(body: PhotoIn, device: dict = Depends(owner)):
    try:
        return await from_photo(body.attachment_id, body.target, body.reference)
    except (MeasureError, attachments.AttachmentError) as e:
        raise HTTPException(409, str(e))


@router.delete(API + "/{measure_id}")
async def api_delete(measure_id: int, device: dict = Depends(owner)):
    await db.pool().execute("DELETE FROM measures WHERE id = $1", measure_id)
    return {"ok": True}
