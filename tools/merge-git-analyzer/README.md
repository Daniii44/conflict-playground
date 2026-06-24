# Conflict Resolution Analyzer

Standalone extraction of MeGA's conflicting-file resolution analyzer.

The executable takes two files:

1. an unmerged file containing diff3 conflict markers
2. the resolved/merged version of that file

It prints the ordered `ConflictResolutionResult` list as JSON.

## Build

```shell
mvn clean package
```

The runnable jar is written to:

```shell
target/conflict-resolution-analyzer-1.0.0.jar
```

## Usage

```shell
java -jar target/conflict-resolution-analyzer-1.0.0.jar <unmerged-file> <merged-file>
```

Example output:

```json
["CONTEXT_UNCHANGED","CHUNK_CANONICAL_OURS","CONTEXT_CHANGED"]
```

Pass `--formatting` to use the original analyzer's language-agnostic whitespace normalization:

```shell
java -jar target/conflict-resolution-analyzer-1.0.0.jar --formatting <unmerged-file> <merged-file>
```

The unmerged input must include diff3-style conflict sections with `<<<<<<<`, `|||||||`, `=======`, and `>>>>>>>` markers. Marker labels are accepted, so both `<<<<<<< ours` and `<<<<<<< GitAnalyzerPlus_ours` work.
