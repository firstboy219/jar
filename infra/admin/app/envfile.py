"""Read and update a docker-compose style .env file in place.

The file is bind-mounted from the host, so it is rewritten in place (same inode)
instead of replaced; a rename would detach the mount.
"""

import re
import threading
from pathlib import Path

_lock = threading.Lock()
# Values end up in docker compose interpolation and container env: keep them boring.
SAFE_VALUE = re.compile(r"^[A-Za-z0-9._@:/+=,-]*$")


class EnvFile:
    def __init__(self, path: str):
        self.path = Path(path)

    def read(self) -> dict[str, str]:
        values = {}
        for line in self.path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
        return values

    def update(self, changes: dict[str, str]) -> None:
        for key, value in changes.items():
            if not SAFE_VALUE.match(value):
                raise ValueError(f"{key}: karakter tidak diizinkan")
        with _lock:
            lines = self.path.read_text().splitlines()
            pending = dict(changes)
            for i, line in enumerate(lines):
                key = line.partition("=")[0].strip()
                if "=" in line and not line.lstrip().startswith("#") and key in pending:
                    lines[i] = f"{key}={pending.pop(key)}"
            lines += [f"{k}={v}" for k, v in pending.items()]
            with self.path.open("r+") as f:
                f.seek(0)
                f.write("\n".join(lines) + "\n")
                f.truncate()
