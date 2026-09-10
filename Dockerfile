# API Verity Lab: the CLI and the self-hosted server, in one image.
#
# Build:  docker build -t apiverity .
#
# Serve:  docker run -p 8090:8090 -v verity-data:/data apiverity
# CLI:    docker run -v "$PWD:/work" apiverity breaking old.yaml new.yaml
#         docker run apiverity --help
#
# The image used to start the server and nothing else was documented. Running
# the CLI did work -- Docker replaces `CMD` with whatever follows the image
# name, and the console script is on PATH -- but nothing said so, nothing
# tested it, and it meant typing `apiverity` again after an image already named
# that. `docker/entrypoint.sh` dispatches now: `serve` is the default, anything
# else is a subcommand.
#
# The server stores everything in a single SQLite file; mount a volume at
# /data for persistence. Configuration via environment variables:
#   VERITY_DB           - SQLite database path inside the container (default /data/verity.db)
#   VERITY_PORT         - listen port (default 8090)
#   VERITY_CORS_ORIGINS - comma-separated browser origins allowed to call the
#                         API, for the dashboard. Empty by default: a server
#                         that answers every origin is one whose operator never
#                         chose to, and `*` is refused outright because every
#                         route here is authenticated.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY apiverity ./apiverity

RUN pip install .

COPY docker/entrypoint.sh /usr/local/bin/apiverity-entrypoint
RUN chmod +x /usr/local/bin/apiverity-entrypoint

# `/work` is where a caller mounts their contracts, and it is created and owned
# here so a `-v "$PWD:/work"` bind mount is readable by the unprivileged user
# the image runs as. Without it the CLI's first useful invocation is a
# permission error.
RUN useradd --system --create-home --uid 10001 verity \
    && mkdir -p /data /work \
    && chown verity:verity /data /work
USER verity
WORKDIR /work

ENV VERITY_DB=/data/verity.db \
    VERITY_PORT=8090

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('VERITY_PORT','8090') + '/healthz', timeout=2)"

ENTRYPOINT ["apiverity-entrypoint"]
CMD ["serve"]
