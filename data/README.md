# Application Data

This directory contains all data that is mounted into the container.
The data consists of:
- caches: all kinds of recreatable content
- playgrounds: target to create playground shared clones in
- playbooks: descriptions of conflict resolution playgrounds
- stores: saved command output, including Graphviz DOT files and Redis data exports

Due to performance considerations it is possible to mount `caches` and `playgrounds` as named volumes instead.
This will make it harder to peak into what is going on (especially making it difficult to use GUI applications to
inspect the conflict resolution state) but remove some performance overhead stemming from bind mounts.
