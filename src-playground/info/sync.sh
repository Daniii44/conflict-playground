#!/bin/bash

for repo in $(ls -1 "${CACHES}/repos" | sed 's/\.[^.]*$//'); do
    echo "Processing: $repo"
    info-conflict-sync "$repo"
done