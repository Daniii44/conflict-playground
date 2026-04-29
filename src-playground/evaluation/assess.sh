#!/bin/bash

if [ $# -ne 1 ]; then
    echo "Usage: $0 <playground-name>"
    exit 1
fi

evaluation-check-for-merge $1 || exit 0
evaluation-diff $1 || exit 0