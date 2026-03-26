#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${API_DIR}/.." && pwd)"

CONDA_ENV_NAME="${CONDA_ENV_NAME:-esafe}"
HTTP_PORT="${HTTP_PORT:-8080}"
MAVEN_REPO_LOCAL="${MAVEN_REPO_LOCAL:-${PROJECT_ROOT}/.m2/repository}"
ADMIN_USERNAME="${RISK_ADMIN_USERNAME:-localadmin}"
ADMIN_PASSWORD="${RISK_ADMIN_PASSWORD:-LocalAdmin123}"
USER_USERNAME="${RISK_USER_USERNAME:-localuser}"
USER_PASSWORD="${RISK_USER_PASSWORD:-LocalUser123}"
BUILDING_SEED_PATH="${RISK_H2_DATA_SCRIPT_PATH:-${API_DIR}/.local-seed/data-h2.full.sql}"
FACILITY_SEED_PATH="${RISK_H2_FACILITY_HISTORY_SCRIPT_PATH:-${API_DIR}/.local-seed/data-h2-facility-history.full.sql}"

if ! command -v conda >/dev/null 2>&1; then
    echo "conda command not found. Install Miniconda/Anaconda first." >&2
    exit 1
fi

if [[ ! -f "${BUILDING_SEED_PATH}" ]]; then
    echo "Building seed not found: ${BUILDING_SEED_PATH}" >&2
    exit 1
fi

if [[ ! -f "${FACILITY_SEED_PATH}" ]]; then
    echo "Facility seed not found: ${FACILITY_SEED_PATH}" >&2
    exit 1
fi

BUILDING_SEED_URI="file://${BUILDING_SEED_PATH}"
FACILITY_SEED_URI="file://${FACILITY_SEED_PATH}"

exec conda run --no-capture-output -n "${CONDA_ENV_NAME}" mvn \
    -Dmaven.repo.local="${MAVEN_REPO_LOCAL}" \
    -Djetty.http.port="${HTTP_PORT}" \
    -Dspring.profiles.active=h2 \
    -Drisk.project.root="${PROJECT_ROOT}" \
    -Drisk.security.admin.username="${ADMIN_USERNAME}" \
    -Drisk.security.admin.password="${ADMIN_PASSWORD}" \
    -Drisk.security.user.username="${USER_USERNAME}" \
    -Drisk.security.user.password="${USER_PASSWORD}" \
    -Drisk.db.h2.data.script="${BUILDING_SEED_URI}" \
    -Drisk.db.h2.facility-history.script="${FACILITY_SEED_URI}" \
    org.eclipse.jetty:jetty-maven-plugin:9.4.53.v20231009:run
