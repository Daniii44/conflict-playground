#!/bin/bash

set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: info-sync [playbook]" >&2
    exit 1
fi

repos=$(playbook-repos "$1")

for repo in $repos; do
    echo "Processing: $repo"
    info-conflict-sync --all-analysis "$repo"
done
