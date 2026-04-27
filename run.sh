#!/bin/bash

if [ $# -eq 0 ]; then
    echo "Usage: $0 <volume-type>"
    echo ""
    echo "volume-type: The type of volume mount to use:"
    echo "  named-volume  Use Docker named volume (better performance)"
    echo "  bind-mount    Use host bind mount (better compatibility)"
    echo ""
    echo "Example: $0 named-volume"
    exit 1
fi

VOLUME_TYPE="$1"

if [ "$VOLUME_TYPE" != "named-volume" ] && [ "$VOLUME_TYPE" != "bind-mount" ]; then
    echo "Error: Invalid volume type '$VOLUME_TYPE'"
    echo "Valid options: named-volume, bind-mount"
    exit 1
fi

docker compose up --build -d conflict-playground
docker exec -it -e VOLUME_TYPE="$VOLUME_TYPE" conflict-playground bash src/entrypoint.sh