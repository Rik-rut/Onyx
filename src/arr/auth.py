"""Web UI credentials: a single account stored in ``auth.toml`` next to the config.

The password is never stored in plain text: it is kept as a salted
PBKDF2-HMAC-SHA256 hash (``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``)
and verified with a constant-time compare. The file is seeded lazily on first
access (so test clients that skip lifespan still work) and at startup (so the
default-credentials warning can fire).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "1234"
PBKDF2_ITERATIONS = 210_000


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _compute_hash(stored: str, password: str) -> str:
    """Recompute a hash using the salt/iterations recorded in ``stored``."""
    parts = stored.split("$")
    if len(parts) != 4:
        return "$$$"
    try:
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
    except (ValueError, TypeError):
        return "$$$"
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class AuthStore:
    """Reads/writes ``auth.toml``; exactly one account, no complexity rules."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.username = DEFAULT_USERNAME
        self.password_hash = _hash_password(DEFAULT_PASSWORD)
        self.must_change_credentials = True
        self.created_at: float | None = None
        self._loaded = False

    def ensure_loaded(self) -> None:
        """Read the file on first access (idempotent afterwards); seed if absent."""
        if not self._loaded:
            self.load()

    def load(self) -> None:
        """Load the account, seeding the default one when the file is absent."""
        if not self.path.exists():
            self._seed()
            return
        with self.path.open("rb") as f:
            data = tomllib.load(f)
        self.username = str(data.get("username", DEFAULT_USERNAME))
        self.password_hash = str(data.get("password_hash", ""))
        self.must_change_credentials = bool(data.get("must_change_credentials", True))
        self.created_at = data.get("created_at")
        self._loaded = True

    def verify(self, username: str, password: str) -> bool:
        if not hmac.compare_digest(username, self.username):
            return False
        return hmac.compare_digest(_compute_hash(self.password_hash, password), self.password_hash)

    def change_credentials(self, username: str, password: str) -> None:
        """Store a new username/password (any non-empty values) and clear the flag."""
        self.username = username
        self.password_hash = _hash_password(password)
        self.must_change_credentials = False
        self._write()

    def _seed(self) -> None:
        self.username = DEFAULT_USERNAME
        self.password_hash = _hash_password(DEFAULT_PASSWORD)
        self.must_change_credentials = True
        self.created_at = time.time()
        self._write()
        self._loaded = True

    def _write(self) -> None:
        now = time.time()
        created = self.created_at if self.created_at is not None else now
        lines = [
            "# Onyx web credentials (managed by the web UI; not plain text)",
            f"username = {_toml_str(self.username)}",
            f"password_hash = {_toml_str(self.password_hash)}",
            f"must_change_credentials = {'true' if self.must_change_credentials else 'false'}",
            f"created_at = {created}",
            f"updated_at = {now}",
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
