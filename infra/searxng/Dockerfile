FROM searxng/searxng:latest

# Copy custom engines from build context into the image without removing built-ins
COPY searx/engines/ /usr/local/searxng/searx/engines/

# Ensure permissions (fallback if chown is unsupported)
RUN if [ -d /usr/local/searxng/searx/engines ]; then chown -R 1000:1000 /usr/local/searxng/searx/engines || true; fi
