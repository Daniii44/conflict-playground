#!/bin/bash

smartgit-daemon() {
    TARGET_FILE="/root/smartgit-control"

    docker exec conflict-playground-hook-manual-cli touch $TARGET_FILE
    docker exec conflict-playground-hook-manual-cli tail -f -n 0 $TARGET_FILE | while read -r PLAYGROUND_NAME; do
        if [[ -z $SMARTGIT_BINARY ]]; then
            echo "smartgit_binary" needs to be defined in the config file to launch SmartGit
            continue 
        fi

        PLAYGROUND_PATH=$(pwd)/data/playgrounds/$PLAYGROUND_NAME
        "$SMARTGIT_BINARY" --open "$PLAYGROUND_PATH"
    done
}

echo $SMARTGIT_BINARY
smartgit-daemon &

docker exec -it -e VOLUME_TYPE=$VOLUME_TYPE -e HOOK_TYPE=$HOOK_TYPE conflict-playground-hook-manual-cli ./entrypoint-base.sh