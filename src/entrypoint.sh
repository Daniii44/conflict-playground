#!/bin/bash

echo "  ____             __ _ _      _                       ";
echo " / ___|___  _ __  / _| (_) ___| |_                     ";
echo "| |   / _ \| '_ \| |_| | |/ __| __|                    ";
echo "| |__| (_) | | | |  _| | | (__| |_                     ";
echo " \____\___/|_| |_|_| |_|_|\___|\__|                  _ ";
echo "|  _ \| | __ _ _   _  __ _ _ __ ___  _   _ _ __   __| |";
echo "| |_) | |/ _\` | | | |/ _\` | '__/ _ \| | | | '_ \ / _\` |";
echo "|  __/| | (_| | |_| | (_| | | | (_) | |_| | | | | (_| |";
echo "|_|   |_|\__,_|\__, |\__, |_|  \___/ \__,_|_| |_|\__,_|";
echo "               |___/ |___/                             ";
echo

echo "Use "help" for a list of commands"
echo

export CACHES="${HOME}/caches"
export PLAYGROUNDS="${HOME}/playgrounds"
export SOURCES="${HOME}/src"

HISTFILE=${CACHES}/.cli_history
history -r "$HISTFILE"

while true; do
    echo
    read -e -p "conflict-playground > " user_input


    if [[ -z "$user_input" ]]; then
        : # Ignore empty input
    elif [[ "$user_input" == "exit" || "$user_input" == "quit" ]]; then
        break
    elif [[ "$user_input" == "help" ]]; then
        cat <<- EOF
General Commands
    help                Show this page
    exit or CTRL+C      Quit the CLI (the container will continue)

Playground Commands
    playground [playground-name]            Start an interactive playground
    playground sync [playground-name]       Cache git repositories locally

Benchmark Commands
    TBD
EOF
    elif [[ "$user_input" == "playground sync" ]]; then
        ${SOURCES}/repo_sync/repo_sync.sh
    else
        echo "Unknown command"
    fi

    history -s "$user_input"
    history -w "$HISTFILE"
done