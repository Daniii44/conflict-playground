#!/bin/bash

export VOLUME_TYPE="${VOLUME_TYPE:-named-volume}"
rm -rf caches # FIXME
rm -f playgrounds
if [ "$VOLUME_TYPE" = "bind-mount" ]; then
    ln -s caches-bind-mount caches
    ln -s playgrounds-bind-mount playgrounds
else
    ln -s caches-named-volume caches
    ln -s playgrounds-named-volume playgrounds
fi

export PLAYGROUNDS="${HOME}/playgrounds"

exec ./entrypoint.py