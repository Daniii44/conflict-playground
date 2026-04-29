#!/bin/bash

if [ $# -ne 1 ]; then
    echo "Usage: $0 <playground-name>"
    exit 1
fi

rm -rf $PLAYGROUNDS/$1 || exit 0