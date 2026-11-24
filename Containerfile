# syntax=docker/dockerfile:1

FROM docker.io/library/node:24-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM docker.io/library/python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CROWDTRACKER_DB=/data/crowdtracker.db \
    CROWDTRACKER_STATIC=/app/static
WORKDIR /app

# Install only the runtime dependencies listed in pyproject.toml; the app itself runs from /app.
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir $(python -c "import tomllib; print(' '.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))")

COPY backend/app ./app
COPY --from=web /web/dist ./static

RUN useradd --system --uid 10001 --no-create-home crowdtracker \
    && mkdir /data \
    && chown crowdtracker /data
USER 10001

VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
