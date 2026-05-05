#!/bin/bash

# Read configuration from config.yaml
CONFIG_FILE="$(dirname "$0")/config.yaml"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file not found at $CONFIG_FILE"
    exit 1
fi

# Parse YAML configuration
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

if [ "$HOOK_TYPE" != "manual-cli" ] && [ "$HOOK_TYPE" != "manual-smartgit" ]; then
    echo "Error: Invalid hook type '$HOOK_TYPE'"
    exit 1
fi

# Playground Version
export PLAYGROUND_VERSION=$(git describe --always --dirty)

echo "[INFO] Building and starting Docker container..."
docker compose up --build -d redis conflict-playground hook-$HOOK_TYPE

echo "[INFO] Cleaning up old sessions..."
# Redirect error to /dev/null so it stays quiet if no session exists
tmux kill-session -t conflict-playground 2>/dev/null

echo "[INFO] Starting tmux session..."
tmux new-session -d -s conflict-playground "docker exec -it -e PLAYGROUND_VERSION="$PLAYGROUND_VERSION" -e VOLUME_TYPE=$VOLUME_TYPE -e HOOK_TYPE=$HOOK_TYPE conflict-playground bash src/entrypoint.sh; tmux kill-session"
tmux split-window -h -t conflict-playground "./src-hooks/attach.sh $VOLUME_TYPE $HOOK_TYPE \"$SMARTGIT_BINARY\"; tmux kill-session"
tmux select-pane -t 1

echo "[INFO] Attaching to tmux session..."
tmux attach-session -t conflict-playground