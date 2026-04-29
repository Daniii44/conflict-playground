#!/bin/bash

if [ $# -lt 2 ]; then
    echo "Usage: $0 <volume-type> <hook-type>"
    echo ""
    echo "volume-type: The type of volume mount to use:"
    echo "  named-volume  Use Docker named volume (better performance)"
    echo "  bind-mount    Use host bind mount (better compatibility)"
    echo ""
    echo "hook-type: The type of merge conflict resolution hook to use:"
    echo "  manual-cli      Manual resolution using CLI tools"
    echo "  manual-smartgit Manual resolution using SmartGit"
    echo ""
    echo "Example: $0 named-volume manual-cli"
    exit 1
fi

VOLUME_TYPE="$1"
HOOK_TYPE="$2"

if [ "$VOLUME_TYPE" != "named-volume" ] && [ "$VOLUME_TYPE" != "bind-mount" ]; then
    echo "Error: Invalid volume type '$VOLUME_TYPE'"
    exit 1
fi

if [ "$HOOK_TYPE" != "manual-cli" ] && [ "$HOOK_TYPE" != "manual-smartgit" ]; then
    echo "Error: Invalid hook type '$HOOK_TYPE'"
    exit 1
fi

echo "[INFO] Building and starting Docker container..."
docker compose up --build -d redis conflict-playground hook-$HOOK_TYPE

echo "[INFO] Starting tmux session..."
tmux new-session -d -s conflict-playground "docker exec -it -e VOLUME_TYPE=$VOLUME_TYPE -e HOOK_TYPE=$HOOK_TYPE conflict-playground bash src/entrypoint.sh; tmux kill-session"
tmux split-window -h -t conflict-playground "./src-hooks/attach.sh $VOLUME_TYPE $HOOK_TYPE; tmux kill-session"

echo "[INFO] Attaching to tmux session..."
tmux attach-session -t conflict-playground