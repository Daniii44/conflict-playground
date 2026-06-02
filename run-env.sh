#!/bin/bash

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$PROJECT_DIR/config.yaml"

load_runtime_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "Error: Configuration file not found at $CONFIG_FILE"
        exit 1
    fi

    VOLUME_TYPE=$(grep '^volume_type:' "$CONFIG_FILE" | sed 's/volume_type:[[:space:]]*//;s/#.*//' | tr -d ' ')
    HOOK_TYPE=$(grep '^hook_type:' "$CONFIG_FILE" | sed 's/hook_type:[[:space:]]*//;s/#.*//' | tr -d ' ')
    SMARTGIT_BINARY=$(grep '^smartgit_binary:' "$CONFIG_FILE" | sed 's/smartgit_binary:[[:space:]]*//;s/#.*//;s/^[[:space:]]*//;s/[[:space:]]*$//')
    SMARTGIT_BINARY="${SMARTGIT_BINARY#[\"\']}"
    SMARTGIT_BINARY="${SMARTGIT_BINARY%[\"\']}"

    if [ -z "$VOLUME_TYPE" ] || [ -z "$HOOK_TYPE" ]; then
        echo "Error: Failed to parse configuration from $CONFIG_FILE"
        echo "Ensure volume_type, hook_type and optionally smartgit_binary are properly set."
        exit 1
    fi

    if [ "$VOLUME_TYPE" != "named-volume" ] && [ "$VOLUME_TYPE" != "bind-mount" ]; then
        echo "Error: Invalid volume type '$VOLUME_TYPE'"
        exit 1
    fi

    if [ "$HOOK_TYPE" != "manual-cli" ] && [ "$HOOK_TYPE" != "opencode" ]; then
        echo "Error: Invalid hook type '$HOOK_TYPE'"
        exit 1
    fi

    export VOLUME_TYPE
    export HOOK_TYPE
    export SMARTGIT_BINARY
}

load_playground_env() {
    load_runtime_config

    export PLAYGROUND_VERSION
    PLAYGROUND_VERSION=$(git -C "$PROJECT_DIR" describe --always --dirty)

    export LOGURU_FORMAT
    LOGURU_FORMAT="{time:HH:mm:ss.SSS} | <level>{level: <8}</level> | {message}"
}

playground_exec_command() {
    printf "docker exec -it"
    printf " -e %q" "LOGURU_FORMAT=$LOGURU_FORMAT"
    printf " -e %q" "PLAYGROUND_VERSION=$PLAYGROUND_VERSION"
    printf " -e %q" "VOLUME_TYPE=$VOLUME_TYPE"
    printf " -e %q" "HOOK_TYPE=$HOOK_TYPE"
    printf " %q" "conflict-playground" "bash" "src/entrypoint.sh"
}
