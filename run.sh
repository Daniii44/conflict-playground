#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/run-env.sh"

load_playground_env

echo "[INFO] Building and starting Docker container..."
docker compose up --build -d redis conflict-playground hook-$HOOK_TYPE

echo "[INFO] Cleaning up old sessions..."
# Redirect error to /dev/null so it stays quiet if no session exists
tmux kill-session -t conflict-playground 2>/dev/null

echo "[INFO] Starting tmux session..."
tmux new-session -d -s conflict-playground "$(playground_exec_command); tmux kill-session"
tmux split-window -h -t conflict-playground "./src-hooks/attach.sh $VOLUME_TYPE $HOOK_TYPE \"$SMARTGIT_BINARY\"; tmux kill-session"
tmux select-pane -t 1

echo "[INFO] Attaching to tmux session..."
tmux attach-session -t conflict-playground
