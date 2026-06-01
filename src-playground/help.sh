#!/bin/bash

cat <<'EOF'
General Commands
    help                Show this page
    exit or CTRL+D      Quit the CLI (the container will continue)

Available Tools:
    conflict-*          Scripts from src/conflict
    benchmark-*         Scripts from src/benchmark
    info-redis-*        Save, import, diff, and prune Redis data keys
    repo-*              Scripts from src/repo
    playground-*         Scripts from src/playgrounds
    playbooks-*         Scripts from src/playbooks
EOF
