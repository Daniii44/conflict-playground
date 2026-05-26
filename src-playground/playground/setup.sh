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
REPO_CACHE_DIR="${CACHES}/repos"
BARE_REPO="${CACHES}/repos/${REPO_NAME}"
PLAYGROUND_NAME=$(playground-name-create $REPO_NAME $MERGE_SHA)
CLONE_PATH="${PLAYGROUNDS}/${PLAYGROUND_NAME}"

resolve_submodule_url() {
    local parent_url="$1"
    local submodule_url="$2"

    if [[ "$submodule_url" =~ ^[a-zA-Z][a-zA-Z0-9+.-]*:// ]] ||
        [[ "$submodule_url" =~ ^[^/]+@[^:]+: ]] ||
        [[ "$submodule_url" == /* ]]; then
        echo "$submodule_url"
        return
    fi

    if [[ "$submodule_url" != ./* && "$submodule_url" != ../* ]]; then
        echo "$submodule_url"
        return
    fi

    python3 - "$parent_url" "$submodule_url" <<'PY'
import posixpath
import sys
from urllib.parse import urlsplit, urlunsplit

parent_url = sys.argv[1].rstrip("/")
submodule_url = sys.argv[2]

parts = urlsplit(parent_url)
if parts.scheme or parts.netloc:
    normalized_path = posixpath.normpath(f"{parts.path}/{submodule_url}")
    print(urlunsplit((parts.scheme, parts.netloc, normalized_path, parts.query, parts.fragment)))
elif ":" in parent_url and "/" not in parent_url.split(":", 1)[0]:
    prefix, path = parent_url.split(":", 1)
    print(f"{prefix}:{posixpath.normpath(f'{path}/{submodule_url}')}")
else:
    print(posixpath.normpath(f"{parent_url}/{submodule_url}"))
PY
}

repo_cache_key() {
    python3 - "$1" <<'PY'
import sys
from pathlib import Path
from urllib.parse import urlsplit

url = sys.argv[1]
parsed = urlsplit(url)
if parsed.scheme or parsed.netloc:
    path = parsed.path
elif ":" in url and "/" not in url.split(":", 1)[0]:
    path = url.split(":", 1)[1]
else:
    path = url

parts = [part for part in path.split("/") if part and part not in {".", ".."}]
if not parts:
    repo_name = Path(url.rstrip("/")).name
    print(repo_name if repo_name.endswith(".git") else f"{repo_name}.git")
else:
    if not parts[-1].endswith(".git"):
        parts[-1] = f"{parts[-1]}.git"
    print("/".join(parts))
PY
}

find_cached_repo() {
    local url="$1"
    local repo_key
    local cache_path

    repo_key=$(repo_cache_key "$url")
    cache_path="${REPO_CACHE_DIR}/${repo_key}"

    if [[ -d "$cache_path" ]]; then
        echo "$cache_path"
        return
    fi
}

init_submodules_with_alternates() {
    local repo_path="$1"
    local parent_url="$2"
    local depth="${3:-0}"
    local gitmodules_path="${repo_path}/.gitmodules"
    local line
    local key
    local submodule_name
    local submodule_path
    local submodule_url
    local resolved_url
    local cache_repo
    local gitlink_sha

    if (( depth > 20 )); then
        echo "--> Skipping deeply nested submodules below $repo_path" >&2
        return
    fi

    if [[ ! -f "$gitmodules_path" ]]; then
        return
    fi

    if ! git config -f "$gitmodules_path" --get-regexp '^submodule\..*\.path$' &> /dev/null; then
        echo "--> Skipping submodule setup for $repo_path because .gitmodules is not parseable" >&2
        return
    fi

    while IFS= read -r line; do
        key="${line%% *}"
        submodule_path="${line#* }"
        submodule_name="${key#submodule.}"
        submodule_name="${submodule_name%.path}"
        submodule_url=$(git config -f "$gitmodules_path" --get "submodule.${submodule_name}.url" || true)

        if [[ -z "$submodule_url" ]]; then
            echo "--> Skipping submodule without URL: $submodule_path" >&2
            continue
        fi

        resolved_url=$(resolve_submodule_url "$parent_url" "$submodule_url")
        cache_repo=$(find_cached_repo "$resolved_url")

        if [[ -z "$cache_repo" ]]; then
            echo "--> Skipping uncached submodule: $submodule_path ($resolved_url)" >&2
            continue
        fi

        gitlink_sha=$(git -C "$repo_path" ls-files -s -- "$submodule_path" |
            awk '$1 == "160000" && $3 == "0" { print $2 }')

        if [[ -z "$gitlink_sha" ]]; then
            echo "--> Leaving unresolved submodule conflict untouched: $submodule_path" >&2
            continue
        fi

        echo "--> Initializing submodule from cache: $submodule_path" >&2
        git -C "$repo_path" config "submodule.${submodule_name}.url" "$cache_repo"

        if git -C "$repo_path" \
            -c protocol.file.allow=always \
            submodule update --init --reference "$cache_repo" -- "$submodule_path" >&2; then
            if git -C "${repo_path}/${submodule_path}" rev-parse --is-inside-work-tree &> /dev/null; then
                git -C "${repo_path}/${submodule_path}" remote set-url origin "$resolved_url" &> /dev/null || true
                init_submodules_with_alternates "${repo_path}/${submodule_path}" "$resolved_url" "$((depth + 1))"
            fi
        else
            echo "--> Failed to initialize submodule from cache: $submodule_path" >&2
        fi
    done < <(git config -f "$gitmodules_path" --get-regexp '^submodule\..*\.path$')
}

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
mkdir -p "$CLONE_PATH"
cd "$CLONE_PATH"
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

SUPERPROJECT_URL=$(git -C "$BARE_REPO" config --get remote.origin.url || true)
if [[ -n "$SUPERPROJECT_URL" ]]; then
    init_submodules_with_alternates "$CLONE_PATH" "$SUPERPROJECT_URL"
else
    echo "--> Skipping submodule setup because cached repo has no origin URL: $BARE_REPO" >&2
fi

echo $PLAYGROUND_NAME
