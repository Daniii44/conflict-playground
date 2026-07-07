from fnmatch import fnmatch

from common.merge_tree import ConflictType
from dataset.tilt.correlation import (
    CONTENT_SUBDATASET,
    DIRECTORY_SUBDATASET,
    MODIFY_DELETE_SUBDATASET,
    RENAME_SUBDATASET,
    build_correlation_table,
    print_latex_table,
)
from info.conflict.analysis.tilt_analysis import (
    InfoConflictTilt,
    TiltConflictTypePurity,
    TiltSubdataset,
)


class FakeRedisJson:
    def __init__(self, values):
        self.values = values

    def get(self, key):
        return self.values.get(key)


class FakeRedis:
    def __init__(self, values):
        self.json_api = FakeRedisJson(values)

    def json(self):
        return self.json_api

    def scan_iter(self, match="*"):
        for key in list(self.json_api.values):
            if fnmatch(key, match):
                yield key


def tilt_info(
    *,
    repo: str = "owner/repo.git",
    merge_sha: str,
    conflict_type_counts: dict[ConflictType, int],
) -> dict:
    subdataset_counts = {
        CONTENT_SUBDATASET: {
            ConflictType.CONFLICT_CONTENTS: conflict_type_counts.get(ConflictType.CONFLICT_CONTENTS, 0),
            ConflictType.CONFLICT_BINARY: conflict_type_counts.get(ConflictType.CONFLICT_BINARY, 0),
        },
        MODIFY_DELETE_SUBDATASET: {
            ConflictType.CONFLICT_MODIFY_DELETE: conflict_type_counts.get(ConflictType.CONFLICT_MODIFY_DELETE, 0),
        },
        RENAME_SUBDATASET: {
            ConflictType.CONFLICT_RENAME_DELETE: conflict_type_counts.get(ConflictType.CONFLICT_RENAME_DELETE, 0),
            ConflictType.CONFLICT_RENAME_RENAME: conflict_type_counts.get(ConflictType.CONFLICT_RENAME_RENAME, 0),
        },
        DIRECTORY_SUBDATASET: {
            ConflictType.CONFLICT_DIR_RENAME_SUGGESTED: conflict_type_counts.get(
                ConflictType.CONFLICT_DIR_RENAME_SUGGESTED,
                0,
            ),
            ConflictType.CONFLICT_DIR_RENAME_SPLIT: conflict_type_counts.get(
                ConflictType.CONFLICT_DIR_RENAME_SPLIT,
                0,
            ),
        },
    }
    total = sum(conflict_type_counts.values())
    return InfoConflictTilt(
        repo=repo,
        merge_commit_oid=merge_sha,
        logical_conflict_count=total,
        conflict_type_counts=conflict_type_counts,
        subdatasets=[
            TiltSubdataset(
                name=subdataset,
                conflict_count=sum(counts.values()),
                purity=sum(counts.values()) / total,
                conflict_types=[
                    TiltConflictTypePurity(
                        type=conflict_type,
                        count=count,
                        purity=count / total,
                    )
                    for conflict_type, count in counts.items()
                    if count
                ],
            )
            for subdataset, counts in subdataset_counts.items()
            if sum(counts.values())
        ],
    ).model_dump()


def dataset_record(
    *,
    subdataset: str,
    source_info_key: str,
) -> dict:
    return {
        "dataset": "tilt",
        "subdataset": subdataset,
        "source_info_key": source_info_key,
    }


def test_build_correlation_table_uses_selected_dataset_records():
    content_info_key = "info:conflict:tilt:owner/repo.git:content"
    directory_info_key = "info:conflict:tilt:owner/repo.git:directory"
    redis = FakeRedis(
        {
            "dataset:tilt:owner/repo.git:content": dataset_record(
                subdataset=CONTENT_SUBDATASET,
                source_info_key=content_info_key,
            ),
            "dataset:tilt:owner/repo.git:directory": dataset_record(
                subdataset=DIRECTORY_SUBDATASET,
                source_info_key=directory_info_key,
            ),
            content_info_key: tilt_info(
                merge_sha="content",
                conflict_type_counts={
                    ConflictType.CONFLICT_CONTENTS: 2,
                    ConflictType.CONFLICT_RENAME_DELETE: 1,
                },
            ),
            directory_info_key: tilt_info(
                merge_sha="directory",
                conflict_type_counts={
                    ConflictType.CONFLICT_CONTENTS: 1,
                    ConflictType.CONFLICT_DIR_RENAME_SUGGESTED: 2,
                },
            ),
        }
    )

    table = build_correlation_table(redis)

    assert table.counts[CONTENT_SUBDATASET][CONTENT_SUBDATASET] == 2
    assert table.counts[CONTENT_SUBDATASET][RENAME_SUBDATASET] == 1
    assert table.normalized[CONTENT_SUBDATASET][CONTENT_SUBDATASET] == 1.0
    assert table.normalized[CONTENT_SUBDATASET][RENAME_SUBDATASET] == 0.5
    assert table.counts[DIRECTORY_SUBDATASET][CONTENT_SUBDATASET] == 1
    assert table.counts[DIRECTORY_SUBDATASET][DIRECTORY_SUBDATASET] == 2
    assert table.normalized[DIRECTORY_SUBDATASET][CONTENT_SUBDATASET] == 0.5
    assert table.normalized[DIRECTORY_SUBDATASET][DIRECTORY_SUBDATASET] == 1.0


def test_print_latex_table_outputs_tabular(capsys):
    redis = FakeRedis(
        {
            "dataset:tilt:owner/repo.git:content": dataset_record(
                subdataset=CONTENT_SUBDATASET,
                source_info_key="info:conflict:tilt:owner/repo.git:content",
            ),
            "info:conflict:tilt:owner/repo.git:content": tilt_info(
                merge_sha="content",
                conflict_type_counts={
                    ConflictType.CONFLICT_CONTENTS: 2,
                },
            ),
        }
    )

    print_latex_table(build_correlation_table(redis), include_counts=False)

    output = capsys.readouterr().out
    assert "\\begin{tabular}{lrrrr}" in output
    assert "Content & 1.000 & 0.000 & 0.000 & 0.000 \\\\" in output
    assert "\\end{tabular}" in output
