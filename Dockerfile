# Self-hosted API Verity Lab server.
#
# Build:  docker build -t apiverity-server .
# Run:    docker run -p 8090:8090 -v verity-data:/data apiverity-server
#
# The server stores everything in a single SQLite file; mount a volume at
# /data for persistence. Configuration via environment variables:
#   VERITY_DB   - SQLite database path inside the container (default /data/verity.db)
#   VERITY_PORT - listen port (default 8090)

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY apiverity ./apiverity

RUN pip install .

RUN useradd --system --create-home --uid 10001 verity \
    && mkdir -p /data && chown verity:verity /data
USER verity

ENV VERITY_DB=/data/verity.db \
    VERITY_PORT=8090

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('VERITY_PORT','8090') + '/healthz', timeout=2)"

CMD ["python", "-c", "import os; from apiverity.server import Store, create_app; app = create_app(Store(os.environ.get('VERITY_DB', '/data/verity.db'))); app.run(host='0.0.0.0', port=int(os.environ.get('VERITY_PORT', '8090')))"]
