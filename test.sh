#!/usr/bin/env bash
set -euo pipefail

docker compose build conflict-playground
docker run --rm \
  -e PYTHONPATH=/root/src \
  --entrypoint pytest \
  "conflict-playground:playground"