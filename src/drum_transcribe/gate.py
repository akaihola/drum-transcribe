"""Creation throttling for the public cloud deployment.

Active only when the CREATE_PASSWORDS env var is set (the laptop server
stays unlimited). Anonymous creations are capped globally per sliding
window, counted from tiny `created` marker files in the version
directories — the timestamp lives in the file *content* because the bucket
re-sync at every cold start rewrites mtimes. Past the cap, POST /api/unlock
with a configured password sets a bypass cookie: HMAC(TOKEN_SECRET, salt of
the matched password entry), so deleting a person's entry from
CREATE_PASSWORDS also revokes every token they ever minted, and rotating
TOKEN_SECRET revokes all tokens at once.

Env vars: CREATE_PASSWORDS ("salt:scrypt-hex,..." — one entry per person,
from `drum-transcribe hash-password`), TOKEN_SECRET (any long random
string), THROTTLE_MAX (default 3), THROTTLE_HOURS (default 24).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from pathlib import Path

SCRYPT = {"n": 2**14, "r": 8, "p": 1}
COOKIE = "create_token"


def enabled() -> bool:
    return bool(os.environ.get("CREATE_PASSWORDS"))


def _entries() -> list[list[str]]:
    return [e.split(":", 1) for e in os.environ["CREATE_PASSWORDS"].split(",") if e]


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), **SCRYPT)
    return f"{salt}:{digest.hex()}"


def generate_passphrase() -> str:
    """Four pronounceable words, ~72 bits — brute-forcing /api/unlock is moot."""
    syllables = [c + v for c in "bdfgklmnprstv" for v in "aeiou"]
    return "-".join("".join(secrets.choice(syllables) for _ in range(3))
                    for _ in range(4))


def verify_password(password: str) -> str | None:
    """Salt of the matching CREATE_PASSWORDS entry, or None."""
    for salt, digest in _entries():
        if hmac.compare_digest(hash_password(password, salt), f"{salt}:{digest}"):
            return salt
    return None


def token_for(salt: str) -> str:
    return hmac.new(os.environ["TOKEN_SECRET"].encode(), salt.encode(),
                    hashlib.sha256).hexdigest()


def valid_token(token: str | None) -> bool:
    return bool(token) and any(
        hmac.compare_digest(token, token_for(salt)) for salt, _ in _entries())


def allow_anonymous(root: Path) -> bool:
    """Is the global anonymous-creation budget still open?"""
    limit = int(os.environ.get("THROTTLE_MAX", "3"))
    cutoff = time.time() - float(os.environ.get("THROTTLE_HOURS", "24")) * 3600
    recent = 0
    for marker in root.glob("*/*/created"):
        try:
            stamp, kind = marker.read_text().split()
            recent += kind == "anon" and float(stamp) > cutoff
        except ValueError:
            pass
    return recent < limit


def write_marker(version_dir: Path, authorized: bool) -> None:
    version_dir.mkdir(parents=True, exist_ok=True)
    marker = version_dir / "created"
    marker.write_text(f"{int(time.time())} {'auth' if authorized else 'anon'}\n")
    if enabled():
        threading.Thread(target=_upload, args=(marker,), daemon=True).start()


def _upload(marker: Path) -> None:
    """Persist the marker to the bucket so cold starts still count it."""
    try:
        import json

        import boto3  # ty: ignore[unresolved-import]

        c = json.loads(Path(".secrets.worker-s3.json").read_text())
        s3 = boto3.client("s3", endpoint_url=c["endpoint"], region_name=c["region"],
                          aws_access_key_id=c["access_key"],
                          aws_secret_access_key=c["secret_key"])
        s3.upload_file(str(marker), c["bucket"],
                       f"{marker.parent.parent.name}/{marker.parent.name}/created")
    except Exception as e:  # noqa: BLE001
        print(f"created-marker upload failed (cap resets at next cold start): {e!r}",
              flush=True)
