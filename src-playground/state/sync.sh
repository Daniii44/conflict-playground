#!/bin/bash
set -euo pipefail

state-redis-sync "$@"
state-clickhouse-sync "$@"
