#!/bin/bash

set -euo pipefail

if [ "$#" -gt 1 ]; then
    echo "Usage: info-sync [playbook]" >&2
    exit 1
fi

if [ "$#" -eq 1 ]; then
    repos=$(playbook-repos "$1")
else
    repos=$(
        find "${CACHES}/repos" -type f -name HEAD | while IFS= read -r head; do
            repo_dir=$(dirname "$head")
            if [ -d "${repo_dir}/objects" ]; then
                realpath -L --relative-to="${CACHES}/repos" "$repo_dir"
            fi
        done
    )
fi

for repo in $repos; do
    echo "Processing: $repo"
    info-conflict-sync --all-analysis "$repo"
done
