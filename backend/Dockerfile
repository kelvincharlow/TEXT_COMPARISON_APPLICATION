FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POSTBANK_STORAGE_ROOT=/tmp/postbank-runtime \
    HOME=/tmp

WORKDIR /app

RUN apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 update \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 \
        install --yes --no-install-recommends libicu72 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 postbank \
    && useradd --uid 10001 --gid postbank --no-create-home --shell /usr/sbin/nologin postbank

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY --chown=postbank:postbank backend/__init__.py ./backend/__init__.py
COPY --chown=postbank:postbank backend/app ./backend/app
COPY --chown=postbank:postbank poc/__init__.py ./poc/__init__.py
COPY --chown=postbank:postbank poc/compare_documents.py ./poc/compare_documents.py

RUN mkdir -p /app/poc/.engine-cache \
    && chown -R postbank:postbank /app/poc/.engine-cache

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"]

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
