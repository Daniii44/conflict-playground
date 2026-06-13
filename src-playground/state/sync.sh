#!/bin/bash
set -euo pipefail

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    cat <<'EOF'
usage: state-sync [-h] <save|playbook> [<save|playbook> ...]

Restore Redis saves, then sync ClickHouse.

positional arguments:
  save|playbook  Exact Redis save name, or playbook name using semantic saves

options:
  -h, --help     Show this help message and exit

Semantic playbook saves use: <playbook>-<type>-v<major>[.<minor>]
When given a playbook name, state-redis-sync loads the highest major version
and the highest minor version per data type within that major.
EOF
    exit 0
fi

state-redis-sync "$@"
state-clickhouse-sync "$@"
