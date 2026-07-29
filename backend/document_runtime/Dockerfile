FROM mcr.microsoft.com/playwright:v1.58.2-noble AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    PATH=/opt/esafe/bin:${PATH}

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        fonts-noto-cjk \
        python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 esafe \
    && useradd \
        --uid 10001 \
        --gid 10001 \
        --create-home \
        --shell /usr/sbin/nologin \
        esafe \
    && python3 -m venv /opt/esafe

COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m pip install --requirement /tmp/requirements.txt

COPY backend/document_runtime/package.json backend/document_runtime/package-lock.json \
    /app/document_runtime/
RUN cd /app/document_runtime \
    && npm ci --omit=dev --ignore-scripts \
    && npm cache clean --force

COPY --chown=esafe:esafe backend/app /app/app
COPY --chown=esafe:esafe backend/alembic /app/alembic
COPY --chown=esafe:esafe backend/alembic.ini /app/alembic.ini
COPY --chown=esafe:esafe backend/document_runtime/render_pdf.mjs \
    /app/document_runtime/render_pdf.mjs

ARG ESAFE_BUILD_COMMIT=unknown
ENV ESAFE_BUILD_COMMIT=${ESAFE_BUILD_COMMIT}

USER 10001:10001

CMD ["celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=INFO"]
