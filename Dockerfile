
FROM 4gray/iptvnator:latest

ENV PORT=3000
ENV BACKEND_URL=/api

# Change both IPv4 and IPv6 nginx listeners
RUN sed -i \
    -e 's/listen       80;/listen       10000;/' \
    -e 's/listen  \[::\]:80;/listen  [::]:10000;/' \
    /etc/nginx/http.d/default.conf.template

EXPOSE 10000

CMD ["iptvnator-entrypoint"]
