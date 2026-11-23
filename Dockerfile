
FROM 4gray/iptvnator:latest

# Internal Express backend
ENV PORT=3000

# Browser-facing API path
ENV BACKEND_URL=/api

# Change nginx's listening port from 80 to 10000
RUN sed -i -E 's/listen[[:space:]]+80([[:space:];])/listen 10000\1/g' /etc/nginx/http.d/default.conf.template

# Public HTTP port for Render
EXPOSE 10000

# Keep the original IPTVnator startup command
CMD ["iptvnator-entrypoint"]
