# Conflict Fixture Files

Each fixture directory contains:

- `unmerged.txt`: a diff3-style file with conflict markers
- `merged.txt`: the resolved version to analyze against

Expected ordered results:

- `canonical-ours`: `["CONTEXT_UNCHANGED","CHUNK_CANONICAL_OURS","CONTEXT_UNCHANGED"]`
- `canonical-theirs`: `["CONTEXT_UNCHANGED","CHUNK_CANONICAL_THEIRS","CONTEXT_UNCHANGED"]`
- `noncanonical-edit`: `["CONTEXT_UNCHANGED","CHUNK_NONCANONICAL","CONTEXT_UNCHANGED"]`

Run one fixture with:

```shell
java -jar target/conflict-resolution-analyzer-1.0.0.jar \
  src/test/resources/conflicting-files/canonical-ours/unmerged.txt \
  src/test/resources/conflicting-files/canonical-ours/merged.txt
```
