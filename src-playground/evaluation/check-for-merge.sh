#!/bin/bash

# Test if the hook even merged the two branches

if [ $# -ne 1 ]; then
    echo "Usage: $0 <playground-name>"
    exit 1
fi

PLAYGROUND_NAME=$1
PLAYGROUND_PATH="$PLAYGROUNDS/$PLAYGROUND_NAME"
MERGE_SHA=$(playground-name-extract-merge-sha "$PLAYGROUND_NAME")

if [ ! -d "$PLAYGROUND_PATH/.git" ]; then
    echo "Error: $PLAYGROUND_PATH is not a git repository."
    exit 1
fi

# Get the parents of the sample solution merge commit
PARENTS=$(git -C "$PLAYGROUND_PATH" rev-list --parents -n 1 "$MERGE_SHA" | cut -d' ' -f2-)

# Check if each parent is reachable from HEAD
for PARENT in $PARENTS; do
    if ! git -C "$PLAYGROUND_PATH" merge-base --is-ancestor "$PARENT" HEAD; then
        echo "Parent commit $PARENT is not reachable from HEAD."
        exit 1
    fi
done

echo "All parent commits of the sample solution merge are reachable from HEAD."
exit 0