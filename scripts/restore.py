
import base64
import os
import sqlite3
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DATABASE = Path("/data/databases/iptvnator.db")
MAGIC = b"IPTVBACKUP1"

REPOSITORY = "txtFn/iptvnator-backups"
BACKUP_PATH = "backups/iptvnator.db.enc"


def download_backup():
    token = os.environ["GITHUB_BACKUP_TOKEN"]

    url = (
        f"https://api.github.com/repos/"
        f"{REPOSITORY}/contents/{BACKUP_PATH}"
    )

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.raw+json",
            "User-Agent": "IPTVnator-Restore"
        }
    )

    with urllib.request.urlopen(
        request, timeout=60
    ) as response:
        return response.read()


def restore_database():
    if DATABASE.exists():
        print("Existing database found; restore skipped")
        return

    key = base64.b64decode(
        os.environ["BACKUP_ENCRYPTION_KEY"],
        validate=True
    )

    if len(key) != 32:
        raise RuntimeError(
            "Encryption key must be 32 bytes"
        )

    print("Downloading encrypted SQLite backup")

    encrypted = download_backup()

    if not encrypted.startswith(MAGIC):
        raise RuntimeError("Invalid backup format")

    offset = len(MAGIC)
    nonce = encrypted[offset:offset + 12]
    ciphertext = encrypted[offset + 12:]

    recovered = AESGCM(key).decrypt(
        nonce,
        ciphertext,
        MAGIC
    )

    DATABASE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with tempfile.TemporaryDirectory(
        dir=DATABASE.parent
    ) as folder:

        restored = Path(folder) / "restored.db"

        restored.write_bytes(recovered)

        connection = sqlite3.connect(
            f"file:{restored}?mode=ro",
            uri=True
        )

        try:
            result = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()

            if result != ("ok",):
                raise RuntimeError(
                    "Restored database integrity check failed"
                )
        finally:
            connection.close()

        if DATABASE.exists():
            raise RuntimeError(
                "Database appeared during restoration"
            )

        os.replace(restored, DATABASE)

    print("SQLite database restored successfully")
    print(f"Restored size: {DATABASE.stat().st_size} bytes")


if __name__ == "__main__":
    restore_database()
