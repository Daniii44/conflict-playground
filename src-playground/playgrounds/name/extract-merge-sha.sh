#!/bin/bash

if [ $# -ne 1 ]; then
    echo "Usage: $0 <playground-name>"
    exit 1
fi

PLAYGROUND_NAME="$1"

# Get everything AFTER the LAST hyphen
echo "${PLAYGROUND_NAME##*-}"