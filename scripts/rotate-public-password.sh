#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

for required in .env scripts/rotate-public-password.py scripts/smoke.sh scripts/verify-tunnel.sh; do
  test -f "$required"
done
command -v openssl >/dev/null
command -v base64 >/dev/null

for container in esafe-api-live-1 esafe-api-demo-1; do
  health=$(docker inspect --format '{{.State.Health.Status}}' "$container" 2>/dev/null || true)
  if [ "$health" != "healthy" ]; then
    printf '%s\n' "$container 상태가 healthy가 아닙니다: ${health:-not-found}" >&2
    exit 1
  fi
done

old_password=$(sed -n 's/^ESAFE_PUBLIC_USER_PASSWORD=//p' .env)
test -n "$old_password"
if [ -n "${ESAFE_PUBLIC_PASSWORD_FILE:-}" ]; then
  test -f "$ESAFE_PUBLIC_PASSWORD_FILE"
  test "$(wc -l < "$ESAFE_PUBLIC_PASSWORD_FILE")" -le 1
  new_password=$(cat -- "$ESAFE_PUBLIC_PASSWORD_FILE")
  if [ "${#new_password}" -lt 10 ] || [ "${#new_password}" -gt 256 ]; then
    printf '%s\n' "Password length must be between 10 and 256 characters." >&2
    exit 1
  fi
else
  new_password=$(openssl rand -hex 20)
fi
helper_b64=$(base64 < scripts/rotate-public-password.py | tr -d '\n')

rotate_container() {
  target=$1
  password=$2
  printf '%s' "$password" | docker exec -i "$target" python -c \
    "import base64;exec(base64.b64decode('$helper_b64'))"
}

if ! rotate_container esafe-api-live-1 "$new_password"; then
  printf '%s\n' "LIVE 비밀번호 교체에 실패했습니다." >&2
  exit 1
fi
if ! rotate_container esafe-api-demo-1 "$new_password"; then
  rotate_container esafe-api-live-1 "$old_password" || true
  printf '%s\n' "DEMO 비밀번호 교체에 실패해 LIVE를 기존 값으로 복원했습니다." >&2
  exit 1
fi

temporary_env=$(mktemp "$ROOT/.env.rotate.XXXXXX")
case "$(realpath -m -- "$temporary_env")" in
  "$ROOT"/.env.rotate.*) ;;
  *)
    rotate_container esafe-api-live-1 "$old_password" || true
    rotate_container esafe-api-demo-1 "$old_password" || true
    printf '%s\n' "임시 환경파일 경계 검증에 실패했습니다." >&2
    exit 1
    ;;
esac

replaced=false
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    ESAFE_PUBLIC_USER_PASSWORD=*)
      printf 'ESAFE_PUBLIC_USER_PASSWORD=%s\n' "$new_password"
      replaced=true
      ;;
    *) printf '%s\n' "$line" ;;
  esac
done < .env > "$temporary_env"
if [ "$replaced" = false ]; then
  printf 'ESAFE_PUBLIC_USER_PASSWORD=%s\n' "$new_password" >> "$temporary_env"
fi
chmod 600 "$temporary_env"

if ! mv -f -- "$temporary_env" .env; then
  rotate_container esafe-api-live-1 "$old_password" || true
  rotate_container esafe-api-demo-1 "$old_password" || true
  rm -f -- "$temporary_env"
  printf '%s\n' ".env 갱신에 실패해 두 프로필을 기존 값으로 복원했습니다." >&2
  exit 1
fi

unset new_password old_password
./scripts/smoke.sh
./scripts/verify-tunnel.sh >/dev/null
printf '%s\n' "공용 로그인 비밀번호 교체와 기존 세션 폐기를 완료했습니다."
printf '%s\n' "새 값은 .env의 ESAFE_PUBLIC_USER_PASSWORD에서만 확인하세요."
