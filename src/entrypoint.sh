#!/bin/bash

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
echo

echo "Use \"help\" for a list of commands"
echo


# Rebuild Symbolic Links
export VOLUME_TYPE="${VOLUME_TYPE:-named-volume}"
rm -rf caches # FIXME
rm -f workdir
if [ "$VOLUME_TYPE" = "bind-mount" ]; then
    ln -s caches-bind-mount caches
    ln -s workdir-bind-mount workdir
else
    ln -s caches-named-volume caches
    ln -s workdir-named-volume workdir
fi

# Export Directory Structure
export CACHES="${HOME}/caches"
export WORKDIR="${HOME}/workdir"
export PLAYGROUNDS="${HOME}/playgrounds"
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

# Write help function to zshrc
cat >> ~/.zshrc <<'HELP_EOF'
help() {
    cat <<'EOF'
General Commands
    help                Show this page
    exit or CTRL+D      Quit the CLI (the container will continue)

Available Tools:
    conflict-*          Scripts from src/conflict
    benchmark-*         Scripts from src/benchmark
    repo-*              Scripts from src/repo
    workdir-*           Scripts from src/workdir
EOF
}
HELP_EOF

# Start a zsh shell for user interaction
exec zsh