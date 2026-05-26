# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

A research tool for studying Git merge conflicts at scale. It clones open-source repositories, detects conflicting merge commits using `git merge-tree`, and creates isolated "playground" environments where users can manually resolve conflicts. Results are stored in Redis for analysis.

## Running

Requires Docker and tmux (WSL on Windows).

```bash
# Copy and configure before first run
cp config.yaml.template config.yaml
# Edit config.yaml: set volume_type (bind-mount | named-volume) and hook_type (manual-cli | manual-smartgit)

# Start everything (builds containers, launches tmux session)
./run.sh
```

`run.sh` builds the Docker images, starts Redis + the playground container + hook container, and attaches a tmux session with two panes: left is the main CLI shell, right is the hook worker.

## Commands Inside the Container

The container's `entrypoint.sh` flattens all executables from `src-playground/` into a single `/bin` directory, replacing `/` with `-` in names. So `info/conflict/sync.py` becomes `info-conflict-sync`.

```bash
help                                          # List all commands
repo-sync [playbook]                          # Clone/update playbook repos to caches
info-conflict-sync <repo> [-f] [-a core]      # Analyze repo for conflicting merges
info-conflict-list [--type <type>]            # Query conflicts from Redis
info-conflict-count <repo>                    # Count stored conflicts
playground-setup <repo> <merge_sha>           # Create isolated playground
playground-ls                                 # List active playgrounds
playbook-start <name> [--skip N] [--pool N]   # Run a playbook
evaluation-assess <playground_name>           # Evaluate a resolved conflict
```

## Testing

```bash
pytest                        # Run all tests (tests-playground/ directory)
pytest tests-playground/foo.py  # Run a single test file
```

`pyproject.toml` sets `testpaths = ["tests-playground"]` and `pythonpath = ["src-playground"]`.

## Python Logging

Python CLI scripts should use Loguru (`from loguru import logger`) for status, warning, and error output instead of `print`. The container installs `python3-loguru`, and log verbosity is controlled by `LOGURU_LEVEL`.

## Architecture

### Data Flow

```
GitHub repos
  → repo-sync → bare repos in /caches/repos/<owner-or-user>/<repo>.git
  → info-conflict-sync → git merge-tree analysis → Redis (info:conflict:core:<repo><sha>)
  → playbook-start → for each conflict:
      playground-setup (working clone with merge in progress)
      hook-dispatch-task → Redis pub/sub → hook container (user resolves)
      evaluation-assess → stores result in Redis
      playground-rm
```

### Key Components

**Conflict Analysis (`src-playground/info/conflict/`)**  
`sync.py` iterates all merge commits in a bare repo via `git rev-list --merges HEAD`, runs `git merge-tree -z` on each pair of parents, and stores conflicts in Redis. Analysis is pluggable: `CoreAnalysis` detects structural conflicts; `MergeBaseAnalysis` is an additional plugin. The binary `merge-tree` output is parsed by `common/merge_tree.py` using the `construct` library.

**Redis Schema**  
- Conflict data: JSON at key `info:conflict:core:<repo><sha>`, indexed by `idx:info:conflict:core`
- Active playground state: `runtime:active_playground:<playground_name>` (JSON with `ActivePlayground` model)
- Hook communication: `to_hook` / `to_playground` pub/sub channels

**Playground Lifecycle (`src-playground/playground/`)**  
`setup.py` creates a git clone using alternates (space-efficient, references the bare repo). It checks out `main` (first parent) and `feature` (second parent) branches and initiates a merge, leaving the repo in a conflicted state for the user.

**Hook Worker Pattern (`src-hooks/`)**  
Hook workers run in a separate container. `HookWorker` base class in `hooks_common.py` handles Redis pub/sub. Currently only `manual-cli` is implemented: it spawns an interactive zsh session so the user can resolve conflicts manually with standard git tools. A `manual-smartgit` hook also exists (GUI-based).

**Playbook Execution (`src-playground/playbook/start.py`)**  
Playbooks are YAML files in `/data/playbooks/`. Two modes:
- **Explicit**: `override_merge_shas` lists specific commits per source repo
- **Dynamic**: `sources: null` + `config.conflict-types` queries Redis for matching conflicts

Setup runs with a `ThreadPoolExecutor` (default pool=3), but hook dispatch is serialized via `hook_lock` to ensure one user interaction at a time.

### Important Env Variables (set inside container)

| Variable | Description |
|---|---|
| `CACHES` | Path to bare repo cache directory |
| `PLAYGROUNDS` | Path to working playground clones |
| `PLAYBOOKS` | Path to YAML playbook definitions |
| `VOLUME_TYPE` | `bind-mount` or `named-volume` |
| `HOOK_TYPE` | `manual-cli` or `manual-smartgit` |
| `LOGURU_LEVEL` | Log level (default `INFO`) |

### Adding a New Analysis Type

1. Create a class in `src-playground/info/conflict/analysis/` inheriting from `Analysis`
2. Register it in `sync.py`'s `collect_analyses()` match statement
3. Add a corresponding Redis index prefix in `common/redis_util.py`

### Adding a New Hook Type

1. Create a new directory under `src-hooks/` with a `Dockerfile` and `entrypoint.py`
2. Subclass `HookWorker` from `src-hooks/hooks_common.py`
3. Add the service to `docker-compose.yaml`
4. Handle the new hook type in `run.sh` and `src-hooks/attach.sh`
