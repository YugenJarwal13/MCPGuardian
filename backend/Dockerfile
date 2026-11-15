# syntax=docker/dockerfile:1
# MCP Guardian API: FastAPI + WebSocket, the CrewAI/ADK inspectors and the A2A case manager.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# dependencies first, so a code change does not reinstall them
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home --uid 1000 guardian \
    && mkdir -p logs && chown -R guardian:guardian /app
USER guardian

# Public-deployment defaults; docker-compose.yml and the env file override them.
ENV GUARDIAN_PUBLIC=1 \
    GUARDIAN_RUNS_PER_HOUR=12 \
    GUARDIAN_CONCURRENT_RUNS=2 \
    GUARDIAN_LLM_RUNS_PER_DAY=25 \
    GUARDIAN_TRACE_FILE=off \
    LLM_PROVIDER=openrouter \
    LLM_MODEL=dots-studio/dots-3-note-preview:free \
    OPENROUTER_FALLBACK_MODELS=nvidia/nemotron-3.5-lightning:free \
    LLM_STRUCTURED_METHODS=response_format,tool_call \
    LLM_LOCAL_FALLBACK=off

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# --ws-max-size: requests are tiny JSON messages; anything larger is refused by the server itself.
# --proxy-headers: the reverse proxy in front (the `web` service) supplies the visitor's address.
CMD ["python", "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--ws-max-size", "65536", "--proxy-headers", "--forwarded-allow-ips=*"]
