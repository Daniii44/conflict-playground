#!/bin/bash

set -euo pipefail

PLAYBOOK="${1:-default}"
CACHE_DIR="${CACHES:-${HOME}/caches}/repos"
PLAYBOOKS_DIR="${PLAYBOOKS:-${HOME}/playbooks}"

SYNCED_REPOS=""

usage() {
    echo "Usage: $0 [playbook-name|playbook-path]"
}

resolve_playbook_path() {
    local playbook="$1"

    if [[ -f "$playbook" ]]; then
        echo "$playbook"
        return
    fi

    if [[ "$playbook" == *.yaml || "$playbook" == *.yml ]]; then
        echo "${PLAYBOOKS_DIR}/${playbook}"
    else
        echo "${PLAYBOOKS_DIR}/${playbook}.yaml"
    fi
}

normalize_url_path() {
    python3 - "$1" <<'PY'
import posixpath
import sys
from urllib.parse import urlsplit, urlunsplit

url = sys.argv[1]
parts = urlsplit(url)
normalized_path = posixpath.normpath(parts.path)
if parts.path.endswith("/") and not normalized_path.endswith("/"):
    normalized_path += "/"
print(urlunsplit((parts.scheme, parts.netloc, normalized_path, parts.query, parts.fragment)))
PY
}

resolve_submodule_url() {
    local parent_url="$1"
    local submodule_url="$2"
    local parent_base

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

    parent_base="${parent_url%/}"
    parent_base="${parent_base%/*}"

    if [[ "$parent_base" =~ ^[a-zA-Z][a-zA-Z0-9+.-]*:// ]]; then
        normalize_url_path "${parent_base}/${submodule_url}"
    else
        echo "${parent_base}/${submodule_url}"
    fi
}

repo_cache_name() {
    local url="${1%/}"
    basename "$url"
}

is_synced() {
    local target_path="$1"

    case $'\n'"$SYNCED_REPOS"$'\n' in
        *$'\n'"$target_path"$'\n'*) return 0 ;;
        *) return 1 ;;
    esac
}

mark_synced() {
    local target_path="$1"

    SYNCED_REPOS="${SYNCED_REPOS}${target_path}"$'\n'
}

sync_repo() {
    local url="$1"
    local repo_name
    local target_path
    local existing_origin

    repo_name=$(repo_cache_name "$url")
    target_path="$CACHE_DIR/$repo_name"

    if is_synced "$target_path"; then
        return
    fi
    mark_synced "$target_path"

    if [[ -d "$target_path" ]]; then
        existing_origin=$(git -C "$target_path" config --get remote.origin.url || true)
        if [[ -n "$existing_origin" && "$existing_origin" != "$url" ]]; then
            echo "--> Warning: cache path $repo_name already points at $existing_origin, not $url" >&2
        fi

        echo "--> Syncing existing repo: $repo_name"
        git -C "$target_path" fetch --all --prune
    else
        echo "--> Loading new repo: $repo_name"
        git clone --bare "$url" "$target_path"
    fi

    sync_submodules "$target_path" "$url"
}

sync_submodules() {
    local repo_path="$1"
    local repo_url="$2"
    local blob
    local line
    local key
    local submodule_url
    local resolved_url

    while IFS= read -r blob; do
        [[ -n "$blob" ]] || continue

        while IFS= read -r line; do
            key="${line%% *}"
            submodule_url="${line#* }"
            [[ -n "${submodule_url:-}" ]] || continue

            resolved_url=$(resolve_submodule_url "$repo_url" "$submodule_url")
            echo "--> Found submodule: $resolved_url" >&2
            sync_repo "$resolved_url"
        done < <(git --git-dir="$repo_path" config --blob "$blob" --get-regexp '^submodule\..*\.url$' || true)
    done < <(git --git-dir="$repo_path" rev-list --objects --all -- .gitmodules | awk '$2 == ".gitmodules" { print $1 }' | sort -u)
}

if [[ $# -gt 1 ]]; then
    usage >&2
    exit 1
fi

CONFIG_FILE=$(resolve_playbook_path "$PLAYBOOK")

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "No such playbook: $CONFIG_FILE" >&2
    exit 1
fi

mkdir -p "$CACHE_DIR"

REPO_URLS=()
while IFS= read -r url; do
    REPO_URLS+=("$url")
done < <(yq -r '.playbook.sources[]?.repo_url // empty' "$CONFIG_FILE")

if [[ ${#REPO_URLS[@]} -eq 0 ]]; then
    echo "No explicit repositories found in playbook: $CONFIG_FILE" >&2
    echo "Dynamic playbooks cannot be repository-synced before Redis contains matching conflicts." >&2
    exit 1
fi

for url in "${REPO_URLS[@]}"; do
    [[ -n "$url" ]] || continue
    sync_repo "$url"
done

echo "Done syncing repository cache"
