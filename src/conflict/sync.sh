#!/bin/bash

for repo in $(ls -1 "${CACHES}/repos" | sed 's/\.[^.]*$//'); do
    echo "Processing: $repo"
    conflict-collect-dirty-merges "$repo"
done