#!/bin/bash

# info-dirty-merges-sha <git-repo-name> <index>

set -e

if [ $# -ne 2 ]; then
    echo "Usage: $0 <git-repo-name> <index>"
    exit 1
fi

GIT_REPO_NAME="$1"
INDEX="$2"
LINE_NUM=$((INDEX + 1))

sed -n "${LINE_NUM}p" "$CACHES/info/dirty-merges/${GIT_REPO_NAME}.txt"