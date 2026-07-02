from common.merge_tree import ConflictType, MergeLogicalConflict, MergeResult
from info.conflict.analysis.common import AnalysisInput
from info.conflict.analysis.core_analysis import InfoConflictCore
from info.conflict.analysis.tilt_analysis import InfoConflictTilt, TiltAnalysis


class FakeJson:
    def __init__(self, values):
        self.values = values

    def get(self, key):
        return self.values.get(key)


class FakeRedis:
    def __init__(self, values):
        self._json = FakeJson(values)

    def json(self):
        return self._json


def analysis_input() -> AnalysisInput:
    return AnalysisInput(
        git_dir="/repos/example.git",
        git_repo_name="owner/repo.git",
        merge_commit_oid="merge-sha",
    )


def logical_conflict(conflict_type: ConflictType) -> MergeLogicalConflict:
    return MergeLogicalConflict(
        type=conflict_type,
        info=f"{conflict_type.value} in file.txt",
        paths=["file.txt"],
    )


def core_conflict(*conflict_types: ConflictType) -> InfoConflictCore:
    return InfoConflictCore(
        repo="owner/repo.git",
        merge_commit_oid="merge-sha",
        merge_result=MergeResult(
            result_tree_oid="tree",
            conflicted_files=[],
            logical_conflicts=[
                logical_conflict(conflict_type)
                for conflict_type in conflict_types
            ],
        ),
    )


def test_analyse_records_requested_example_purities():
    input_ = analysis_input()
    redis = FakeRedis({
        "info:conflict:core:owner/repo.git:merge-sha": core_conflict(
            ConflictType.CONFLICT_CONTENTS,
            ConflictType.CONFLICT_RENAME_DELETE,
            ConflictType.CONFLICT_RENAME_RENAME,
        ).model_dump()
    })
    analysis = TiltAnalysis("tilt", redis_client=redis)

    result = analysis.analyse(input_)

    assert result is not None
    returned_input, tilt = result
    assert returned_input == input_
    assert isinstance(tilt, InfoConflictTilt)
    assert tilt.logical_conflict_count == 3
    assert tilt.conflict_type_counts == {
        ConflictType.CONFLICT_CONTENTS: 1,
        ConflictType.CONFLICT_RENAME_DELETE: 1,
        ConflictType.CONFLICT_RENAME_RENAME: 1,
    }
    assert [subdataset.name for subdataset in tilt.subdatasets] == ["content", "rename"]

    content = tilt.subdatasets[0]
    assert content.conflict_count == 1
    assert content.purity == 1 / 3
    assert [(entry.type, entry.count, entry.purity) for entry in content.conflict_types] == [
        (ConflictType.CONFLICT_CONTENTS, 1, 1 / 3)
    ]

    rename = tilt.subdatasets[1]
    assert rename.conflict_count == 2
    assert rename.purity == 2 / 3
    assert [(entry.type, entry.count, entry.purity) for entry in rename.conflict_types] == [
        (ConflictType.CONFLICT_RENAME_DELETE, 1, 1 / 3),
        (ConflictType.CONFLICT_RENAME_RENAME, 1, 1 / 3),
    ]


def test_analyse_uses_all_logical_conflicts_as_purity_denominator():
    input_ = analysis_input()
    redis = FakeRedis({
        "info:conflict:core:owner/repo.git:merge-sha": core_conflict(
            ConflictType.CONFLICT_CONTENTS,
            ConflictType.CONFLICT_CONTENTS,
            ConflictType.CONFLICT_MODIFY_DELETE,
            ConflictType.CONFLICT_SUBMODULE_FAILED_TO_MERGE,
        ).model_dump()
    })
    analysis = TiltAnalysis("tilt", redis_client=redis)

    result = analysis.analyse(input_)

    assert result is not None
    _returned_input, tilt = result
    assert tilt.logical_conflict_count == 4
    assert [subdataset.name for subdataset in tilt.subdatasets] == ["content", "modify/delete"]
    assert tilt.subdatasets[0].conflict_count == 2
    assert tilt.subdatasets[0].purity == 0.5
    assert tilt.subdatasets[0].conflict_types[0].purity == 0.5
    assert tilt.subdatasets[1].conflict_count == 1
    assert tilt.subdatasets[1].purity == 0.25
    assert tilt.subdatasets[1].conflict_types[0].purity == 0.25


def test_analyse_records_no_subdatasets_when_no_targeted_types():
    input_ = analysis_input()
    redis = FakeRedis({
        "info:conflict:core:owner/repo.git:merge-sha": core_conflict(
            ConflictType.CONFLICT_SUBMODULE_FAILED_TO_MERGE,
        ).model_dump()
    })
    analysis = TiltAnalysis("tilt", redis_client=redis)

    result = analysis.analyse(input_)

    assert result is not None
    _returned_input, tilt = result
    assert tilt.logical_conflict_count == 1
    assert tilt.conflict_type_counts == {
        ConflictType.CONFLICT_SUBMODULE_FAILED_TO_MERGE: 1,
    }
    assert tilt.subdatasets == []


def test_analyse_skips_when_core_record_is_missing():
    analysis = TiltAnalysis("tilt", redis_client=FakeRedis({}))

    assert analysis.analyse(analysis_input()) is None
