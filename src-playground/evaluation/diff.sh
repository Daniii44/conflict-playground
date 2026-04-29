#!/bin/bash

# Compare the merge with the actual resolution

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

# Print the diff between the sample merge solution and the actual merge solution
ACTUAL_MERGE_SHA=$(git -C "$PLAYGROUND_PATH" rev-parse HEAD)

diff_output=$(git -C "$PLAYGROUND_PATH" diff "$MERGE_SHA" "$ACTUAL_MERGE_SHA")

if [ -z "$diff_output" ]; then
    echo "No difference to sample solution found (Conflict Resolution sucessful)"
    exit 0
else
    echo "$diff_output"
    exit 1
fi