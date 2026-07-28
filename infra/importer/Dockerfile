FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --gid 10001 esafe \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin esafe

COPY importer/requirements.txt /tmp/requirements.txt
RUN python -m pip install --requirement /tmp/requirements.txt

COPY --chown=esafe:esafe importer/esafe_importer /app/esafe_importer
USER 10001:10001
ENTRYPOINT ["python", "-m", "esafe_importer"]

FROM runtime AS test
USER root
COPY importer/requirements-dev.txt /tmp/requirements-dev.txt
RUN python -m pip install --requirement /tmp/requirements-dev.txt
COPY importer/pyproject.toml /app/pyproject.toml
COPY importer/tests /app/tests
RUN ruff check esafe_importer tests && mypy esafe_importer && pytest
