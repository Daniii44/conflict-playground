---
description: Resolve Merge Conflict
agent: build
model: ollama/qwen3-coder-next:latest
---

# Resolve Merge Conflicts

Your job is to resolve all merge conflicts in the current repository without human intervention, then commit the completed merge.

- [Resolve Merge Conflicts](#resolve-merge-conflicts)
  - [1. Operating rules](#1-operating-rules)
  - [2. Inspect the merge](#2-inspect-the-merge)
  - [3. Build context](#3-build-context)
  - [4. Resolve conflicts](#4-resolve-conflicts)
  - [5. Verify and commit](#5-verify-and-commit)

## 1. Operating rules

This command must run non-interactively from start to finish.

- Do not ask the user for clarification, confirmation, or help.
- Do not stop at a proposed resolution. Make the edits yourself.
- Do not launch editors, pagers, shells, GUI tools, or commands that wait for input.
- Do not use network access unless it is already required by the repository's normal local checks.
- Preserve unrelated user changes. Only edit files needed to resolve the merge or to keep the repository consistent after the merge.
- If a conflict is genuinely ambiguous, choose the most conservative resolution supported by the surrounding code, tests, history, and intent of both sides.

If this command is being invoked, a merge is already in progress and there are unresolved conflicts.

## 2. Inspect the merge

Start by establishing the exact state of the repository:

1. Run `git status --short --branch`.
2. Run `git diff --name-only --diff-filter=U` to list conflicted paths.
3. Run `git ls-files -u` to inspect unmerged index stages.
4. When useful, inspect the merge parents with `git rev-parse HEAD MERGE_HEAD` and compare them with `git diff HEAD...MERGE_HEAD -- <path>` or `git diff MERGE_HEAD...HEAD -- <path>`.
5. Run `rg "<<<<<<<|=======|>>>>>>>"` to find textual conflict markers that may remain outside the unmerged index.

Do not assume the branch names are `main` or `feature`; use the actual merge state.

## 3. Build context

For each conflicted path, understand both sides before editing:

1. Inspect `git diff --base -- <path>`, `git diff --ours -- <path>`, and `git diff --theirs -- <path>` when available.
2. Read the surrounding file, related tests, and nearby call sites.
3. Check recent history for the conflicted path with `git log --oneline --decorate -- <path>` when it helps determine intent.
4. Prefer existing project patterns over introducing new abstractions during conflict resolution.

## 4. Resolve conflicts

For each conflict, decide whether to:

1. Keep our changes
2. Keep their changes
3. Use a careful, intelligent combination of both

In most cases you should aim for (3), but correctness matters more than cleverness.

When you are confident about how to resolve a conflict:

1. Edit the file to the desired final state.
2. Remove all conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).
3. Ensure the resolved code is coherent as a whole, not just marker-free.
4. Preserve formatting conventions already used in the file.
5. Stage the resolved file with `git add <path>`.

For deleted/renamed/added conflicts, choose the result that best preserves working functionality and project intent, then stage the final state with `git add` or `git rm` as appropriate.

For submodule conflicts, inspect the gitlink SHAs and available submodule history if present. Choose the commit that preserves the intended dependency state, update the submodule checkout when possible, then stage the gitlink.

Continue until `git diff --name-only --diff-filter=U` prints nothing.

## 5. Verify and commit

Before committing:

1. Run `rg "<<<<<<<|=======|>>>>>>>"` and remove any remaining conflict markers.
2. Run `git diff --check`.
3. Run focused tests, linters, type checks, or build commands if they are discoverable and practical for the repository. Prefer the cheapest relevant checks first.
4. Run `git status --short` and confirm there are no unmerged paths.
5. Review the staged merge resolution with `git diff --cached`.

If checks fail because of your resolution, fix the issue and rerun the relevant check. If checks fail for an unrelated pre-existing reason, continue only after verifying the merge is still fully resolved and internally consistent.

Commit the completed merge non-interactively:

\`\`\`bash
git commit --no-edit
\`\`\`

If `git commit --no-edit` is not possible because no merge message exists, use:

\`\`\`bash
git commit -m "Resolve merge conflicts"
\`\`\`

Finish only after the merge commit succeeds. Then report the commit SHA, the checks you ran, and any checks that could not be run.
