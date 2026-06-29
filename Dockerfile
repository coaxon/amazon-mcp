FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY amazon_mcp/ amazon_mcp/
COPY scripts/verify_install.sh scripts/verify_install.sh

ENV PYTHONUNBUFFERED=1 \
    AMAZON_MCP_TRANSPORT=streamable-http \
    AMAZON_MCP_HOST=0.0.0.0 \
    AMAZON_MCP_PORT=8780 \
    AMAZON_MCP_DRY_RUN=1

EXPOSE 8780

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -sf "http://127.0.0.1:8780/health" || exit 1

CMD ["python", "-m", "amazon_mcp"]
