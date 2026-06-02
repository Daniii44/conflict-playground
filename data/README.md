# Application Data

This directory contains all data that is mounted into the container.
The data consists of:
- caches: all kinds of recreatable content
- playgrounds: target to create playground shared clones in
- playbooks: descriptions of conflict resolution playgrounds
- stores: saved command output, including Graphviz DOT files and Redis data exports

## Playbook Conflict Type Selection

Playbooks may filter selected conflicts with `playbook.config.conflict-types`.
They may also set target percentages for conflict types:

```yaml
playbook:
  config:
    conflict-type-percentages:
      CONFLICT (contents): 80
      CONFLICT (rename/rename): 20
  sources:
    - repo_url: https://github.com/example/project.git
      limit: 10
```

When target percentages are set, `playbook-start` keeps a running selection
composition across repositories. If an earlier repository lacks one target type,
later repositories that contain that type are preferred until the overall
selection moves back toward the requested percentages.

Due to performance considerations it is possible to mount `caches` and `playgrounds` as named volumes instead.
This will make it harder to peak into what is going on (especially making it difficult to use GUI applications to
inspect the conflict resolution state) but remove some performance overhead stemming from bind mounts.
