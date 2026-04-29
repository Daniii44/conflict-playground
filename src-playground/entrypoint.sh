#!/bin/bash

clear
cat <<'EOF'
  ____             __ _ _      _                       
 / ___|___  _ __  / _| (_) ___| |_                     
| |   / _ \| '_ \| |_| | |/ __| __|                    
| |__| (_) | | | |  _| | | (__| |_                     
 \____\___/|_| |_|_| |_|_|\___|\__|                  _ 
|  _ \| | __ _ _   _  __ _ _ __ ___  _   _ _ __   __| |
| |_) | |/ _` | | | |/ _` | '__/ _ \| | | | '_ \ / _` |
|  __/| | (_| | |_| | (_| | | | (_) | |_| | | | | (_| |
|_|   |_|\__,_|\__, |\__, |_|  \___/ \__,_|_| |_|\__,_|
               |___/ |___/                             

EOF

echo "This is the Control Center to create and manage Playgrounds.";
echo "Use \"help\" for a list of commands"
echo

export GIT_AUTHOR_NAME="conflict-playground"
export GIT_AUTHOR_EMAIL="conflict-playground@example.com"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
git config --global init.defaultBranch main

# Rebuild Symbolic Links
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

# Export Directory Structure
export CACHES="${HOME}/caches"
export PLAYGROUNDS="${HOME}/playgrounds"
export PLAYBOOKS="${HOME}/playbooks"
export SOURCES="${HOME}/src"

# Initialization: walk src, copy all executable files to bin with flat names
BIN_DIR="${HOME}/bin"
mkdir -p "$BIN_DIR"
find "$SOURCES" -type f -perm -u=x | while read f; do
    # Get relative path from $SOURCES, replace / with -
    rel="${f#$SOURCES/}"
    # Remove file extension (e.g., .sh, .py)
    base="${rel%.*}"
    flat_name="${base//\//-}"
    cp "$f" "$BIN_DIR/$flat_name"
    chmod +x "$BIN_DIR/$flat_name"
done
export PATH="$BIN_DIR:$PATH"

# Start a zsh shell for user interaction
exec zsh