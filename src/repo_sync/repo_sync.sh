#!/bin/bash

CONFIG_FILE="${HOME}/playgrounds/default.yaml"
CACHE_DIR="${HOME}/caches/repos"

mkdir -p "$CACHE_DIR"

yq -r '.playground.sources[].repo_url' "$CONFIG_FILE" | while IFS= read -r url; do
    repo_name=$(basename "$url")
    target_path="$CACHE_DIR/$repo_name"

    if [ -d "$target_path" ]; then
        echo "--> Syncing existing repo: $repo_name"
        git -C "$target_path" fetch --all
    else
        echo "--> Loading new repo: $repo_name"
        git clone --bare "$url" "$target_path"
    fi
done

echo "Done syncing repository cache"