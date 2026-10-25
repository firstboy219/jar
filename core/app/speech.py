"""Text made for the ear (Blueprint v4 Fase 3.3): what JARVIS says is normalised HERE, on the server, before it reaches
the phone — whichever voice speaks it (Android's own engine or an OpenRouter/ElevenLabs voice, which reads "Rp 1.500.000"
or "25/10" in English otherwise). The displayed text never changes; only the spoken copy does.

  Rp 1.500.000 → satu juta lima ratus ribu rupiah     85% → delapan puluh lima persen     14:30 → empat belas lewat tiga puluh
  25/10/2026 → dua puluh lima Oktober dua ribu dua puluh enam                              yg/dgn/tdk/dll → yang/dengan/tidak/dan lain-lain
  pronunciations the owner taught ("Renature" → "ri-ne-cer") come first; very long sentences are cut where a comma allows.
Everything here is pure (unit-tested); the learned pronunciations are passed in.
"""

import re

_ONES = ["nol", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan", "sepuluh", "sebelas"]
_SCALES = [(10 ** 12, "triliun"), (10 ** 9, "miliar"), (10 ** 6, "juta"), (1000, "ribu")]
_MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
_SUFFIX = {"rb": 1000, "ribu": 1000, "k": 1000, "jt": 10 ** 6, "juta": 10 ** 6, "m": 10 ** 9, "miliar": 10 ** 9,
           "milyar": 10 ** 9, "t": 10 ** 12, "triliun": 10 ** 12}
ABBREVIATIONS = {"yg": "yang", "dgn": "dengan", "tdk": "tidak", "utk": "untuk", "dll": "dan lain-lain", "dsb": "dan sebagainya",
                 "sdh": "sudah", "blm": "belum", "krn": "karena", "tsb": "tersebut", "jl": "jalan", "kpd": "kepada",
                 "spt": "seperti", "bbrp": "beberapa", "sbg": "sebagai", "pd": "pada", "org": "orang", "trims": "terima kasih",
                 "km/jam": "kilometer per jam", "dst": "dan seterusnya", "a.n.": "atas nama", "u/": "untuk "}
UNITS = {"km": "kilometer", "m": "meter", "cm": "sentimeter", "kg": "kilogram", "gr": "gram", "g": "gram", "ml": "mililiter",
         "l": "liter", "mb": "megabyte", "gb": "gigabyte", "kb": "kilobyte", "ms": "milidetik", "dtk": "detik", "mnt": "menit",
         "jt": "juta", "rb": "ribu"}


def terbilang(n: int) -> str:
    """0 ≤ n < 10^15 in Indonesian words. Pure; unit-tested."""
    if n < 0:
        return "minus " + terbilang(-n)
    if n < 12:
        return _ONES[n]
    if n < 20:
        return _ONES[n - 10] + " belas"
    if n < 100:
        return (_ONES[n // 10] + " puluh" + (" " + _ONES[n % 10] if n % 10 else "")).replace("satu puluh", "sepuluh")
    if n < 1000:
        head = "seratus" if n // 100 == 1 else _ONES[n // 100] + " ratus"
        return head + (" " + terbilang(n % 100) if n % 100 else "")
    for size, word in _SCALES:
        if n >= size:
            q, r = divmod(n, size)
            head = "seribu" if size == 1000 and q == 1 else terbilang(q) + " " + word
            return head + (" " + terbilang(r) if r else "")
    return str(n)


def _digits(s: str) -> str:
    return " ".join(_ONES[int(c)] for c in s)


def number_words(text: str) -> str:
    """'1.500.000' / '3,5' / '0.75' / '2026' / '08123456789' → words. Pure."""
    t = text.strip()
    if re.fullmatch(r"0\d{6,}|\d{9,}", t):                      # phone numbers, codes: digit by digit
        return _digits(t)
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", t):                   # Indonesian thousands
        return terbilang(int(t.replace(".", "")))
    if re.fullmatch(r"\d{1,3}(,\d{3})+", t):                    # English thousands
        return terbilang(int(t.replace(",", "")))
    m = re.fullmatch(r"(\d+)[.,](\d+)", t)
    if m:                                                       # a decimal: "tiga koma lima", "nol koma nol nol empat"
        return terbilang(int(m.group(1))) + " koma " + (_digits(m.group(2)) if m.group(2).startswith("0") or len(m.group(2)) > 2
                                                         else terbilang(int(m.group(2))))
    if re.fullmatch(r"\d+", t):
        return terbilang(int(t)) if len(t) <= 15 else _digits(t)
    if re.fullmatch(r"\d+(\.\d+){2,}", t):                      # versions: 0.14.1
        return " titik ".join(terbilang(int(p)) for p in t.split("."))
    return t


def _amount(num: str, suffix: str | None) -> str:
    words = number_words(num)
    if suffix:
        mult = _SUFFIX.get(suffix.lower().rstrip("."))
        if mult:
            if re.fullmatch(r"\d+", num.replace(".", "").replace(",", "")) and "," not in num and num.count(".") != 1:
                return terbilang(int(num.replace(".", "")) * mult)
            return words + " " + {1000: "ribu", 10 ** 6: "juta", 10 ** 9: "miliar", 10 ** 12: "triliun"}[mult]
    return words


_RP = re.compile(r"\bRp\.?\s?(\d[\d.,]*\d|\d)(?:\s?(rb|ribu|jt|juta|miliar|milyar|M|T|triliun)\b)?", re.I)
_USD = re.compile(r"(?:\$|\bUSD\s?)(\d[\d.,]*\d|\d)(?:\s?(rb|ribu|jt|juta|k)\b)?", re.I)
_PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s?%")
_DATE_DMY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_TIME = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b(?!:)|(?<=pukul )([01]?\d|2[0-3])\.([0-5]\d)\b|(?<=jam )([01]?\d|2[0-3])\.([0-5]\d)\b", re.I)
_UNIT = re.compile(r"\b(\d+(?:[.,]\d+)?)\s?(" + "|".join(sorted(UNITS, key=len, reverse=True)) + r")\b(?!/)", re.I)
_NUM = re.compile(r"(?<![\w.,])(\d[\d.,]*\d|\d)(?![\w])")
_URL = re.compile(r"https?://\S+|www\.\S+")
_MD = [(re.compile(r"```.*?```", re.S), " (kode) "), (re.compile(r"`([^`]*)`"), r"\1"), (re.compile(r"\*\*|__|[*_#>]"), ""),
       (re.compile(r"^\s*[-•]\s+", re.M), ""), (re.compile(r"\[([^]]+)]\([^)]+\)"), r"\1")]


def _date(d: int, m: int, y: int) -> str:
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return f"{d}/{m}/{y}"
    return f"{terbilang(d)} {_MONTHS[m - 1]} {terbilang(y)}"


def _time(m: re.Match) -> str:
    h, mi = (int(g) for g in [g for g in m.groups() if g is not None][:2])
    return terbilang(h) + (f" lewat {terbilang(mi)}" if mi else "")


def respell(text: str, pronounce: dict[str, str]) -> str:
    """The owner's pronunciations, whole words, case-insensitive, longest first. Pure."""
    for word in sorted(pronounce, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", pronounce[word], text, flags=re.I)
    return text


def cut_long(text: str, limit: int = 180) -> str:
    """Very long sentences get a full stop at a comma near the middle, so the voice breathes. Pure."""
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        while len(sentence) > limit and (cut := sentence.rfind(", ", 40, limit)) > 0:
            out.append(sentence[:cut] + ".")
            sentence = sentence[cut + 2:]
        out.append(sentence)
    return " ".join(out)


def normalize(text: str, pronounce: dict[str, str] | None = None) -> str:
    """The spoken copy of `text`. Pure; unit-tested."""
    if not text:
        return text
    for rx, rep in _MD:
        text = rx.sub(rep, text)
    text = _URL.sub("tautan", text)
    if pronounce:
        text = respell(text, pronounce)
    text = _RP.sub(lambda m: _amount(m.group(1), m.group(2)) + " rupiah", text)
    text = _USD.sub(lambda m: _amount(m.group(1), m.group(2)) + " dolar", text)
    text = _PCT.sub(lambda m: number_words(m.group(1)) + " persen", text)
    text = _DATE_ISO.sub(lambda m: _date(int(m.group(3)), int(m.group(2)), int(m.group(1))), text)
    text = _DATE_DMY.sub(lambda m: _date(int(m.group(1)), int(m.group(2)), int(m.group(3))), text)
    text = _TIME.sub(_time, text)
    text = _UNIT.sub(lambda m: number_words(m.group(1)) + " " + UNITS[m.group(2).lower()], text)
    for short, long in sorted(ABBREVIATIONS.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<!\w){re.escape(short)}(?!\w)" if short[-1].isalnum() else rf"(?<!\w){re.escape(short)}",
                      long, text, flags=re.I)
    text = _NUM.sub(lambda m: number_words(m.group(1)), text)
    text = re.sub(r"\s+", " ", text).strip()
    return cut_long(text)
