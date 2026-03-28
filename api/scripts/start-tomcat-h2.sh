#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${API_DIR}/.." && pwd)"
SPRING_DIR="${API_DIR}/src/main/resources/egovframework/spring"

CATALINA_HOME_DEFAULT="/opt/homebrew/Cellar/tomcat@8/8.5.100/libexec"
JAVA_HOME_DEFAULT="/opt/homebrew/Cellar/openjdk@11/11.0.30/libexec/openjdk.jdk/Contents/Home"

TOMCAT_HOME="${CATALINA_HOME:-${CATALINA_HOME_DEFAULT}}"
TOMCAT_BASE="${CATALINA_BASE:-${API_DIR}/.tomcat-base-h2}"
JAVA_HOME_VALUE="${JAVA_HOME:-${JAVA_HOME_DEFAULT}}"
HTTP_PORT=18080
SKIP_BUILD=false
REQUIRE_ALERT_ZONE_FILE=false

ADMIN_USERNAME="${RISK_ADMIN_USERNAME:-localadmin}"
ADMIN_PASSWORD="${RISK_ADMIN_PASSWORD:-LocalAdmin123}"
USER_USERNAME="${RISK_USER_USERNAME:-localuser}"
USER_PASSWORD="${RISK_USER_PASSWORD:-LocalUser123}"
KMA_AUTH_KEY_VALUE="${KMA_AUTH_KEY:-FtRxuKuhQneUcbirodJ3ng}"
ALERT_ZONE_FILE_VALUE="${RISK_ALERT_ZONE_FILE:-}"

if [[ -n "${MAVEN_HOME:-}" ]]; then
    MAVEN_CMD="${MAVEN_HOME}/bin/mvn"
elif [[ -n "${M2_HOME:-}" ]]; then
    MAVEN_CMD="${M2_HOME}/bin/mvn"
elif command -v mvn >/dev/null 2>&1; then
    MAVEN_CMD="$(command -v mvn)"
else
    MAVEN_CMD="/opt/homebrew/bin/mvn"
fi

usage() {
    cat <<'EOF'
Usage: ./scripts/start-tomcat-h2.sh [options]

Options:
  --tomcat-home <path>
  --tomcat-base <path>
  --java-home <path>
  --maven-cmd <path>
  --http-port <port>
  --alert-zone-file <path>
  --require-alert-zone-file
  --skip-build
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tomcat-home)
            TOMCAT_HOME="$2"
            shift 2
            ;;
        --tomcat-base)
            TOMCAT_BASE="$2"
            shift 2
            ;;
        --java-home)
            JAVA_HOME_VALUE="$2"
            shift 2
            ;;
        --maven-cmd)
            MAVEN_CMD="$2"
            shift 2
            ;;
        --http-port)
            HTTP_PORT="$2"
            shift 2
            ;;
        --alert-zone-file)
            ALERT_ZONE_FILE_VALUE="$2"
            shift 2
            ;;
        --require-alert-zone-file)
            REQUIRE_ALERT_ZONE_FILE=true
            shift
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

SERVER_XML="${TOMCAT_BASE}/conf/server.xml"
WAR_SRC="${API_DIR}/target/risk-api-1.0.0.war"
WAR_DST="${TOMCAT_BASE}/webapps/ROOT.war"
WEB_ROOT_DIR="${TOMCAT_BASE}/webapps/ROOT"
SHUTDOWN_SH="${TOMCAT_HOME}/bin/shutdown.sh"
CATALINA_SH="${TOMCAT_HOME}/bin/catalina.sh"
SETENV_SH="${TOMCAT_BASE}/bin/setenv.sh"
LOCAL_SEED_DIR="${API_DIR}/.local-seed"
LOCAL_BUILDING_SEED="${LOCAL_SEED_DIR}/data-h2.full.sql"
LOCAL_FACILITY_SEED="${LOCAL_SEED_DIR}/data-h2-facility-history.full.sql"
ACTIVE_DB_FILE="${SPRING_DIR}/risk-db.properties"
H2_DB_FILE="${SPRING_DIR}/risk-db-h2.properties"

[[ -d "${TOMCAT_HOME}" ]] || { echo "Tomcat not found: ${TOMCAT_HOME}" >&2; exit 1; }
[[ -d "${TOMCAT_BASE}" ]] || { echo "Tomcat base not found: ${TOMCAT_BASE}" >&2; exit 1; }
[[ -d "${JAVA_HOME_VALUE}" ]] || { echo "JAVA_HOME not found: ${JAVA_HOME_VALUE}" >&2; exit 1; }
[[ -f "${MAVEN_CMD}" || "${MAVEN_CMD}" == "mvn" ]] || { echo "Maven not found: ${MAVEN_CMD}" >&2; exit 1; }
[[ -f "${SERVER_XML}" ]] || { echo "server.xml not found: ${SERVER_XML}" >&2; exit 1; }
[[ -f "${H2_DB_FILE}" ]] || { echo "Profile file not found: ${H2_DB_FILE}" >&2; exit 1; }

export JAVA_HOME="${JAVA_HOME_VALUE}"
export PATH="${JAVA_HOME}/bin:${PATH}"
export RISK_PROJECT_ROOT="${PROJECT_ROOT}"

if [[ -n "${KMA_AUTH_KEY_VALUE// }" ]]; then
    export KMA_AUTH_KEY="${KMA_AUTH_KEY_VALUE}"
else
    echo "Warning: KMA_AUTH_KEY is empty. Weather refresh API may fail in H2 runtime." >&2
    unset KMA_AUTH_KEY || true
fi

if [[ -n "${ALERT_ZONE_FILE_VALUE// }" ]]; then
    [[ -f "${ALERT_ZONE_FILE_VALUE}" ]] || { echo "Alert zone mapping file not found: ${ALERT_ZONE_FILE_VALUE}" >&2; exit 1; }
    export RISK_ALERT_ZONE_FILE="$(cd "$(dirname "${ALERT_ZONE_FILE_VALUE}")" && pwd)/$(basename "${ALERT_ZONE_FILE_VALUE}")"
    echo "Using alert zone file: ${RISK_ALERT_ZONE_FILE}"
elif [[ "${REQUIRE_ALERT_ZONE_FILE}" == "true" ]]; then
    echo "Alert zone mapping file is required in strict mode." >&2
    exit 1
else
    unset RISK_ALERT_ZONE_FILE || true
    echo "Alert zone file not set. Using classpath fallback (egovframework/spring/alert-zones.csv)."
fi

if [[ -f "${LOCAL_BUILDING_SEED}" ]]; then
    export RISK_H2_DATA_SCRIPT="file:${LOCAL_BUILDING_SEED}"
    echo "Using local full H2 building seed: ${LOCAL_BUILDING_SEED}"
else
    unset RISK_H2_DATA_SCRIPT || true
fi

if [[ -f "${LOCAL_FACILITY_SEED}" ]]; then
    export RISK_H2_FACILITY_HISTORY_SCRIPT="file:${LOCAL_FACILITY_SEED}"
    echo "Using local full H2 facility seed: ${LOCAL_FACILITY_SEED}"
else
    unset RISK_H2_FACILITY_HISTORY_SCRIPT || true
fi

echo "[0/6] Configure Tomcat setenv.sh"
cat > "${SETENV_SH}" <<EOF
#!/bin/sh

PROJECT_ROOT="${PROJECT_ROOT}"

export JAVA_HOME="${JAVA_HOME_VALUE}"
export RISK_PROJECT_ROOT="\${PROJECT_ROOT}"
export CATALINA_PID="${TOMCAT_BASE}/temp/tomcat.pid"
EOF

if [[ -n "${KMA_AUTH_KEY:-}" ]]; then
    cat >> "${SETENV_SH}" <<EOF
export KMA_AUTH_KEY="${KMA_AUTH_KEY}"
EOF
fi

cat >> "${SETENV_SH}" <<EOF

CATALINA_OPTS="\$CATALINA_OPTS -Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8"
CATALINA_OPTS="\$CATALINA_OPTS -Dspring.profiles.active=h2"
CATALINA_OPTS="\$CATALINA_OPTS -Drisk.security.admin.username=${ADMIN_USERNAME}"
CATALINA_OPTS="\$CATALINA_OPTS -Drisk.security.admin.password=${ADMIN_PASSWORD}"
CATALINA_OPTS="\$CATALINA_OPTS -Drisk.security.user.username=${USER_USERNAME}"
CATALINA_OPTS="\$CATALINA_OPTS -Drisk.security.user.password=${USER_PASSWORD}"
CATALINA_OPTS="\$CATALINA_OPTS -Drisk.project.root=\${PROJECT_ROOT}"
EOF

if [[ -n "${KMA_AUTH_KEY:-}" ]]; then
    cat >> "${SETENV_SH}" <<'EOF'
CATALINA_OPTS="$CATALINA_OPTS -Dkma.auth.key=$KMA_AUTH_KEY"
EOF
fi

if [[ -n "${RISK_ALERT_ZONE_FILE:-}" ]]; then
    cat >> "${SETENV_SH}" <<EOF
CATALINA_OPTS="\$CATALINA_OPTS -Drisk.weather.alert.zone.file=${RISK_ALERT_ZONE_FILE}"
EOF
fi

if [[ -n "${RISK_H2_DATA_SCRIPT:-}" ]]; then
    cat >> "${SETENV_SH}" <<EOF
CATALINA_OPTS="\$CATALINA_OPTS -Drisk.db.h2.data.script=${RISK_H2_DATA_SCRIPT}"
EOF
fi

if [[ -n "${RISK_H2_FACILITY_HISTORY_SCRIPT:-}" ]]; then
    cat >> "${SETENV_SH}" <<EOF
CATALINA_OPTS="\$CATALINA_OPTS -Drisk.db.h2.facility-history.script=${RISK_H2_FACILITY_HISTORY_SCRIPT}"
EOF
fi

cat >> "${SETENV_SH}" <<'EOF'

export CATALINA_OPTS
EOF

chmod +x "${SETENV_SH}"

echo "[1/6] Switch DB profile -> h2"
cp "${H2_DB_FILE}" "${ACTIVE_DB_FILE}"
echo "Switched DB profile to 'h2'"
echo "Active file: ${ACTIVE_DB_FILE}"

echo "[2/6] Configure Tomcat HTTP port -> ${HTTP_PORT}"
perl -0pi -e 's/Connector port="\d+" protocol="HTTP\/1\.1"/Connector port="'"${HTTP_PORT}"'" protocol="HTTP\/1.1"/' "${SERVER_XML}"
perl -0pi -e 's/(Connector port="'"${HTTP_PORT}"'" protocol="HTTP\/1\.1")(?![^>]*URIEncoding=)/$1 URIEncoding="UTF-8" useBodyEncodingForURI="true"/' "${SERVER_XML}"

if [[ "${SKIP_BUILD}" != "true" ]]; then
    echo "[3/6] Build WAR"
    export MAVEN_OPTS="-Dmaven.wagon.http.ssl.insecure=true -Dmaven.wagon.http.ssl.allowall=true -Dmaven.wagon.http.ssl.ignore.validity.dates=true"
    (
        cd "${API_DIR}"
        "${MAVEN_CMD}" -q -DskipTests package
    )
else
    echo "[3/6] Build WAR (skip)"
fi

[[ -f "${WAR_SRC}" ]] || { echo "WAR not found after build: ${WAR_SRC}" >&2; exit 1; }

echo "[4/6] Stop Tomcat (if running)"
export CATALINA_HOME="${TOMCAT_HOME}"
export CATALINA_BASE="${TOMCAT_BASE}"
"${SHUTDOWN_SH}" >/dev/null 2>&1 || true
sleep 3

echo "[5/6] Deploy ROOT.war"
rm -rf "${WEB_ROOT_DIR}"
rm -f "${WAR_DST}"
cp "${WAR_SRC}" "${WAR_DST}"

echo "[6/6] Start Tomcat"
"${CATALINA_SH}" start

echo "Waiting for startup..."
for _ in $(seq 1 120); do
    if curl -fsS "http://127.0.0.1:${HTTP_PORT}/login.do" >/dev/null 2>&1; then
        echo
        echo "Tomcat started: http://localhost:${HTTP_PORT}/"
        echo "Dashboard: http://localhost:${HTTP_PORT}/riskDashboard.do"
        echo "Nationwide map: http://localhost:${HTTP_PORT}/riskNationwideRiskMap.do"
        echo "Login (admin): ${ADMIN_USERNAME} / ${ADMIN_PASSWORD}"
        echo "Login (user):  ${USER_USERNAME} / ${USER_PASSWORD}"
        exit 0
    fi
    sleep 1
done

echo "Tomcat did not become ready within 120 seconds." >&2
echo "Check logs under: ${TOMCAT_BASE}/logs" >&2
exit 1
