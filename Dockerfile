FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY . .
RUN pip install --no-cache-dir .

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
