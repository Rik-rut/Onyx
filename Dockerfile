# Stage 1: Compile the Svelte 5 + Vite + Tailwind CSS SPA into static assets.
FROM node:22-slim AS spa
WORKDIR /workspace/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Pure Python + Transmission + FFmpeg runtime serving compiled static assets.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    transmission-daemon \
    transmission-cli \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv via the official installer (fetches from GitHub releases),
# avoiding a ghcr.io pull so the build works on hosts whose registry
# mirrors do not resolve ghcr.
RUN curl -fsSL https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock* ./
COPY . /app

# Copy only the freshly compiled SPA static bundle from the Node build stage
COPY --from=spa /workspace/src/arr/web/static/dist /app/src/arr/web/static/dist

# Sync the runtime venv, then install the bundled Chromium for the TPB
# browser indexer (must run through uv so the venv contains playwright).
RUN uv sync --frozen --no-dev || uv sync --no-dev
RUN uv run playwright install --with-deps chromium

RUN chmod +x /app/docker-entrypoint.sh
RUN mkdir -p /config /downloads/movies /downloads/tv-shows

EXPOSE 3698 9091 51413 51413/udp

ENTRYPOINT ["/app/docker-entrypoint.sh"]
