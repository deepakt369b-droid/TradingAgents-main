# ─────────────────────────────────────────────────────────────────────────────
# TradingAgents — Coolify / Docker build
#
# WHY uv INSTEAD OF pip  (fixes Coolify "helper container timeout"):
#   - uv downloads & compiles dependencies in parallel and streams progress
#     output continuously, so Docker BuildKit / Coolify never mark the step
#     as "hung" (pip can go silent for minutes → false-positive OOM / timeout).
#   - UV_HTTP_TIMEOUT=600 replaces pip's default 15s socket timeout.
#
# BUILD-SPEED NOTES (this Coolify server's network is ~80 kB/s, so every MB
# counts — the previous build exceeded the 1h queue timeout on downloads):
#   - No `# syntax=docker/dockerfile:1` directive → avoids pulling the 14MB
#     BuildKit frontend image (saves ~12 min on slow networks).
#   - Single base image `python:3.12-slim` for BOTH stages; uv is installed
#     via pip (small wheel) instead of pulling the ~70MB uv base image.
#   - No curl in the runtime image; the healthcheck uses Python's stdlib.
#
# LAYER ORDERING  (keeps dependency layer cached permanently):
#   1. Copy ONLY dependency manifests (pyproject.toml, README.md, requirements.txt)
#   2. uv pip install -r requirements.txt   ← locked pins, cached across builds
#   3. Copy application source LAST
#   4. uv pip install --no-deps .           ← only this layer re-runs on code change
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_HTTP_TIMEOUT=600

# Install uv (fast Python package installer) — small wheel, avoids pulling a
# separate ~70MB uv base image on this slow network.
RUN pip install --no-cache-dir uv

# Dedicated virtualenv so the runtime image needs no build tools.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

# 1. Copy ONLY dependency manifest files first — this layer is cached and
#    reused across builds (avoids re-resolving the dependency graph).
COPY pyproject.toml README.md requirements.txt ./

# 2. Install from the locked requirements.txt (exact pins, from `uv pip compile`).
#    uv runs in parallel and emits progress so Coolify sees liveness.
RUN uv pip install --no-cache --no-build-isolation -r requirements.txt

# 3. Copy actual application code LAST — only this layer invalidates on code change.
COPY . .

# 4. Final light install without rebuilding dependencies.
RUN uv pip install --no-cache --no-deps --no-build-isolation .

# ─────────────────────────────────────────────────────────────────────────────
# Runtime stage — slim image with no build tooling.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home appuser \
 && install -d -m 0755 -o appuser -g appuser /home/appuser/.tradingagents
USER appuser
WORKDIR /home/appuser/app

COPY --from=builder --chown=appuser:appuser /build .

# Ensure the project config store directory is writable by the app user so
# API keys & settings saved from the browser persist inside the project.
RUN mkdir -p /home/appuser/app/config

EXPOSE 8000

# Headless web server for Coolify / Docker deployments.
# Binds to 0.0.0.0 so the app is reachable through Coolify's proxy.
# (The desktop launcher `python -m app` is NOT used here — it binds to
# 127.0.0.1 on a random port and tries to open a native window, which
# fails in a headless container.)
CMD ["uvicorn", "app.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]