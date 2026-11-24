# syntax=docker/dockerfile:1
# --- 1) client Messenger (Go + SQLite via cgo) -------------------------------------------------------------
ARG GO_VERSION=1.26
FROM golang:${GO_VERSION}-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=1 go build -trimpath -ldflags="-s -w" -o /out/messenger-lite .

# --- 2) image d'exécution : hub Python + Claude CLI + client ----------------------------------------------
FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tini nodejs npm \
 && npm install -g @anthropic-ai/claude-code \
 && npm cache clean --force \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin hub \
 && mkdir -p /data/accounts && chown -R hub:hub /data

