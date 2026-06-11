# AGENTS.md

Guidance for coding agents working in this repository.

## What This Project Is

A research tool for studying Git merge conflicts at scale. It clones open-source repositories, detects conflicting merge commits using `git merge-tree`, creates isolated "playground" worktrees for manual resolution, and stores results in Redis.

## Imported Datasets

Imported paper datasets live under `data/datasets/`. Their structure is documented in `docs/DATASET.md`. These directories can contain extremely many files, so inspect them only with bounded commands such as `find ... -maxdepth N ... | head -n M`, targeted `jq` queries, or small `sed -n` ranges. Avoid unbounded recursive listings, greps, or counts over the full dataset trees.

## Running

Requires Docker and tmux (WSL on Windows).

```bash
# Copy and configure before first run
cp config.yaml.template config.yaml
# Edit config.yaml: set volume_type (bind-mount | named-volume) and hook_type (manual-cli | manual-smartgit)

# Start everything (builds containers, launches tmux session)
./run.sh
```

`run.sh` builds images, starts Redis plus playground/hook containers, and attaches tmux with the main CLI on the left and hook worker on the right.

## Commands Inside the Container

`entrypoint.sh` flattens executable files from `src-playground/` into `/bin`, replacing `/` with `-` and dropping extensions. Example: `info/conflict/sync.py` becomes `info-conflict-sync`. Avoid two executable files with the same flattened name.

```bash
help                                          # List all commands
repo-sync [playbook] [--no-submodules]        # Clone/update playbook repos to caches
repo-size [playbook]                          # Estimate GitHub disk usage for playbook repos (requires gh_graphql_token or GH_GRAPHQL_TOKEN)
info-conflict-sync <owner/repo.git> [-f]      # Analyze repo for conflicting merges
info-conflict-list [--type <type>]            # Query conflicts from Redis
info-conflict-count <repo>                    # Count stored conflicts
playground-setup <owner/repo.git> <merge_sha> # Create isolated playground
playground-ls                                 # List active playgrounds
playbook-start <name> [--skip N] [--pool N]   # Run a playbook
evaluation-sync [playground] [-a <analysis>]  # Evaluate saved conflict resolutions
```

## Testing

```bash
./test.sh  # Build the playground image and run all tests in Docker
```

`test.sh` runs `pytest` inside the `conflict-playground:playground` Docker image with `PYTHONPATH=/root/src`. `pyproject.toml` sets `testpaths = ["tests-playground"]` and `pythonpath = ["src-playground"]`.

## Python Conventions

Python CLI scripts should use Loguru (`from loguru import logger`) for status/warning/error output instead of `print`; reserve stdout for command output consumed by other commands. Shared Git and repo-cache behavior belongs in `src-playground/common/`: use `common.git_util` for Git subprocesses and `common.repo_cache` for URL-to-cache-key and submodule URL resolution.

## Git Conventions

Always commit your changes after you have completed your task.
Use Conventional Commits with an explicit scope, matching the existing history style, for example `feat(stores): add shared data stores directory`.

## Architecture

### Script Collection (Shell vs Python)

This repository is simply a collection of scripts offered to the user via a cli. Simple scripts are best implemented as simple shell scripts while more complicated ones should be Python to ensure readability. Automatically migrate from shell to python as appropriate.

### Data Flow

```
GitHub repos
  → repo-sync → bare repos in /caches/repos/<owner-or-user>/<repo>.git
  → info-conflict-sync → git merge-tree analysis → Redis (info:conflict:<analysis>:<repo>:<sha>)
  → playbook-start → for each conflict:
      playground-setup (working clone with merge in progress)
      hook-dispatch-task → Redis pub/sub → hook container (user resolves)
      save resolution to Redis
      playground-rm
  → evaluation-sync → restores saved resolutions → Redis (evaluation:merge:<analysis>:...)
```

### Key Components

**Conflict Analysis (`src-playground/info/conflict/`)**
`sync.py` takes repo IDs like `qt/qt5.git`, resolves them under `$CACHES/repos`, iterates merge commits via `git rev-list --merges HEAD`, and runs pluggable analyses (`core`, `divergence`, `tree-diff`). Git subprocesses should go through `common.git_util.capture_git`/`stream_git` so prompts cannot stall execution.

**Repo Cache (`src-playground/repo/sync.py`, `common/repo_cache.py`)**
`repo-sync [playbook]` reads explicit `repo_url` entries, clones bare repositories into `$CACHES/repos/<owner>/<repo>.git`, scans historical `.gitmodules` blobs, and recursively caches submodules unless `--no-submodules` is passed. Do not support the old flat cache naming scheme. Preserve the `.git` suffix in repo IDs stored in Redis and passed between commands.

**Redis Schema**
- Conflict data: JSON at key `info:conflict:<analysis>:<repo>:<sha>`, indexed by the corresponding RediSearch index
- Active playground state: `runtime:active_playground:<playground_name>` (JSON with `ActivePlayground` model)
- Hook communication: `to_hook` / `to_playground` pub/sub channels

**Stores Directory (`/data/stores`)**
Generated, user-inspectable output that should persist outside the container belongs under `$STORES` (`/root/stores` in the container, bind-mounted from `./data/stores`). Redis export/import saves live in `$STORES/redis-saves`; Graphviz DOT output uses `$STORES/graphviz` when commands resolve a bare output name. Do not migrate or depend on older cache-based save paths.

**Playground Lifecycle (`src-playground/playground/`)**
`setup.py` creates a working repo using `.git/objects/info/alternates` pointing at the cached bare repo. It checks out `feature` (first parent), then `main` (second parent), merges `feature`, and leaves conflicts in place. It also initializes clean submodule gitlinks from cached bare repos using `git submodule update --init --reference`; unresolved submodule conflicts are left for the user.

**Hook Worker Pattern (`src-hooks/`)**
Hook workers run separately and communicate over Redis pub/sub. `manual-cli` opens an interactive shell; `manual-smartgit` is GUI-based.

**Playbook Execution (`src-playground/playbook/start.py`)**
Playbooks are YAML files in `/data/playbooks/`. Two modes:
- **Explicit**: `override_merge_shas` lists specific commits per source repo
- **Explicit parent pairs**: `override_merge_shas` entries may also be objects with `parents: [left_sha, right_sha]`; `playbook-start` resolves them to a merge commit in the cached bare repo
- **Dynamic**: `sources: null` + `config.conflict-types` queries Redis for matching conflicts

Setup runs with a `ThreadPoolExecutor` (default pool=3), but hook dispatch is serialized via `hook_lock` so only one manual interaction runs at a time.

### Important Env Variables (set inside container)

| Variable | Description |
|---|---|
| `CACHES` | Path to bare repo cache directory |
| `PLAYGROUNDS` | Path to working playground clones |
| `PLAYBOOKS` | Path to YAML playbook definitions |
| `DATASETS` | Path to imported paper datasets |
| `STORES` | Path to saved command output, such as Graphviz DOT files and Redis data exports |
| `GH_GRAPHQL_TOKEN` | GitHub personal access token for GraphQL API calls such as `repo-size` |
| `VOLUME_TYPE` | `bind-mount` or `named-volume` |
| `HOOK_TYPE` | `manual-cli` or `manual-smartgit` |
| `LOGURU_LEVEL` | Log level (default `INFO`) |

### Git/Submodule Rules

- Use `common.git_util` for Git calls; it sets `GIT_ASKPASS=false`, `GIT_TERMINAL_PROMPT=0`, `SSH_ASKPASS=false`, and `GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes"`.
- Use `common.repo_cache.repo_cache_key()` everywhere a repo URL becomes a cache key. Example: both `https://github.com/qt/qt5.git` and `git@github.com:qt/qt5.git` map to `qt/qt5.git`.
- RediSearch tag queries for repo names must escape `/`, `.`, `-`, and other punctuation.

### Adding a New Analysis Type

1. Create a class in `src-playground/info/conflict/analysis/` inheriting from `Analysis`
2. Register it in `sync.py`'s `collect_analyses()` match statement
3. Add a corresponding Redis index prefix in `common/redis_util.py`

### Adding a New Hook Type

1. Create a new directory under `src-hooks/` with a `Dockerfile` and `entrypoint.py`
2. Subclass `HookWorker` from `src-hooks/hooks_common.py`
3. Add the service to `docker-compose.yaml`
4. Handle the new hook type in `run.sh` and `src-hooks/attach.sh`
