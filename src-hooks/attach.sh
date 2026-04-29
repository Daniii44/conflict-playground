#!/bin/bash

if [ $# -lt 2 ]; then
    echo "Usage: $0 <volume-type> <hook-type>"
    echo ""
    echo "volume-type: The type of volume mount to use:"
    echo "  named-volume  Use Docker named volume (better performance)"
    echo "  bind-mount    Use host bind mount (better compatibility)"
    echo ""
    echo "hook-type: The type of merge conflict resolution hook to use:"
    echo "  manual-cli      Manual resolution using CLI tools"
    echo "  manual-smartgit Manual resolution using SmartGit"
    echo ""
    echo "Example: $0 named-volume manual-cli"
    exit 1
fi

echo " _   _             _    ";
echo "| | | | ___   ___ | | __";
echo "| |_| |/ _ \ / _ \| |/ /";
echo "|  _  | (_) | (_) |   < ";
echo "|_| |_|\___/ \___/|_|\_\ ";
echo
echo "The Hook handles the actual Conflict Resolution Task.";
echo "Dispatch Tasks from the Control Center."
echo 
echo "Hook Type: $2"
echo

export VOLUME_TYPE=$1
export HOOK_TYPE=$2

exec src-hooks/$HOOK_TYPE/attach.sh