#!/bin/bash

smartgit-daemon() {
    TARGET_FILE="/root/smartgit-control"

    docker exec conflict-playground-hook-manual-cli touch $TARGET_FILE
    docker exec conflict-playground-hook-manual-cli tail -f -n 0 $TARGET_FILE | while read -r PLAYGROUND_NAME; do
        PLAYGROUND_PATH=$(pwd)/data/playgrounds/$PLAYGROUND_NAME
        /Applications/SmartGit.app/Contents/MacOS/SmartGit --open "$PLAYGROUND_PATH"
    done
}

smartgit-daemon &

docker exec -it -e VOLUME_TYPE=$VOLUME_TYPE -e HOOK_TYPE=$HOOK_TYPE conflict-playground-hook-manual-cli ./entrypoint-base.sh