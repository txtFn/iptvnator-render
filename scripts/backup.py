
import base64
import os
import sqlite3
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DATABASE = Path("/data/databases/iptvnator.db")
MAGIC = b"IPTVBACKUP1"


def create_backup():
    if not DATABASE.is_file():
        raise RuntimeError("Database missing; backup aborted")

    key = base64.b64decode(
        os.environ["BACKUP_ENCRYPTION_KEY"],
        validate=True
    )

    if len(key) != 32:
        raise RuntimeError("Encryption key must be 32 bytes")

    with tempfile.TemporaryDirectory() as folder:
        snapshot = Path(folder) / "snapshot.db"

        source = sqlite3.connect(
            f"file:{DATABASE}?mode=ro",
            uri=True
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
            uri=True
        )

        try:
            result = check.execute(
                "PRAGMA integrity_check"
            ).fetchone()

            if result != ("ok",):
                raise RuntimeError("SQLite integrity check failed")
        finally:
            check.close()

        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(
            nonce,
            snapshot.read_bytes(),
            MAGIC
        )

        output = Path(folder) / "backup.db.enc"
        output.write_bytes(MAGIC + nonce + ciphertext)

        # Verify authenticated decryption.
        recovered = AESGCM(key).decrypt(
            nonce,
            output.read_bytes()[len(MAGIC) + 12:],
            MAGIC
        )

        if recovered != snapshot.read_bytes():
            raise RuntimeError("Backup verification failed")

        print("Encrypted SQLite snapshot verified")
        print(f"Encrypted size: {output.stat().st_size} bytes")


if __name__ == "__main__":
    create_backup()
