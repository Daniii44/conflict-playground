#!/bin/bash

docker exec -it \
    -e VOLUME_TYPE=$VOLUME_TYPE \
    -e HOOK_TYPE=$HOOK_TYPE \
    -e OPENCODE_MODEL=$OPENCODE_MODEL \
    conflict-playground-hook-opencode \
    ./entrypoint-base.sh
