#!/bin/bash

# Arguments:
# repo name - name of the bare repository in the caches directory
# merge commit sha

# Only handle merge commits with two parents for now

if [ $# -ne 2 ]; then
    echo "Usage: $0 <repo-name> <merge-commit-sha>"
    exit 1
fi

REPO_NAME="$1"
MERGE_SHA="$2"

CACHES="${CACHES:-${HOME}/caches}"
BARE_REPO="${CACHES}/repos/${REPO_NAME}.git"
PLAYGROUND_NAME=$(playground-name-create $REPO_NAME $MERGE_SHA)
CLONE_PATH="${PLAYGROUNDS}/${PLAYGROUND_NAME}"

# Check if bare repo exists
if [[ ! -d "$BARE_REPO" ]]; then
    echo "Error: Bare repository $BARE_REPO does not exist"
    exit 1
fi

# Check if merge commit has exactly two parents
PARENTS=$(git --git-dir="$BARE_REPO" show -s --format=%P "$MERGE_SHA")
PARENT_COUNT=$(echo "$PARENTS" | wc -w)

if [[ $PARENT_COUNT -ne 2 ]]; then
    echo "Error: Only merge commits with exactly two parents are supported (found $PARENT_COUNT)"
    exit 1
fi

# Get the two parent SHAs
PARENTS=$(git --git-dir="$BARE_REPO" rev-list --parents -n 1 "$MERGE_SHA")
read -r MERGE_COMMIT FIRST_PARENT SECOND_PARENT <<< "$PARENTS"

# Determine which parent is main (usually the second parent in merge commits)
# and which is the feature branch
# Convention: second parent is typically main, first parent is feature
MAIN_PARENT="$SECOND_PARENT"
FEATURE_PARENT="$FIRST_PARENT"

# Create clone directory if it doesn't exist
mkdir -p "$PLAYGROUNDS"

# Remove existing clone if it exists
if [[ -d "$CLONE_PATH" ]]; then
    rm -rf "$CLONE_PATH"
fi

# Create a shared clone at the specified commit
mkdir -p $CLONE_PATH
cd $CLONE_PATH
git init &> /dev/null
#git clone --no-checkout --shared "$BARE_REPO" "$CLONE_PATH"

# Adjust .git/objects/info/alternates
ABS_PATH=$(realpath -L "$BARE_REPO/objects")
REL_PATH=$(realpath -L --relative-to="$CLONE_PATH/.git/objects" "$ABS_PATH")
SYMLINK_PATH="${REL_PATH/caches-bind-mount/caches}"
SYMLINK_PATH="${SYMLINK_PATH/caches-named-volume/caches}"
echo $SYMLINK_PATH > $CLONE_PATH/.git/objects/info/alternates

# Create local branches for main and feature
cd "$CLONE_PATH"

git checkout -b feature "$FEATURE_PARENT" &> /dev/null
git checkout -b main "$MAIN_PARENT" &> /dev/null
git merge feature &> /dev/null

echo $PLAYGROUND_NAME