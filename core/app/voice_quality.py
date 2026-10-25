"""Measuring and judging the speech complements (Blueprint v4 Fase 3.1 + 3.4, ADR-048). Everything here is pure.

The quality gate, learned the hard way (ADR-016: configured boost words once pulled "Ashar/Opik/Aby" into "UAT"/"Shopee"):
a complement may run live ("on") only when, on the owner's own corrected utterances,
  · the error rate (WER) goes DOWN, and
  · false corrections (it made a correct utterance wrong, or dropped something the owner really said) stay ≤ 1%,
  · with at least MIN_SAMPLES corrected utterances to judge on.
Until then it runs in "shadow": it computes what it WOULD do and that is logged, nothing the owner said is changed.
A complement that is on and stops passing goes back to shadow by itself.
"""

import difflib
import re

MIN_SAMPLES = 20
MAX_FALSE_RATE = 0.01
COMPLEMENTS = {
    "kamus": "Kamus nama & istilah (kontak, perusahaan, merek, koreksimu) memperbaiki kata yang salah dengar",
    "halusinasi": "Frasa halusinasi yang dipelajari (mis. 'terima kasih telah menonton' saat hening) dibuang",
    "gema": "Ucapan yang ternyata suara JARVIS sendiri (gema dari speaker) dibuang",
    "opini_kedua": "Ucapan berkeyakinan rendah juga didengar mesin kedua; yang lebih cocok dipakai",
    "ambang": "Ambang 'mungkin salah dengar' dikalibrasi per mesin dari koreksimu",
}
DROPPERS = {"halusinasi", "gema"}
DEFAULT_MODES = {"kamus": "shadow", "halusinasi": "shadow", "gema": "shadow", "opini_kedua": "off", "ambang": "shadow"}
DEFAULT_THRESHOLD = 0.45
ERROR_KINDS = ("nama", "angka", "istilah", "gema", "halusinasi", "derau", "lainnya")
_NUMBERISH = re.compile(r"\d|\b(nol|satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh|sebelas|belas|puluh|ratus|"
                        r"ribu|juta|miliar|triliun|rupiah|persen|koma)\b", re.I)


def words(text: str) -> list[str]:
    return re.findall(r"[\w']+", (text or "").lower())


def wer(hyp: str, ref: str) -> float:
    """Word error rate of hyp against ref (0 = perfect). An empty ref: 0 if hyp is empty too, else 1. Pure."""
    h, r = words(hyp), words(ref)
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return round(prev[-1] / len(r), 4)


def similar(a: str, b: str) -> float:
    a, b = " ".join(words(a)), " ".join(words(b))
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def is_echo(heard: str, spoken_recently: list[str]) -> bool:
    """The microphone picked up JARVIS's own voice: what was heard is (most of) something it just said. Pure."""
    h = " ".join(words(heard))
    if len(h) < 8:
        return False
    for s in spoken_recently:
        s_norm = " ".join(words(s))
        if not s_norm:
            continue
        if similar(h, s_norm) >= 0.8 or (len(h) >= 14 and h in s_norm):
            return True
    return False


def is_hallucination(heard: str, phrases: list[str]) -> bool:
    """The whole utterance is a learned hallucination phrase (never a phrase inside a real sentence). Pure."""
    h = " ".join(words(heard))
    return bool(h) and any(h == " ".join(words(p)) for p in phrases)


def apply_lexicon(text: str, pairs: dict[str, str]) -> str:
    """Exact misheard → meant replacements the owner taught, whole words, case-insensitive, longest first. Pure."""
    for heard in sorted(pairs, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(heard)}(?!\w)", pairs[heard], text, flags=re.I)
    return text


def apply_reference_fix(raw: str, heard_part: str, meant_part: str) -> str | None:
    """The owner said "bukan X, maksudku Y": the full utterance as meant, or None when X is not in it. Pure."""
    if not heard_part:
        return None
    rx = re.compile(rf"(?<!\w){re.escape(heard_part.strip())}(?!\w)", re.I)
    if not rx.search(raw):
        return None
    return rx.sub(meant_part.strip(), raw, count=1)


def glossary_hits(text: str, glossary: list[str]) -> int:
    low = " " + " ".join(words(text)) + " "
    return sum(1 for g in glossary if g and f" {' '.join(words(g))} " in low)


def choose(primary: dict, second: dict, glossary: list[str]) -> str:
    """'primary' or 'second' for a doubtful utterance. Prefer the one that contains more known names/terms, then the
    one that heard anything at all; when both agree or nothing tells them apart, keep the primary. Pure."""
    p, s = primary.get("text") or "", second.get("text") or ""
    if not s:
        return "primary"
    if not p:
        return "second"
    if similar(p, s) >= 0.95:
        return "primary"
    gp, gs = glossary_hits(p, glossary), glossary_hits(s, glossary)
    if gs != gp:
        return "second" if gs > gp else "primary"
    pc, sc = primary.get("confidence"), second.get("confidence")
    if isinstance(pc, (int, float)) and isinstance(sc, (int, float)) and sc - pc >= 0.15:
        return "second"
    return "primary"


def classify_error(raw: str, ref: str, echo: bool = False, glossary: list[str] | None = None) -> str | None:
    """Taxonomy of one corrected utterance (Fase 3.1): None when it was right. Pure; unit-tested."""
    if wer(raw, ref) == 0:
        return None
    if not words(ref):
        return "gema" if echo else ("halusinasi" if len(words(raw)) <= 6 else "derau")
    rw, fw = words(raw), words(ref)
    sm = difflib.SequenceMatcher(None, rw, fw)
    changed_ref = [w for tag, _, _, j1, j2 in sm.get_opcodes() if tag != "equal" for w in fw[j1:j2]]
    changed_raw = [w for tag, i1, i2, _, _ in sm.get_opcodes() if tag != "equal" for w in rw[i1:i2]]
    if any(_NUMBERISH.search(w) for w in changed_ref + changed_raw):
        return "angka"
    gloss = {w for g in (glossary or []) for w in words(g)}
    # a capital that does not merely start the sentence (or an acronym) marks a name
    ref_caps = {m.group(0) for m in re.finditer(r"\b[A-Z][\w']+", ref) if m.start() > 0 or m.group(0).isupper()}
    if any(w in gloss for w in changed_ref) or any(w.lower() in changed_ref for w in ref_caps):
        return "nama"
    if any(len(w) >= 5 for w in changed_ref):
        return "istilah"
    return "lainnya"


def judge(samples: list[dict], name: str) -> dict:
    """Gate verdict for one complement. samples: [{"raw", "after", "reference"}] where `after` is the complement's
    output on `raw` ("" = dropped). Pure; unit-tested."""
    n = len(samples)
    if n == 0:
        return {"complement": name, "samples": 0, "passes": False, "reason": f"belum ada ucapan yang dikoreksi (butuh {MIN_SAMPLES})"}
    base = sum(wer(s["raw"], s["reference"]) for s in samples) / n
    new = sum(wer(s["after"], s["reference"]) for s in samples) / n
    changed = [s for s in samples if (s["after"] or "") != (s["raw"] or "")]
    false = [s for s in changed if wer(s["after"], s["reference"]) > wer(s["raw"], s["reference"])]
    fixed = [s for s in changed if wer(s["after"], s["reference"]) < wer(s["raw"], s["reference"])]
    false_rate = len(false) / n
    reasons = []
    if n < MIN_SAMPLES:
        reasons.append(f"baru {n} ucapan terkoreksi (butuh {MIN_SAMPLES})")
    if not new < base:
        reasons.append(f"kesalahan tidak turun (WER {base:.3f} → {new:.3f})")
    if false_rate > MAX_FALSE_RATE:
        reasons.append(f"koreksi keliru {false_rate:.1%} (> {MAX_FALSE_RATE:.0%})")
    return {"complement": name, "samples": n, "wer_before": round(base, 4), "wer_after": round(new, 4),
            "changed": len(changed), "fixed": len(fixed), "false_corrections": len(false), "false_rate": round(false_rate, 4),
            "passes": not reasons, "reason": "; ".join(reasons) or "lolos: kesalahan turun, koreksi keliru tidak naik",
            "examples_false": [{"raw": s["raw"][:120], "after": (s["after"] or "")[:120], "reference": s["reference"][:120]}
                               for s in false[:3]]}


def calibrate(points: list[tuple[float, bool]], target_error: float = 0.10, min_points: int = 30) -> float | None:
    """The lowest 'heard well enough' threshold such that utterances at or above it are wrong ≤ target_error of the
    time. points: (confidence, was_wrong). None when there is too little to go on. Pure; unit-tested."""
    pts = [(c, w) for c, w in points if isinstance(c, (int, float))]
    if len(pts) < min_points:
        return None
    for t in [round(0.30 + 0.05 * i, 2) for i in range(11)]:   # 0.30 … 0.80
        above = [w for c, w in pts if c >= t]
        if len(above) >= min_points // 2 and sum(above) / len(above) <= target_error:
            return t
    return 0.80


def next_mode(mode: str, auto: bool, verdict: dict) -> str:
    """shadow → on when the gate passes; on → shadow when it no longer does; 'off' and manual modes stay. Pure."""
    if not auto or mode == "off":
        return mode
    if mode == "shadow" and verdict.get("passes"):
        return "on"
    if mode == "on" and not verdict.get("passes") and verdict.get("samples", 0) >= MIN_SAMPLES:
        return "shadow"
    return mode
