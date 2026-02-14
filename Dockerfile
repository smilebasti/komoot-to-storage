# syntax=docker/dockerfile:1

## -----------------------------------------------------
## Build stage (use tag with -dev suffix: e.g. 3.9.23-debian13-fips-dev)
FROM docker.io/library/python:3-slim AS build-stage AS build-stage

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

RUN python -m venv /app/venv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

## -----------------------------------------------------
## Final stage (use the same tag as above but without the -dev suffix e.g. 3.9.23-debian13-fips)
FROM docker.io/library/python:3-slim AS runtime-stage

MAINTAINER komoot@smilebasti.de

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

COPY --from=build-stage /app/venv /app/venv
COPY app.py .
COPY exporter.py .
COPY translations.py .
COPY templates templates

EXPOSE 5000

# Health check using Python directly (no shell needed)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/health', timeout=5)"]

CMD ["python", "/app/app.py"]
