#!/bin/bash

echo "Syncing Repositories"
repo-sync "$@"

echo
echo "Syncing Info"
info-sync
