#!/bin/bash

if [ $# -ne 2 ]; then
    echo "Usage: $0 <playground-name>"
    exit 1
fi

PLAYGROUND_NAME="$1"

# Get everything BEFORE the LAST hyphen
echo "${PLAYGROUND_NAME%-*}"