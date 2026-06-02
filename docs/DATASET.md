# Imported Datasets

This repository currently contains two imported paper datasets under `data/datasets/`.
Both trees can contain very many files. When inspecting them, use bounded commands
such as `find ... -maxdepth N ... | head -n M`, targeted `jq` queries on a single
JSON file, or `sed -n` ranges. Avoid unbounded recursive listings, greps, or counts.

## Ji et al.: Understanding Merge Conflicts and Resolutions in Git Rebases

Location: `data/datasets/ji`

This dataset is a compact Git repository import. The working tree contains:

- `README.md`: upstream format description.
- `all_rebases`: the main data file, about 45 MB in this import.
- `.git/`: metadata for the imported dataset repository.

`all_rebases` is a line-oriented text file. Each line represents one rebase:

```text
repo:PR_num:pre_commits:post_commits:local_pre_commits:local_post_commits:matched_indexes
```

The commit-list fields are comma-separated SHA lists. Per the upstream README, the
ordered commit lists are stored as `[HEAD, ..., fork-point]`.

Observed field meanings:

- `repo`: GitHub repository in `owner/name` form, without `.git`.
- `PR_num`: pull request number associated with the rebase.
- `pre_commits`: first-parent commits from the head branch before rebasing.
- `post_commits`: first-parent commits from the head branch after rebasing.
- `local_pre_commits`: locally restored SHAs corresponding to `pre_commits`.
- `local_post_commits`: locally restored SHAs corresponding to `post_commits`.
- `matched_indexes`: comma-separated indexes mapping pre-rebase commits to
  post-rebase commits; `-1` appears for unmatched entries.

Notes for consumers:

- Treat `all_rebases` as a custom colon-delimited format, not CSV. The commit-list
  fields contain comma-separated lists and may be long.
- The local SHA fields are useful when the paper's reconstructed repositories differ
  from upstream GitHub commit IDs.
- The file had 51,183 lines in the inspected import.

## Schesch et al.: Evaluation of Version Control Merge Tools

Location: `data/datasets/schesch`

This dataset is organized as per-repository JSON files below four top-level result
directories. The common path shape is:

```text
data/datasets/schesch/<result-kind>/<owner>/<repo>.json
```

The repository filenames omit `.git`; for example, `j256/simplemagic` is stored as
`data/datasets/schesch/<result-kind>/j256/simplemagic.json`.

Top-level result directories:

- `test_cache/`: test execution results keyed by fingerprint-like IDs.
- `sha_cache_entry/`: mappings from original commit IDs or tool-run IDs to
  generated tree/commit fingerprints and merge status.
- `merge_timing_results/`: runtime measurements for specific merge-tool runs.
- `merge_analysis/`: static merge-pair metadata such as changed files, diff sizes,
  Java involvement, import involvement, and paths to diff-analysis logs.

The result directories are nested by coverage: `merge_timing_results` is a subset
of `merge_analysis`, and `merge_analysis` is a subset of `test_cache`. In other
words, not every repository or merge in `test_cache` has static merge analysis,
and not every analyzed merge has merge-tool timing results.

### `test_cache`

Each file is a JSON object. Observed keys are fingerprint-like IDs. Values contain:

- `test_result`: aggregate result such as `Tests_passed` or `Tests_failed`.
- `test_results`: list of per-run test results.
- `test_coverage`: list of per-run coverage values.
- `test_log_file`: paths to logs from the original dataset environment.

The log paths are stored as strings such as `cache/test_cache/logs/...`; they are
references from the original dataset layout and are not necessarily present in this
repository.

### `sha_cache_entry`

Each file is a JSON object with mixed key shapes:

- `<commit-sha>` for individual checkout/cache entries.
- `<left-sha>_<right-sha>_<tool>` for merge-tool executions.

Individual checkout values contain:

- `sha`: generated fingerprint or reconstructed SHA.
- `explanation`: short provenance text, for example a checked-out commit message.

Merge-tool values contain:

- `sha`: generated merge-result fingerprint.
- `left_fingerprint` and `right_fingerprint`: fingerprints for the two sides.
- `merge status`: status such as `Merge_success` or `Merge_failed`.
- `merge_logs`: optional path to an original merge log.

Observed merge-tool key suffixes include Git strategies and external tools such as
`git_hires_merge`, `gitmerge_ort`, `gitmerge_recursive_*`, `gitmerge_resolve`,
`intellimerge`, `plumelib_ort*`, and `spork`.

### `merge_timing_results`

Each file is a JSON object keyed by:

```text
<left-sha>-<right-sha>-<tool>
```

Values contain `run_time`, a list of measured runtimes in seconds for the tool run.
Because this directory compares multiple merge tools, the same merge pair can
appear multiple times with different `<tool>` suffixes. Count distinct merges by
repository plus `<left-sha>-<right-sha>`, not by complete timing-result key.

The playground CLI includes `dataset-schesch-count`, which reports the number of
repositories and distinct merge pairs that pass the paper's final merge filter in
`merge_analysis`.

### `merge_analysis`

Each file is a JSON object keyed by:

```text
<left-sha>_<right-sha>
```

Values summarize the merge pair and its diffs. Observed fields include:

- `diff contains java file`
- `imports_involved`
- `left parent test result`
- `non_java_involved`
- `num_diff_files`
- `num_diff_hunks`
- `num_diff_lines`
- `num_intersecting_files`
- `parents pass`
- `right parent test result`
- `test merge`
- `union_diff_files`
- `diff_logs`: original log paths for `base_left`, `base_right`, and `left_right`

Some numeric-looking fields may contain sentinel strings such as `"Error"`, so
consumers should validate types instead of assuming every metric is numeric.

The paper's final merge subset can be counted from this directory by retaining
entries where `diff contains java file` is `true`, `parents pass` is `true`, and
both `left parent test result` and `right parent test result` are `Tests_passed`.
The `test merge` flag must also be `true`; entries without that flag were analyzed
but not retained in the final parent-tested merge subset. In this import, matching
the paper's 6,045 retained merges also requires completed diff metrics
(`num_diff_hunks` must be numeric) and excludes large diff-analysis records where
`num_diff_files >= 1000`. `dataset-schesch-count` applies that filter and counts
repositories with at least one retained merge.

## Practical Inspection Patterns

Prefer commands like these when exploring the datasets:

```bash
find data/datasets/schesch -maxdepth 3 -type d | head -n 100
find data/datasets/schesch/merge_analysis -maxdepth 4 -type f | head -n 50
jq 'keys[:20]' data/datasets/schesch/merge_analysis/j256/simplemagic.json
jq 'to_entries[:2]' data/datasets/schesch/sha_cache_entry/j256/simplemagic.json
sed -n '1,5p' data/datasets/ji/all_rebases
```

Avoid commands like these on the full dataset trees:

```bash
find data/datasets -type f
grep -R pattern data/datasets
rg pattern data/datasets
du -sh data/datasets
```
