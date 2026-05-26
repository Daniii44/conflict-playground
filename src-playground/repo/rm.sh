#!/bin/bash

# Usage: rm.sh <repo-name>
# Removes the bare repository for the given repo name from the caches directory.

if [ $# -ne 1 ]; then
    echo "Usage: $0 <repo-name>"
    exit 1
fi

REPO_NAME="$1"
CACHES="${CACHES:-${HOME}/caches}"
REPO_PATH="${CACHES}/repos/${REPO_NAME}"

if [[ -z "$REPO_NAME" ]]; then
    echo "Error: Repository name must not be empty."
    exit 1
fi

if [[ ! -d "$REPO_PATH" ]]; then
    echo "Error: Repository $REPO_PATH does not exist."
    exit 1
fi

echo "Removing repository at $REPO_PATH..."
rm -rf "$REPO_PATH"

echo "Removing all playground shared clones in $PLAYGROUNDS..."
rm -rf "$PLAYGROUNDS"/${REPO_NAME}-*
