#!/bin/bash


docker exec -it -e VOLUME_TYPE=$VOLUME_TYPE -e HOOK_TYPE=$HOOK_TYPE conflict-playground-hook-manual-cli ./entrypoint-base.sh