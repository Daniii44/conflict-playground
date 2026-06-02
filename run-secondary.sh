#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/run-env.sh"

load_playground_env

if ! docker container inspect -f '{{.State.Running}}' conflict-playground 2>/dev/null | grep -q '^true$'; then
    echo "Error: conflict-playground container is not running."
    echo "Start the main session with ./run.sh first."
    exit 1
fi

BASE_SESSION_NAME="${1:-conflict-playground-secondary}"
SESSION_NAME="$BASE_SESSION_NAME"
SESSION_INDEX=2

while tmux has-session -t "$SESSION_NAME" 2>/dev/null; do
    SESSION_NAME="$BASE_SESSION_NAME-$SESSION_INDEX"
    SESSION_INDEX=$((SESSION_INDEX + 1))
done

echo "[INFO] Starting tmux session $SESSION_NAME..."
tmux new-session -d -s "$SESSION_NAME" "$(playground_exec_command); tmux kill-session"

echo "[INFO] Attaching to tmux session $SESSION_NAME..."
tmux attach-session -t "$SESSION_NAME"
