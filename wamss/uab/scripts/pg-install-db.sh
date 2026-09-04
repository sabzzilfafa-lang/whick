#!/usr/bin/env bash
# CC install 스크립트용 PostgreSQL 헬퍼
# Usage: source "$(dirname "$0")/pg-install-db.sh"
set -euo pipefail

CC_DB_CONTAINER="${CC_DB_CONTAINER:-whick-cc-db}"
CC_DB_USER="${CC_DB_USER:-cc_app}"
CC_DB_PASSWORD="${CC_DB_PASSWORD:-whick_cc_dev_pass}"
CC_PG_DATABASE="${CC_PG_DATABASE:-whick_control}"

_pg_psql() {
  docker exec -e PGPASSWORD="$CC_DB_PASSWORD" "$CC_DB_CONTAINER" \
    psql -U "$CC_DB_USER" -d "$CC_PG_DATABASE" -v ON_ERROR_STOP=1 "$@"
}

pg_ops_row() {
  _pg_psql -q -t -A -F $'\t' -c "$1"
}

pg_core_row() {
  _pg_psql -q -t -A -F $'\t' -c "$1"
}

pg_ops_query() {
  _pg_psql -c "$1"
}

pg_core_query() {
  _pg_psql -c "$1"
}

pg_ops_exec() {
  _pg_psql -q -c "$1"
}

pg_core_exec() {
  _pg_psql -q -c "$1"
}
