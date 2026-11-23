
FROM 4gray/iptvnator:latest

# Use port 3000 for the internal backend
ENV PORT=3000
ENV BACKEND_URL=/api

# Make nginx listen on Render's public port
RUN sed -i \
    -e 's/listen[[:space:]]*80;/listen 10000;/' \
    -e 's/listen[[:space:]]*\[::\]:80;/listen [::]:10000;/' \
    /etc/nginx/http.d/default.conf.template

EXPOSE 10000

# Override PORT at startup for the backend.
# Preserve the original entrypoint.
CMD ["sh", "-c", "PORT=3000 exec iptvnator-entrypoint"]
