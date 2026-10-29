"""Routines (ADR-083): Hermes remembers HOW a task on the owner's phone was done and replays it without AI next time.

After a phone task succeeded with the AI deciding every tap, one model call turns what happened (the trace) into a ROUTINE — a small program:

  open                                   open the app
  tap   {match}                          tap the element that matches (text / description / hint / class / resource id; may use {params})
  type  {match, text, submit}            type a text ("{tujuan}") into a field
  wait  {match, timeout}                 wait until an element shows up (a screen that loads)
  scroll {arah}  /  back                 scroll, the Back button
  read  {match, regex, into}             read a value from the screen into a variable (e.g. the pickup time in minutes)
  if    {var, cmp, value, then, else}    jump to a label by a rule the owner gave (pickup ≤ 5 minutes → chat, else cancel and order again)
  goto  {to, max}                        jump back (re-order), at most `max` times
  ai    {goal, max_steps}                a step that needs judgement: the AI does only this part (pick the right place, chat with the driver)
  ask   {question, into}                 ask the owner
  done  {result}                         finished; the result text may use variables

…and lists the owner's needs it learned (pickup at home, the cheaper option, at most 5 minutes) — they become preference memories too.
Next time the request matches a routine by meaning, one small call fills its parameters from the request, the program runs, and AI is spent
only on the `ai` steps. When a step cannot be done (the app changed, an element is missing) the AI takes over from that screen, and what it
did becomes the routine's next version. Three failures in a row switch a routine off. The phone's guards (no PIN/OTP, only the approved app,
no top-ups …) apply to every replayed step exactly as to the AI's.
"""

import json
import logging
import re

from . import db, llm, memory

log = logging.getLogger("jarvis-core.routines")
OPS = {"open", "tap", "type", "wait", "scroll", "back", "read", "if", "goto", "ai", "ask", "done"}
MATCH_KEYS = {"id", "t", "t_has", "d", "d_has", "h", "c", "e", "k"}
MAX_STEPS, MAX_RUN = 80, 160
MIN_SIMILARITY = 0.6     # of the request to a routine's PATTERN (its particulars — the destination — would dominate the request itself)
FAIL_LIMIT = 3
_VAR = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class RoutineError(ValueError):
    pass


# ---------- pure parts (unit-tested) ----------

def fill(text: str, values: dict) -> str:
    """'{tujuan}' → the value; unknown names stay as they are."""
    return _VAR.sub(lambda m: str(values[m[1]]) if m[1] in values else m[0], str(text or ""))


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def find_node(obs: dict, match: dict, values: dict | None = None) -> dict | None:
    """The first element on the screen that fits every key of `match` (pure). Text keys compare without case and spacing; *_has = contains."""
    m = {k: (fill(v, values or {}) if isinstance(v, str) else v) for k, v in (match or {}).items() if k in MATCH_KEYS}
    if not m:
        return None
    for n in obs.get("nodes") or []:
        ok = True
        for k, v in m.items():
            if k == "id":
                ok = n.get("id") == v
            elif k in ("t", "d"):
                ok = _norm(n.get(k)) == _norm(v)
            elif k in ("t_has", "d_has"):
                ok = _norm(v) in _norm(n.get(k[0]))
            elif k == "h":
                ok = _norm(v) in _norm(n.get("h"))
            elif k == "c":
                ok = (n.get("c") or "") == v
            elif k in ("e", "k"):
                ok = bool(n.get(k)) == bool(v)
            if not ok:
                break
        if ok:
            return n
    return None


def squash(text: str) -> str:
    """'Go-Ride ke Ancol' → 'goridekeancol': what keywords are looked for in (pure)."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def keys_match(keys: list, goal: str) -> bool:
    """Every keyword of a routine is in the request (pure; unit-tested). No keywords: never matches by keywords."""
    g = squash(goal)
    ks = [squash(k) for k in keys or [] if squash(k)]
    return bool(ks) and all(k in g for k in ks)


def screen_words(obs: dict) -> str:
    """All text on the screen, for a `read` without a match."""
    return " · ".join(str(n.get(k)) for n in obs.get("nodes") or [] for k in ("t", "d") if n.get(k))


def compare(a, cmp: str, b) -> bool:
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        x, y = _norm(a), _norm(b)
    return {"<=": x <= y, "<": x < y, ">=": x >= y, ">": x > y, "==": x == y, "!=": x != y}.get(cmp, False)


def validate(steps: list, params: dict) -> list[str]:
    """What is wrong with a program (pure; unit-tested). [] = it may be saved and run."""
    problems = []
    if not isinstance(steps, list) or not steps:
        return ["program kosong"]
    if len(steps) > MAX_STEPS:
        problems.append(f"lebih dari {MAX_STEPS} langkah")
    labels = [s.get("label") for s in steps if isinstance(s, dict) and s.get("label")]
    if len(labels) != len(set(labels)):
        problems.append("label ganda")
    for i, s in enumerate(steps):
        if not isinstance(s, dict) or s.get("op") not in OPS:
            problems.append(f"langkah {i + 1}: op tidak dikenal")
            continue
        op = s["op"]
        if op in ("tap", "type", "wait") and not (isinstance(s.get("match"), dict) and set(s["match"]) & MATCH_KEYS):
            problems.append(f"langkah {i + 1}: {op} tanpa elemen yang dicari")
        if op == "type" and not str(s.get("text") or "").strip():
            problems.append(f"langkah {i + 1}: type tanpa teks")
        if op == "read" and not (s.get("into") and s.get("regex")):
            problems.append(f"langkah {i + 1}: read butuh regex dan into")
        if op == "read":
            try:
                re.compile(s.get("regex") or "")
            except re.error:
                problems.append(f"langkah {i + 1}: regex rusak")
        if op == "if" and (s.get("cmp") not in ("<=", "<", ">=", ">", "==", "!=") or not s.get("var")):
            problems.append(f"langkah {i + 1}: if butuh var dan cmp")
        for key in ("then", "else", "to"):
            if s.get(key) and s[key] not in labels:
                problems.append(f"langkah {i + 1}: label {s[key]} tidak ada")
        if op == "goto" and not s.get("to"):
            problems.append(f"langkah {i + 1}: goto tanpa tujuan")
        if op == "ai" and not str(s.get("goal") or "").strip():
            problems.append(f"langkah {i + 1}: ai tanpa tujuan")
        for v in _VAR.findall(json.dumps(s, ensure_ascii=False)):
            if v not in params and not any(x.get("into") == v for x in steps if isinstance(x, dict)):
                problems.append(f"langkah {i + 1}: variabel {{{v}}} tidak dikenal")
                break
    if not any(isinstance(s, dict) and s.get("op") == "done" for s in steps):
        problems.append("tidak ada langkah done")
    return problems[:10]


async def execute(steps: list, values: dict, io) -> dict:
    """Run a routine. `io`: observe(), act(op, **args) → screen (refuses what the guards refuse), ai(goal, max_steps) → text, ask(q) → text,
    emit(event). Returns {ok, result | why, at, auto, ai}. Pure apart from io (unit-tested with a fake phone)."""
    v = dict(values)
    labels = {s["label"]: i for i, s in enumerate(steps) if s.get("label")}
    jumps: dict[str, int] = {}
    pc, ran, auto, ai = 0, 0, 0, 0
    obs = await io.observe()

    def fail(why: str) -> dict:
        return {"ok": False, "why": why, "at": pc + 1, "auto": auto, "ai": ai, "values": v}

    while pc < len(steps):
        ran += 1
        if ran > MAX_RUN:
            return fail("rutin berputar terlalu lama")
        s = steps[pc]
        op = s["op"]
        label = s.get("say") or op
        try:
            if op in ("tap", "type"):
                n = find_node(obs, s["match"], v)
                if not n:
                    return fail(f"tidak menemukan {json.dumps(s['match'], ensure_ascii=False)} di layar")
                await io.emit({"type": "tool", "id": f"r{pc}", "name": f"rutin_{op}", "label": label, "status": "running"})
                obs = await (io.act("tap", index=n["i"]) if op == "tap" else
                             io.act("type", index=n["i"], text=fill(s["text"], v), submit=bool(s.get("submit"))))
                auto += 1
            elif op == "wait":
                for _ in range(int(s.get("timeout") or 10)):
                    if find_node(obs, s["match"], v):
                        break
                    obs = await io.observe(1.0)
                else:
                    return fail(f"tidak muncul: {json.dumps(s['match'], ensure_ascii=False)}")
                auto += 1
            elif op in ("open", "back", "scroll"):
                obs = await io.act(op, direction=s.get("arah") or "bawah")
                auto += 1
            elif op == "read":
                n = find_node(obs, s["match"], v) if s.get("match") else None
                text = " · ".join(str(n.get(k)) for k in ("t", "d") if n and n.get(k)) if n else screen_words(obs)
                m = re.search(s["regex"], text or "", re.IGNORECASE)
                if not m:
                    return fail(f"tidak bisa membaca {s['into']} dari layar")
                got = m.group(1) if m.groups() else m.group(0)
                v[s["into"]] = float(got.replace(",", ".")) if re.fullmatch(r"\d+(?:[.,]\d+)?", got) else got
                auto += 1
            elif op == "if":
                yes = compare(v.get(s["var"]), s["cmp"], s.get("value"))
                target = s.get("then") if yes else s.get("else")
                auto += 1
                if target:
                    pc = labels[target]
                    continue
            elif op == "goto":
                jumps[s["to"]] = jumps.get(s["to"], 0) + 1
                if jumps[s["to"]] > int(s.get("max") or 2):
                    return fail(f"sudah diulang {jumps[s['to']] - 1} kali")
                pc = labels[s["to"]]
                continue
            elif op == "ai":
                await io.emit({"type": "thought", "text": f"langkah yang butuh pertimbangan: {fill(s['goal'], v)[:120]}"})
                out = await io.ai(fill(s["goal"], v), int(s.get("max_steps") or 8))
                ai += 1
                if s.get("into"):
                    v[s["into"]] = out
                obs = await io.observe()
            elif op == "ask":
                v[s.get("into") or "jawaban"] = await io.ask(fill(s["question"], v))
                obs = await io.observe()
            elif op == "done":
                return {"ok": True, "result": fill(s.get("result") or "Selesai.", v), "auto": auto, "ai": ai, "values": v}
        except Exception as e:   # a guard refused, the phone refused, the AI step gave up: the AI takes over from here
            return fail(f"{type(e).__name__}: {e}"[:300])
        pc += 1
    return fail("rutin berakhir tanpa done")


COMPILE = """Kamu menyusun RUTIN dari cara JARVIS baru saja menyelesaikan tugas di aplikasi {label}, supaya lain kali bisa diulang TANPA AI.
Balas HANYA JSON: {{"nama": "...", "pola": "...", "kata_kunci": ["..."], "params": {{"nama_param": "artinya"}}, "steps": [...], "kebutuhan": ["..."]}}.
"pola" = permintaannya tanpa hal yang berubah-ubah, memakai param (mis. "Pesan GoRide dari {{asal}} ke {{tujuan}}").
"kata_kunci" = 1–3 kata yang PASTI ada di setiap permintaan sejenis (mis. ["goride"]) — bukan alamat atau nama.
Langkah (op): open; tap {{match}}; type {{match, text, submit}}; wait {{match, timeout}}; scroll {{arah}}; back;
read {{match?, regex, into}}; if {{var, cmp, value, then, else}}; goto {{to, max}}; ai {{goal, max_steps}}; ask {{question, into}}; done {{result}}.
Setiap langkah boleh punya "label" (tujuan lompatan) dan "say" (teks singkat untuk pemilik).
match memakai kunci: id (resource id), t (teks persis), t_has (teks mengandung), d / d_has (deskripsi), h (petunjuk), c (kelas), e/k (true).
Aturan:
- Langkah yang selalu sama (buka menu, tombol tetap) → tap/wait biasa. Teks yang berasal dari permintaan (alamat, menu, catatan) → param
  "{{nama_param}}", jangan ditulis mati.
- Yang butuh pertimbangan (memilih hasil pencarian yang paling cocok, mengobrol dengan driver/penjual, menilai sesuatu yang tidak bisa dibaca
  sebagai angka) → op ai dengan goal yang jelas dan max_steps kecil.
- Aturan pemilik yang berupa angka (mis. jemput ≤ 5 menit) → read angka dari layar lalu if; ulangi dengan goto (max 2) bila aturannya begitu.
- Jangan pernah mengetik PIN/OTP/kata sandi; jangan menekan isi saldo/transfer.
- "kebutuhan": hal yang pemilik inginkan dan berlaku lagi lain kali (lokasi jemput biasa, opsi harga, batas waktu) — kalimat pendek.
- Akhiri dengan done yang menulis hasil untuk pemilik (boleh memakai variabel)."""


def parse_program(raw: str) -> dict:
    """The model's JSON (possibly fenced) → {nama, params, steps, kebutuhan} (pure; unit-tested)."""
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not m:
        raise RoutineError("bukan JSON")
    try:
        data = json.loads(m.group(0))
    except ValueError as e:
        raise RoutineError(f"JSON rusak: {e}") from e
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    out = {"nama": str(data.get("nama") or "rutin")[:80], "pola": str(data.get("pola") or data.get("nama") or "")[:300],
           "kata_kunci": [str(k)[:30] for k in (data.get("kata_kunci") or []) if squash(k)][:3], "params": {str(k)[:30]: str(v)[:120] for k, v in params.items() if re.fullmatch(r"[a-z_][a-z0-9_]*", str(k))},
           "steps": data.get("steps") if isinstance(data.get("steps"), list) else [],
           "kebutuhan": [str(x)[:200] for x in (data.get("kebutuhan") or []) if str(x).strip()][:8]}
    problems = validate(out["steps"], out["params"])
    if problems:
        raise RoutineError("; ".join(problems))
    return out


# ---------- the store ----------

async def find(app: str, goal: str) -> dict | None:
    """The active routine of this app for `goal`: first by its keywords (all in the request; the most proven wins), else by meaning of its pattern."""
    rows = [dict(r) for r in await db.pool().fetch("SELECT * FROM routines WHERE app = $1 AND status = 'active' ORDER BY ok_runs DESC, updated_at DESC", app)]
    if not rows:
        return None
    by_keys = [r for r in rows if keys_match(r["keys"], goal)]
    if by_keys:
        return max(by_keys, key=lambda r: (len(r["keys"] or []), r["ok_runs"]))
    rows = [r for r in rows if r["embedding"] is not None]
    if not rows:
        return None
    [qv] = await memory.embed([goal])
    best, r = max(((memory.cosine(qv, list(r["embedding"])), r) for r in rows), key=lambda x: x[0])
    return r if best >= MIN_SIMILARITY else None


async def params_for(routine: dict, goal: str) -> dict:
    """Fill the routine's parameters from the new request (+ what JARVIS remembers of the owner) — one small call; none when it has none."""
    params = routine["params"] or {}
    if not params:
        return {}
    try:
        hints = [m["text"] for m in await memory.search(goal, limit=4) if m["score"] >= 0.35]
    except Exception:
        hints = []
    raw = await llm.complete([
        {"role": "system", "content": "Isi parameter dari permintaan pemilik. Balas HANYA JSON {nama_param: nilai}. Pakai yang pemilik ingat bila "
                                      "permintaannya tidak menyebut (mis. 'rumah'). Nilai yang tidak diketahui: string kosong."},
        {"role": "user", "content": f"PERMINTAAN: {goal}\nPARAMETER: {json.dumps(params, ensure_ascii=False)}\nYANG DIINGAT: {json.dumps(hints, ensure_ascii=False)}"}],
        category="ringan", max_tokens=200, caller="core", temperature=0)
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    try:
        got = json.loads(m.group(0)) if m else {}
    except ValueError:
        got = {}
    return {k: str(got.get(k) or "") for k in params}


async def learn(app: str, label: str, goal: str, trace: list[dict], result: str, task_id: int | None, replaces: dict | None = None) -> dict | None:
    """Turn a successful AI run into a routine (or the next version of the one that broke). Best effort: a failure here never touches the task."""
    if len(trace) < 2:
        return None
    try:
        raw = await llm.complete([
            {"role": "system", "content": COMPILE.format(label=label)},
            {"role": "user", "content": f"PERMINTAAN PEMILIK: {goal}\n\nYANG DILAKUKAN (urut):\n{json.dumps(trace[-60:], ensure_ascii=False)[:14000]}\n\nHASIL: {result[:800]}"}],
            category="hp", max_tokens=2500, caller="core", temperature=0)
        prog = parse_program(raw)
    except Exception as e:
        log.warning("routine for %s not learned: %s", app, e)
        return None
    pattern = prog["pola"] or goal
    [vec] = await memory.embed([_VAR.sub(" ", pattern)])
    if replaces:
        row = await db.pool().fetchrow(
            """UPDATE routines SET name = $2, params = $3::jsonb, steps = $4::jsonb, needs = $5::jsonb, version = version + 1, status = 'active',
                      fail_streak = 0, source_task = $6, pattern = $7, keys = $8::jsonb, embedding = $9, updated_at = now() WHERE id = $1 RETURNING *""",
            replaces["id"], prog["nama"], prog["params"], prog["steps"], prog["kebutuhan"], task_id,
            pattern, prog["kata_kunci"], vec)
    else:
        row = await db.pool().fetchrow(
            """INSERT INTO routines (app, name, intent, pattern, keys, embedding, params, steps, needs, source_task)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8::jsonb, $9::jsonb, $10) RETURNING *""",
            app, prog["nama"], goal[:1000], pattern, prog["kata_kunci"], vec, prog["params"],
            prog["steps"], prog["kebutuhan"], task_id)
    for need in prog["kebutuhan"]:   # what the owner wants becomes a preference memory too (duplicates merge there)
        try:
            await memory.save(need, "personal", f"rutin:{row['id']}", kind="preference")
        except Exception:
            pass
    return dict(row)


async def record(routine_id: int, ok: bool, auto: int, ai: int) -> None:
    await db.pool().execute(
        """UPDATE routines SET runs = runs + 1, ok_runs = ok_runs + CASE WHEN $2 THEN 1 ELSE 0 END, auto_steps = auto_steps + $3, ai_steps = ai_steps + $4,
                  fail_streak = CASE WHEN $2 THEN 0 ELSE fail_streak + 1 END,
                  status = CASE WHEN NOT $2 AND fail_streak + 1 >= $5 THEN 'off' ELSE status END, updated_at = now() WHERE id = $1""",
        routine_id, ok, auto, ai, FAIL_LIMIT)


async def listing() -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT id, app, name, intent, pattern, keys, params, needs, version, status, runs, ok_runs, auto_steps, ai_steps, jsonb_array_length(steps) AS steps, updated_at FROM routines ORDER BY updated_at DESC")
    return [dict(r) for r in rows]


async def set_status(routine_id: int, status: str) -> bool:
    if status not in ("active", "off"):
        raise RoutineError("status: active atau off")
    return (await db.pool().execute("UPDATE routines SET status = $2, fail_streak = 0, updated_at = now() WHERE id = $1", routine_id, status)).endswith("1")


async def delete(routine_id: int) -> bool:
    return (await db.pool().execute("DELETE FROM routines WHERE id = $1", routine_id)).endswith("1")
