#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$SCRIPT_DIR"

CLICKHOUSE_IMAGE="${CLICKHOUSE_IMAGE:-clickhouse/clickhouse-server:latest}"
CLICKHOUSE_USER="${CLICKHOUSE_USER:-default}"
CLICKHOUSE_PASSWORD="${CLICKHOUSE_PASSWORD:-dev-dynha9-fenvYc-daqmeh}"
CLICKHOUSE_DB="${CLICKHOUSE_DB:-default}"

NETWORK_NAME="${NETWORK_NAME:-clickhouse-schema-check-$$}"
CLICKHOUSE_CONTAINER="${CLICKHOUSE_CONTAINER:-clickhouse-schema-check-clickhouse-$$}"
HOST_PORT="${HOST_PORT:-}"

cleanup() {
    docker rm -f "$CLICKHOUSE_CONTAINER" >/dev/null 2>&1 || true
    docker network rm "$NETWORK_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_for_clickhouse() {
    echo "[INFO] Waiting for ClickHouse native client readiness"
    for _ in $(seq 1 60); do
        if docker exec "$CLICKHOUSE_CONTAINER" \
            clickhouse-client \
            --user "$CLICKHOUSE_USER" \
            --password "$CLICKHOUSE_PASSWORD" \
            --query "SELECT 1" >/dev/null 2>&1; then
            return
        fi
        sleep 1
    done

    echo "[ERROR] ClickHouse did not become ready in time" >&2
    exit 1
}

resolve_host_port() {
    HOST_PORT="$(docker port "$CLICKHOUSE_CONTAINER" 8123/tcp | sed 's/.*://')"
    if [ -z "$HOST_PORT" ]; then
        echo "[ERROR] Could not resolve published ClickHouse HTTP port" >&2
        exit 1
    fi
}

wait_for_clickhouse_http() {
    echo "[INFO] Waiting for ClickHouse HTTP readiness on 127.0.0.1:$HOST_PORT"
    for _ in $(seq 1 60); do
        if curl --silent --show-error --fail \
            --user "$CLICKHOUSE_USER:$CLICKHOUSE_PASSWORD" \
            "http://127.0.0.1:$HOST_PORT/?query=SELECT%201" >/dev/null 2>&1; then
            return
        fi
        sleep 1
    done

    echo "[ERROR] ClickHouse HTTP endpoint did not become ready in time" >&2
    exit 1
}

echo "[INFO] Creating temporary Docker network $NETWORK_NAME"
docker network create "$NETWORK_NAME" >/dev/null

echo "[INFO] Starting temporary ClickHouse container $CLICKHOUSE_CONTAINER"
docker run -d --rm \
    --name "$CLICKHOUSE_CONTAINER" \
    --network "$NETWORK_NAME" \
    --network-alias clickhouse \
    -p "127.0.0.1::8123" \
    -e CLICKHOUSE_DB="$CLICKHOUSE_DB" \
    -e CLICKHOUSE_USER="$CLICKHOUSE_USER" \
    -e CLICKHOUSE_PASSWORD="$CLICKHOUSE_PASSWORD" \
    "$CLICKHOUSE_IMAGE" >/dev/null

wait_for_clickhouse
resolve_host_port
wait_for_clickhouse_http

echo "[INFO] Running state/clickhouse/ensure.py against http://127.0.0.1:$HOST_PORT"
PYTHONPATH="$ROOT_DIR/src-playground" \
CLICKHOUSE_URL="http://127.0.0.1:$HOST_PORT" \
CLICKHOUSE_DB="$CLICKHOUSE_DB" \
CLICKHOUSE_USER="$CLICKHOUSE_USER" \
CLICKHOUSE_PASSWORD="$CLICKHOUSE_PASSWORD" \
python3 "$ROOT_DIR/src-playground/state/clickhouse/ensure.py"

echo "[INFO] ClickHouse schema ensure completed successfully"
