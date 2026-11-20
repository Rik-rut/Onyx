FROM python:3.11-slim

# Install system dependencies including transmission-daemon and ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    transmission-daemon \
    transmission-cli \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv binary from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency definition
COPY pyproject.toml uv.lock* ./

# Copy full application source code
COPY . /app

# Install application and all dependencies with uv
RUN uv sync --frozen --no-dev || uv sync --no-dev

# Ensure entrypoint script is executable
RUN chmod +x /app/docker-entrypoint.sh

# Create mount points
RUN mkdir -p /config /downloads/movies /downloads/tv-shows

EXPOSE 3698 9091 51413 51413/udp

ENTRYPOINT ["/app/docker-entrypoint.sh"]
