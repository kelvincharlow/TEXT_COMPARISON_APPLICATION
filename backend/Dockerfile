FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POSTBANK_ENGINE_CACHE=/app/engine-cache \
    POSTBANK_STORAGE_ROOT=/tmp/postbank-runtime \
    HOME=/tmp

WORKDIR /app

RUN apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 update \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 \
        install --yes --no-install-recommends libicu72 libreoffice-writer poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 postbank \
    && useradd --uid 10001 --gid postbank --no-create-home --shell /usr/sbin/nologin postbank

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY --chown=postbank:postbank backend/__init__.py ./backend/__init__.py
COPY --chown=postbank:postbank backend/app ./backend/app
COPY --chown=postbank:postbank backend/migrations ./backend/migrations
COPY --chown=postbank:postbank alembic.ini ./alembic.ini

RUN mkdir -p /app/engine-cache \
    && chown -R postbank:postbank /app/engine-cache

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"]

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]

# Test-only image; test fixtures and developer tools never enter the runtime image.
FROM runtime AS test
COPY --chown=postbank:postbank backend/tests ./backend/tests
COPY --chown=postbank:postbank poc ./poc
CMD ["python", "-m", "unittest", "discover", "-s", "backend/tests", "-t", ".", "-v"]

# A plain docker build must also produce the application, never the test image.
FROM runtime AS production
