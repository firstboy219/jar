"""Detect content that must not leave the server (sent to a cloud model or stored in memory)."""

import re

PRIVATE_PREFIXES = ("/privat", "#privat", "/private")

_PATTERNS = {
    "API key": re.compile(r"\b(sk-(?:or-|proj-|ant-)?[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,})\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "password": re.compile(r"\b(password|passwd|pwd|kata ?sandi|sandi|pin)\s*[:=]\s*\S+", re.IGNORECASE),
    "token/secret": re.compile(r"\b(token|secret|api[_ -]?key)\s*[:=]\s*[A-Za-z0-9._~+/-]{12,}", re.IGNORECASE),
}
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def scan(text: str) -> list[str]:
    """Return the kinds of sensitive data found (empty list = clean)."""
    found = [name for name, rx in _PATTERNS.items() if rx.search(text)]
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append("nomor kartu")
            break
    return found


def is_private(text: str) -> bool:
    return text.lstrip().lower().startswith(PRIVATE_PREFIXES)
