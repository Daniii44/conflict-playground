#!/bin/bash

if [ $# -ne 2 ]; then
    echo "Usage: $0 <repo-name> <merge-commit-sha>"
    exit 1
fi

REPO_NAME="$1"
MERGE_SHA="$2"

echo "${REPO_NAME}-${MERGE_SHA}"