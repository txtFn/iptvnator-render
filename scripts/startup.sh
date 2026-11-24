#!/bin/sh

set -eu

DATABASE="/data/databases/iptvnator.db"
BACKUP_INTERVAL="${BACKUP_INTERVAL_SECONDS:-300}"
SCRIPT_DIR="/opt/iptvnator-backup"

echo "[Startup] Initializing IPTVnator"

# Restore before starting the application.
echo "[Restore] Checking database"

if python3 "$SCRIPT_DIR/restore.py"; then
    echo "[Restore] Database check completed"
else
    echo "[Restore] Failed; startup aborted"
    exit 1
fi

# Background backup worker.
backup_loop() {
    echo "[Backup] Automatic backup worker started"
    echo "[Backup] Interval: $BACKUP_INTERVAL seconds"

    while true; do
        sleep "$BACKUP_INTERVAL"

        if [ -f "$DATABASE" ]; then
            echo "[Backup] Checking database"

            if python3 "$SCRIPT_DIR/backup.py"; then
                echo "[Backup] Completed"
            else
                echo "[Backup] Failed; will retry"
            fi
        else
            echo "[Backup] Database not ready"
        fi
    done
}

# Enable automatic backups only when explicitly configured.
if [ "${BACKUP_UPLOAD_ENABLED:-0}" = "1" ]; then
    backup_loop &
else
    echo "[Backup] Automatic uploads disabled"
fi

# Start IPTVnator using its original startup command.
echo "[Startup] Starting IPTVnator"

export PORT=3000

exec iptvnator-entrypoint
