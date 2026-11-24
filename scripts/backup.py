
import base64
import hashlib
import json
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


def github_request(url, token, method="GET", payload=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "IPTVnator-Backup",
    }

    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(
        request, timeout=60
    ) as response:
        return json.loads(response.read())


def upload_backup(encrypted, key):
    token = os.environ["GITHUB_BACKUP_TOKEN"]

    test_mode = os.getenv("BACKUP_TEST_MODE") == "1"

    if test_mode:
        path = "test/backup.db.enc"
    else:
        path = "backups/iptvnator.db.enc"

    url = (
        f"https://api.github.com/repos/"
        f"{REPOSITORY}/contents/{path}"
    )

    existing_sha = None

    try:
        existing = github_request(url, token)
        existing_sha = existing["sha"]

        # Compare decrypted snapshots, not random ciphertext.
        if existing.get("content"):
            previous = base64.b64decode(existing["content"])

            if not previous.startswith(MAGIC):
                raise RuntimeError("Invalid existing backup format")

            previous_nonce = previous[len(MAGIC):len(MAGIC) + 12]

            previous_plain = AESGCM(key).decrypt(
                previous_nonce,
                previous[len(MAGIC) + 12:],
                MAGIC,
            )

            current_plain = AESGCM(key).decrypt(
                encrypted[len(MAGIC):len(MAGIC) + 12],
                encrypted[len(MAGIC) + 12:],
                MAGIC,
            )

            if hashlib.sha256(previous_plain).digest() == \
               hashlib.sha256(current_plain).digest():
                print("Database unchanged; upload skipped")
                return

    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise

    payload = {
        "message": "Update encrypted IPTVnator backup",
        "content": base64.b64encode(encrypted).decode("ascii"),
    }

    if existing_sha:
        payload["sha"] = existing_sha

    github_request(
        url,
        token,
        method="PUT",
        payload=payload,
    )

    print("Encrypted backup uploaded successfully")
    print(f"Backup location: {path}")


def create_backup():
    if not DATABASE.is_file():
        raise RuntimeError("Database missing; backup aborted")

    key = base64.b64decode(
        os.environ["BACKUP_ENCRYPTION_KEY"],
        validate=True,
    )

    if len(key) != 32:
        raise RuntimeError("Encryption key must be 32 bytes")

    with tempfile.TemporaryDirectory() as folder:
        snapshot = Path(folder) / "snapshot.db"

        source = sqlite3.connect(
            f"file:{DATABASE}?mode=ro",
            uri=True,
            timeout=30,
        )

        try:
            destination = sqlite3.connect(str(snapshot))

            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()

        check = sqlite3.connect(
            f"file:{snapshot}?mode=ro",
            uri=True,
        )

        try:
            result = check.execute(
                "PRAGMA integrity_check"
            ).fetchone()

            if result != ("ok",):
                raise RuntimeError(
                    "SQLite integrity check failed"
                )

            tables = check.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]

            if tables == 0:
                raise RuntimeError(
                    "Empty database schema; backup aborted"
                )

        finally:
            check.close()

        plaintext = snapshot.read_bytes()
        nonce = os.urandom(12)

        ciphertext = AESGCM(key).encrypt(
            nonce,
            plaintext,
            MAGIC,
        )

        encrypted = MAGIC + nonce + ciphertext

        recovered = AESGCM(key).decrypt(
            nonce,
            ciphertext,
            MAGIC,
        )

        if recovered != plaintext:
            raise RuntimeError("Backup verification failed")

        print("Encrypted SQLite snapshot verified")
        print(f"Encrypted size: {len(encrypted)} bytes")

        if os.getenv("BACKUP_UPLOAD_ENABLED") == "1":
            upload_backup(encrypted, key)
        else:
            print("GitHub upload disabled; verification only")


if __name__ == "__main__":
    create_backup()
