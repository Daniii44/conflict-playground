# Resolve Merge Conflicts

The current working directory is a Git worktree with an in-progress merge and unresolved conflicts.
Resolve the merge without human interaction, stage the resolved paths, and create the merge commit.

## Operating Rules

This command must run non-interactively from start to finish.

- Do not ask the user for clarification, confirmation, or help.
- Do not stop at a proposed resolution. Make the edits yourself.
- Do not launch editors, pagers, shells, GUI tools, or commands that wait for input.
- Stay within the working directory and its Git metadata.
- Do not use network access.
- Do not install dependencies, download artifacts, or consult external resources.
- Do not run builds, tests, linters, formatters, package scripts, or project programs.
- Do not try to reset or recreate the conflicting state.

You may use non-interactive Git and file-inspection commands to understand the merge state, such as `git status`, `git ls-files -u`, `git diff`, `git diff --cc`, `git show`, `git log`, and ordinary file reads/searches.

## Inspect The Merge

Find every unresolved path and determine the conflict type from the repository state.
Use Git’s index stages and nearby repository history when useful.
Do not assume branch names, project conventions, or conflict causes that are not visible from the repository.

## Resolve Conflicts

Edit files and Git state as needed to remove all unmerged entries.
Choose a resolution based on the available repository evidence.
Keep changes focused on resolving the merge conflict and any directly necessary consistency updates.
Do not make unrelated refactors, cleanups, formatting sweeps, or feature changes.

Stage every resolved path.

## Verify And Commit

Verify by inspection and Git status that there are no unmerged paths left.
Do not run project code or validation commands.

Finalize the merge with:

```bash
git commit --no-edit
```
