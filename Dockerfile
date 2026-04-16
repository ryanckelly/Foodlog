FROM python:3.12-slim

WORKDIR /app

# Install the package (editable mode for simplicity)
COPY pyproject.toml ./
COPY foodlog/ ./foodlog/
COPY mcp_server/ ./mcp_server/

RUN pip install --no-cache-dir -e .

# Data directory for SQLite (mounted from host via compose)
RUN mkdir -p /data
VOLUME ["/data"]

# Internal port. Tailscale serve.json forwards 3473 -> 3474.
EXPOSE 3474

CMD ["python", "-m", "foodlog.api.app"]
