"""Password hashing (scrypt), signed session cookies, and login throttling. Stdlib only."""

import base64
import hashlib
import hmac
import secrets
import time

SESSION_TTL = 12 * 3600
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=_N, r=_R, p=_P).hex()
    return f"scrypt:{salt}:{digest}"  # no '$': compose would try to interpolate it


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split(":")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=_N, r=_R, p=_P).hex()
    return hmac.compare_digest(candidate, digest)


def make_session(secret: str, password_hash: str) -> str:
    # Binding to the hash's salt invalidates all sessions when the password changes.
    payload = f"{int(time.time()) + SESSION_TTL}:{password_hash.split(':')[1]}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def check_session(token: str | None, secret: str, password_hash: str) -> bool:
    if not token:
        return False
    try:
        expires, salt, sig = base64.urlsafe_b64decode(token.encode()).decode().split(":")
    except Exception:
        return False
    expected = hmac.new(secret.encode(), f"{expires}:{salt}".encode(), hashlib.sha256).hexdigest()
    return (
        hmac.compare_digest(sig, expected)
        and int(expires) > time.time()
        and salt == password_hash.split(":")[1]
    )


class Throttle:
    """At most `limit` failed logins per client per `window` seconds."""

    def __init__(self, limit: int = 5, window: int = 900):
        self.limit, self.window = limit, window
        self.failures: dict[str, list[float]] = {}

    def blocked(self, client: str) -> bool:
        now = time.time()
        recent = [t for t in self.failures.get(client, []) if now - t < self.window]
        self.failures[client] = recent
        return len(recent) >= self.limit

    def fail(self, client: str) -> None:
        self.failures.setdefault(client, []).append(time.time())

    def reset(self, client: str) -> None:
        self.failures.pop(client, None)
