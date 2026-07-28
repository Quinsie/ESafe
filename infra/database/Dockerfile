FROM postgis/postgis:16-3.5

ARG PGVECTOR_VERSION=0.8.1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        postgresql-server-dev-16 \
    && git clone --branch "v${PGVECTOR_VERSION}" --depth 1 \
        https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && make -C /tmp/pgvector \
    && make -C /tmp/pgvector install \
    && apt-get purge --yes --auto-remove build-essential git postgresql-server-dev-16 \
    && rm -rf /var/lib/apt/lists/* /tmp/pgvector

COPY infra/database/init-extensions.sql /docker-entrypoint-initdb.d/00-extensions.sql
