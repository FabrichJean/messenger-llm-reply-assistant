# syntax=docker/dockerfile:1
# --- 1) client Messenger (Go + SQLite via cgo) -------------------------------------------------------------
ARG GO_VERSION=1.26
FROM golang:${GO_VERSION}-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd/ ./cmd/
COPY internal/ ./internal/
RUN CGO_ENABLED=1 go build -trimpath -ldflags="-s -w" -o /out/messenger-lite ./cmd/messenger-lite

# --- 2) image d'exécution : hub Python + Claude CLI + client ----------------------------------------------
FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tini nodejs npm \
 && npm install -g @anthropic-ai/claude-code \
 && npm cache clean --force \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin hub \
 && mkdir -p /data/accounts && chown -R hub:hub /data

WORKDIR /app
COPY hub/ /app/hub/
COPY extension/ /app/extension/
COPY dist/relais.apk /app/dist/relais.apk
COPY --from=build /out/messenger-lite /app/messenger-lite

ENV HUB_BIND=0.0.0.0 \
    HUB_PORT=8787 \
    HUB_DATA=/data \
    HUB_ACCOUNTS_ROOT=/data/accounts \
    HUB_CLIENT_BIN=/app/messenger-lite \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/hub

USER hub
VOLUME ["/data", "/home/hub"]
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD curl -fsS http://127.0.0.1:8787/healthz || exit 1
ENTRYPOINT ["tini", "--"]
CMD ["python3", "/app/hub/hub.py"]
