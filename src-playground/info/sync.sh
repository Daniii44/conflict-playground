#!/bin/bash

for repo in $(ls -1 "${CACHES}/repos" | sed 's/\.[^.]*$//'); do
    echo "Processing: $repo"
    info-dirty-merges-sync "$repo"
done