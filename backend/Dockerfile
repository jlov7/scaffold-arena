FROM ghcr.io/astral-sh/uv:0.6.14 AS uv

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=uv /uv /uvx /bin/

WORKDIR /app


FROM base AS dev

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra dev --no-install-project

COPY . .
RUN uv sync --frozen --extra dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]


FROM base AS prod

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra team --no-install-project

COPY . .
RUN uv sync --frozen --extra team

RUN useradd --create-home --uid 10001 arena && chown -R arena:arena /app
USER arena

EXPOSE 8000

CMD ["uv", "run", "arena", "serve", "--host", "0.0.0.0", "--port", "8000"]
