# Production Dockerfile — single-service deployment (Railway, Fly, etc.)
# Builds frontend static files, copies into backend, serves everything from FastAPI.

# --- Stage 1: Build frontend ---
FROM node:22-alpine AS frontend-build

WORKDIR /frontend

RUN corepack enable

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ .
RUN pnpm build


# --- Stage 2: Production backend + static assets ---
FROM ghcr.io/astral-sh/uv:0.6.14 AS uv

FROM python:3.12-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --extra team --no-install-project

COPY backend/ .
RUN uv sync --frozen --extra team

# Copy built frontend into backend/static for FastAPI to serve
COPY --from=frontend-build /frontend/dist ./static

# Persistent data directory
RUN useradd --create-home --uid 10001 arena && mkdir -p /app/data && chown -R arena:arena /app
USER arena

EXPOSE 8000

CMD ["sh", "-c", "uv run arena serve --host 0.0.0.0 --port ${PORT:-8000}"]
