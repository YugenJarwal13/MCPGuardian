# MCP Guardian: one container serving the web app, the API and the DVMCP demo lab.
# Built for a free Hugging Face Space (Docker SDK, port 7860), but runs anywhere:
#   docker build -t mcp-guardian .
#   docker run -p 7860:7860 -e OPENROUTER_API_KEY=... mcp-guardian

# ---- 1. build the React app --------------------------------------------------
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. the Python backend ----------------------------------------------------
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY --from=web /web/dist frontend/dist
COPY deploy/start.sh deploy/start.sh

# the DVMCP lab (deliberately vulnerable servers) is cloned at build time; it binds to 127.0.0.1 only
RUN git clone --depth 1 https://github.com/harishsg993010/damn-vulnerable-MCP-server \
        backend/external/damn-vulnerable-MCP-server \
    && mkdir -p backend/logs \
    && useradd -m -u 1000 user && chown -R user:user /app
USER user

# Public-deployment defaults. Secrets (OPENROUTER_API_KEY, optional LANGFUSE_*) come from the host's settings.
ENV GUARDIAN_PUBLIC=1 \
    GUARDIAN_RUNS_PER_HOUR=12 \
    GUARDIAN_CONCURRENT_RUNS=2 \
    GUARDIAN_LLM_RUNS_PER_DAY=10 \
    LLM_PROVIDER=openrouter \
    LLM_MODEL=dots-studio/dots-3-note-preview:free \
    OPENROUTER_FALLBACK_MODELS=nvidia/nemotron-3.5-lightning:free \
    LLM_STRUCTURED_METHODS=response_format,tool_call \
    LLM_LOCAL_FALLBACK=off \
    PYTHONUNBUFFERED=1 \
    PORT=7860
EXPOSE 7860
CMD ["bash", "deploy/start.sh"]
