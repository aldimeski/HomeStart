"""AES-256-GCM encryption for credentials of external systems (they must be readable again, so not hashed).

The key lives in a separate file, so a copy of the database alone does not reveal the passwords.
"""

import base64
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import ConfigError

log = logging.getLogger("homestart.secrets")

KEY_BYTES = 32
NONCE_BYTES = 12


class SecretBox:
    def __init__(self, key: bytes):
        self._aes = AESGCM(key)

    @classmethod
    def from_key_file(cls, path: Path) -> "SecretBox":
        if not path.exists():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as fh:
                    fh.write(base64.b64encode(os.urandom(KEY_BYTES)).decode() + "\n")
            except OSError as exc:
                raise ConfigError(f"Cannot create encryption key file {path}: {exc}") from exc
            log.warning("Created new encryption key file %s; back it up together with the database", path)

        try:
            key = base64.b64decode(path.read_text().strip(), validate=True)
        except (OSError, ValueError) as exc:
            raise ConfigError(f"Cannot read encryption key file {path}: {exc}") from exc
        if len(key) != KEY_BYTES:
            raise ConfigError(f"Encryption key file {path} must contain {KEY_BYTES} base64-encoded bytes")
        return cls(key)

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        return base64.b64encode(nonce + self._aes.encrypt(nonce, plaintext.encode(), None)).decode()

    def decrypt(self, token: str) -> str:
        raw = base64.b64decode(token)
        return self._aes.decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], None).decode()
