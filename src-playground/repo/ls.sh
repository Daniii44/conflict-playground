#!/bin/bash

find "${CACHES}/repos" -type f -name HEAD | while IFS= read -r head; do
    repo_dir=$(dirname "$head")
    if [ -d "${repo_dir}/objects" ]; then
        realpath -L --relative-to="${CACHES}/repos" "$repo_dir"
    fi
done | sort
