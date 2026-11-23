
FROM 4gray/iptvnator:latest

# Keep the Express backend on a separate internal port.
ENV PORT=3000

# Render will need to reach nginx on port 10000.
EXPOSE 10000
