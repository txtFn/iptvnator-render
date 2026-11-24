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

# Conservative upload limit for memory and API usage.
DEFAULT_MAX_BACKUP_MB = 25


def github_request(
    url,
    token,
    method="GET",
    payload=None,
    raw=False,
):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": (
            "application/vnd.github.raw+json"
            if raw
            else "application/vnd.github+json"
        ),
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
        request, timeout=120
    ) as response:

        if raw:
            return response.read()

        return json.loads(response.read())


def decrypt_backup(encrypted, key):
    if not encrypted.startswith(MAGIC):
        raise RuntimeError("Invalid backup format")

    if len(encrypted) < len(MAGIC) + 12 + 16:
        raise RuntimeError("Incomplete encrypted backup")

    offset = len(MAGIC)

    nonce = encrypted[offset:offset + 12]
    ciphertext = encrypted[offset + 12:]

    return AESGCM(key).decrypt(
        nonce,
        ciphertext,
        MAGIC,
    )


def upload_backup(encrypted, key):
    token = os.environ["GITHUB_BACKUP_TOKEN"]

    max_mb = int(
        os.getenv(
            "MAX_BACKUP_SIZE_MB",
            str(DEFAULT_MAX_BACKUP_MB),
        )
    )

    if not 1 <= max_mb <= 95:
        raise RuntimeError("Invalid maximum backup size")

    max_bytes = max_mb * 1024 * 1024

    if len(encrypted) > max_bytes:
        raise RuntimeError(
            f"Backup exceeds configured {max_mb} MiB limit; "
            "upload aborted"
        )

    test_mode = os.getenv("BACKUP_TEST_MODE") == "1"

    if test_mode:
        path = "test/backup.db.enc"
    else:
        path = "backups/iptvnator.db.enc"

    base_url = (
        f"https://api.github.com/repos/{REPOSITORY}"
    )

    url = f"{base_url}/contents/{path}"

    # Verify repository access.
    github_request(base_url, token)

    existing_sha = None
    existing = None

    try:
        existing = github_request(url, token)

    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise

        print("No existing backup found")

    if existing is not None:
        existing_sha = existing["sha"]

        print("Existing remote backup found")
        print(
            f"Remote backup size: "
            f"{existing.get('size', 'unknown')} bytes"
        )

        if existing.get("size", 0) > max_bytes:
            raise RuntimeError(
                "Existing remote backup exceeds configured "
                "size limit; upload aborted"
            )

        # Download raw contents using the immutable blob SHA.
        # This also supports files larger than 1 MB.
        blob_url = (
            f"{base_url}/git/blobs/{existing_sha}"
        )

        previous = github_request(
            blob_url,
            token,
            raw=True,
        )

        previous_plain = decrypt_backup(
            previous,
            key,
        )

        previous_hash = hashlib.sha256(
            previous_plain
        ).digest()

        del previous_plain
        del previous

        current_plain = decrypt_backup(
            encrypted,
            key,
        )

        current_hash = hashlib.sha256(
            current_plain
        ).digest()

        del current_plain

        if previous_hash == current_hash:
            print("Database unchanged; upload skipped")
            return

        print("Database changes detected")

    payload = {
        "message": "Update encrypted IPTVnator backup",
        "content": base64.b64encode(
            encrypted
        ).decode("ascii"),
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
        raise RuntimeError(
            "Database missing; backup aborted"
        )

    key = base64.b64decode(
        os.environ["BACKUP_ENCRYPTION_KEY"],
        validate=True,
    )

    if len(key) != 32:
        raise RuntimeError(
            "Encryption key must be 32 bytes"
        )

    with tempfile.TemporaryDirectory() as folder:
        snapshot = Path(folder) / "snapshot.db"

        source = sqlite3.connect(
            f"file:{DATABASE}?mode=ro",
            uri=True,
            timeout=30,
        )

        try:
            destination = sqlite3.connect(
                str(snapshot)
            )

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

            if os.getenv("BACKUP_TEST_MODE") != "1":
                playlist_table = check.execute(
                    "SELECT COUNT(*) FROM sqlite_master "
                    "WHERE type='table' AND name='playlists'"
                ).fetchone()[0]

                if playlist_table == 0:
                    raise RuntimeError(
                        "Playlists table missing; backup aborted"
                    )

                playlist_count = check.execute(
                    "SELECT COUNT(*) FROM playlists"
                ).fetchone()[0]

                print(f"Playlist count: {playlist_count}")

                if playlist_count == 0:
                    raise RuntimeError(
                        "No playlists found; backup aborted "
                        "to protect existing remote backup"
                    )

                print(
                    "Production playlist validation passed"
                )

            else:
                print(
                    "Test mode: playlist validation skipped"
                )

        finally:
            check.close()

        upload_enabled = (
            os.getenv("BACKUP_UPLOAD_ENABLED") == "1"
        )

        # Check size before loading the snapshot into memory.
        if upload_enabled:
            max_mb = int(
                os.getenv(
                    "MAX_BACKUP_SIZE_MB",
                    str(DEFAULT_MAX_BACKUP_MB),
                )
            )

            if not 1 <= max_mb <= 95:
                raise RuntimeError(
                    "Invalid maximum backup size"
                )

            estimated_size = (
                snapshot.stat().st_size
                + len(MAGIC)
                + 12
                + 16
            )

            if estimated_size > max_mb * 1024 * 1024:
                raise RuntimeError(
                    f"Snapshot exceeds configured "
                    f"{max_mb} MiB limit; backup aborted"
                )

        plaintext = snapshot.read_bytes()

        nonce = os.urandom(12)

        ciphertext = AESGCM(key).encrypt(
            nonce,
            plaintext,
            MAGIC,
        )

        encrypted = MAGIC + nonce + ciphertext

        del ciphertext

        recovered = decrypt_backup(
            encrypted,
            key,
        )

        if recovered != plaintext:
            raise RuntimeError(
                "Backup verification failed"
            )

        del recovered
        del plaintext

        print("Encrypted SQLite snapshot verified")
        print(f"Encrypted size: {len(encrypted)} bytes")

        if upload_enabled:
            upload_backup(encrypted, key)
        else:
            print(
                "GitHub upload disabled; verification only"
            )


if __name__ == "__main__":
    create_backup()
