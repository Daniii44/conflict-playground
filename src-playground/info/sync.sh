#!/bin/bash

set -euo pipefail

if [ "$#" -gt 1 ]; then
    echo "Usage: info-sync [playbook]" >&2
    exit 1
fi

if [ "$#" -eq 1 ]; then
    repos=$(playbook-repos "$1")
else
    repos=$(find "${CACHES}/repos" -mindepth 1 -maxdepth 1 -type d -name "*.git" -exec basename {} .git \;)
fi

for repo in $repos; do
    echo "Processing: $repo"
    info-conflict-sync "$repo"
done