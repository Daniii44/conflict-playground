#!/bin/bash

# info-dirty-merges-count <git-repo-name>

set -e

if [ $# -ne 1 ]; then
    echo "Usage: $0 <git-repo-name>"
    exit 1
fi

GIT_REPO_NAME="$1"

wc -l < "$CACHES/info/dirty-merges/${GIT_REPO_NAME}.txt"