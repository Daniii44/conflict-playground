#!/bin/bash

cat <<'EOF'
General Commands
    help                Show this page
    exit or CTRL+D      Quit the CLI (the container will continue)

Available Tools:
    conflict-*          Scripts from src/conflict
    benchmark-*         Scripts from src/benchmark
    dataset-*           Inspect imported paper datasets
    evaluation-*        Sync, assess, and replay conflict resolution evaluation output
    state-*             Sync, save, import, diff, and prune state data
    resolution-*        List, inspect, restore, and prune saved conflict resolutions
    repo-*              Scripts from src/repo
    playground-*         Scripts from src/playgrounds
    playbooks-*         Scripts from src/playbooks
EOF
