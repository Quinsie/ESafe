FROM python:3.12-slim-bookworm AS runtime


ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --gid 10001 esafe \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin esafe

COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m pip install --requirement /tmp/requirements.txt

COPY --chown=esafe:esafe backend/app /app/app
COPY --chown=esafe:esafe backend/alembic /app/alembic
COPY --chown=esafe:esafe backend/alembic.ini /app/alembic.ini

ARG ESAFE_BUILD_COMMIT=unknown
ENV ESAFE_BUILD_COMMIT=${ESAFE_BUILD_COMMIT}

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=4 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]

FROM runtime AS test

USER root
COPY backend/requirements-dev.txt /tmp/requirements-dev.txt
RUN python -m pip install --requirement /tmp/requirements-dev.txt
COPY backend/pyproject.toml /app/pyproject.toml
COPY backend/tests /app/tests
RUN ruff check app alembic tests && mypy app alembic && pytest
