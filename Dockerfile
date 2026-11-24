FROM 4gray/iptvnator:latest

# Dependencies for encrypted SQLite backups
RUN apk add --no-cache \
    python3 \
    py3-cryptography \
    sqlite \
    curl \
    ca-certificates

# Internal backend configuration
ENV PORT=3000
ENV BACKEND_URL=/api

# Automatic backup interval: 5 minutes
ENV BACKUP_INTERVAL_SECONDS=300

# Make nginx listen on Render's public port
RUN sed -i \
    -e 's/listen[[:space:]]*80;/listen 10000;/' \
    -e 's/listen[[:space:]]*\[::\]:80;/listen [::]:10000;/' \
    /etc/nginx/http.d/default.conf.template

# Install backup and restoration scripts
RUN mkdir -p /opt/iptvnator-backup

COPY scripts/backup.py /opt/iptvnator-backup/backup.py
COPY scripts/restore.py /opt/iptvnator-backup/restore.py
COPY scripts/startup.sh /opt/iptvnator-backup/startup.sh

# Normalize line endings and permissions
RUN sed -i 's/\r$//' /opt/iptvnator-backup/startup.sh \
    && chmod +x /opt/iptvnator-backup/startup.sh

EXPOSE 10000

# Start through the custom backup and restore wrapper
ENTRYPOINT ["/bin/sh", "/opt/iptvnator-backup/startup.sh"]
CMD []
