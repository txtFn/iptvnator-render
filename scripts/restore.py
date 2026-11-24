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

BACKUP_PATH = (
    "test/backup.db.enc"
    if os.getenv("BACKUP_TEST_MODE") == "1"
    else "backups/iptvnator.db.enc"
)


def download_backup():
    token = os.environ["GITHUB_BACKUP_TOKEN"]

    base_url = (
        f"https://api.github.com/repos/{REPOSITORY}"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.raw+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "IPTVnator-Restore",
    }

    # Verify repository access.
    request = urllib.request.Request(
        base_url,
        headers=headers,
    )

    with urllib.request.urlopen(
        request, timeout=60
    ) as response:
        response.read()

    url = f"{base_url}/contents/{BACKUP_PATH}"

    request = urllib.request.Request(
        url,
        headers=headers,
    )

    try:
        with urllib.request.urlopen(
            request, timeout=120
        ) as response:
            return response.read()

    except urllib.error.HTTPError as error:
        if error.code == 404:
            print("Remote backup not found")
            return None

        raise


def restore_database():
    if DATABASE.exists():
        print("Existing database found; restore skipped")
        return

    key = base64.b64decode(
        os.environ["BACKUP_ENCRYPTION_KEY"],
        validate=True,
    )

    if len(key) != 32:
        raise RuntimeError(
            "Encryption key must be 32 bytes"
        )

    print("Downloading encrypted SQLite backup")
    print(f"Backup location: {BACKUP_PATH}")

    encrypted = download_backup()

    if encrypted is None:
        if os.getenv("BACKUP_TEST_MODE") == "1":
            raise RuntimeError(
                "Required test backup not found"
            )

        if os.getenv("ALLOW_INITIAL_SETUP") != "1":
            raise RuntimeError(
                "Production backup not found; "
                "initial setup is not authorized"
            )

        print("No production backup available")
        print("IPTVnator may initialize a new database")
        return

    if not encrypted.startswith(MAGIC):
        raise RuntimeError("Invalid backup format")

    if len(encrypted) < len(MAGIC) + 12 + 16:
        raise RuntimeError("Incomplete encrypted backup")

    offset = len(MAGIC)

    nonce = encrypted[offset:offset + 12]
    ciphertext = encrypted[offset + 12:]

    recovered = AESGCM(key).decrypt(
        nonce,
        ciphertext,
        MAGIC,
    )

    del encrypted
    del ciphertext

    DATABASE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with tempfile.TemporaryDirectory(
        dir=DATABASE.parent
    ) as folder:

        restored = Path(folder) / "restored.db"

        restored.write_bytes(recovered)

        del recovered

        connection = sqlite3.connect(
            f"file:{restored}?mode=ro",
            uri=True,
        )

        try:
            result = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()

            if result != ("ok",):
                raise RuntimeError(
                    "Restored database integrity check failed"
                )

            tables = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]

            if tables == 0:
                raise RuntimeError(
                    "Restored database has an empty schema"
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
