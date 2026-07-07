from fnmatch import fnmatch

from common.merge_tree import ConflictType
from dataset.tilt.playbook import (
    DATASET_TILT_KEY,
    TOP100_TARGETS,
    TiltTarget,
    build_tilt_playbook_result,
    dataset_tilt_conflict_key,
    default_playbook_output_path,
    generate_tilt_playbook,
    targets_for_name,
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

    def set(self, key, _path, value):
        self.values[key] = value


class FakeRedis:
    def __init__(self, values):
        self.json_api = FakeRedisJson(values)
        self.deleted = []

    def json(self):
        return self.json_api

    def scan_iter(self, match="*"):
        for key in list(self.json_api.values):
            if fnmatch(key, match):
                yield key

    def delete(self, *keys):
        self.deleted.extend(keys)
        for key in keys:
            self.json_api.values.pop(key, None)


def tilt_info(
    *,
    repo: str = "owner/repo.git",
    merge_sha: str = "merge-sha",
    logical_conflict_count: int = 1,
    subdatasets: list[TiltSubdataset],
) -> dict:
    return InfoConflictTilt(
        repo=repo,
        merge_commit_oid=merge_sha,
        logical_conflict_count=logical_conflict_count,
        conflict_type_counts={},
        subdatasets=subdatasets,
    ).model_dump()


def subdataset(
    name: str,
    purity: float,
    entries: list[tuple[ConflictType, float]],
) -> TiltSubdataset:
    return TiltSubdataset(
        name=name,
        conflict_count=len(entries),
        purity=purity,
        conflict_types=[
            TiltConflictTypePurity(
                type=conflict_type,
                count=1,
                purity=entry_purity,
            )
            for conflict_type, entry_purity in entries
        ],
    )


def tilt_key(repo: str, merge_sha: str) -> str:
    return f"info:conflict:tilt:{repo}:{merge_sha}"


def test_top100_target_resolves_by_name():
    assert targets_for_name("top100") == TOP100_TARGETS


def test_default_playbook_output_path_uses_target_name(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYBOOKS", str(tmp_path))

    assert default_playbook_output_path("top100") == tmp_path / "top100.yaml"


def test_build_tilt_playbook_prefers_scarce_bucket_for_multi_qualifying_conflict():
    targets = (
        TiltTarget("content", ConflictType.CONFLICT_CONTENTS, 1),
        TiltTarget("rename", ConflictType.CONFLICT_RENAME_DELETE, 1),
    )
    redis = FakeRedis(
        {
            tilt_key("owner/repo.git", "shared"): tilt_info(
                merge_sha="shared",
                logical_conflict_count=2,
                subdatasets=[
                    subdataset("content", 0.5, [(ConflictType.CONFLICT_CONTENTS, 0.5)]),
                    subdataset("rename", 0.5, [(ConflictType.CONFLICT_RENAME_DELETE, 0.5)]),
                ],
            ),
            tilt_key("owner/repo.git", "content-only"): tilt_info(
                merge_sha="content-only",
                subdatasets=[
                    subdataset("content", 1.0, [(ConflictType.CONFLICT_CONTENTS, 1.0)]),
                ],
            ),
            tilt_key("owner/repo.git", "content-extra"): tilt_info(
                merge_sha="content-extra",
                subdatasets=[
                    subdataset("content", 0.8, [(ConflictType.CONFLICT_CONTENTS, 0.8)]),
                ],
            ),
        }
    )

    result = build_tilt_playbook_result(redis, targets=targets)

    selected_by_sha = {
        candidate.identity.merge_sha: candidate
        for candidate in result.selected
    }
    assert set(selected_by_sha) == {"shared", "content-only"}
    assert selected_by_sha["shared"].subdataset == "rename"
    assert selected_by_sha["shared"].reason_conflict_type == ConflictType.CONFLICT_RENAME_DELETE
    assert selected_by_sha["content-only"].subdataset == "content"
    assert selected_by_sha["content-only"].reason_conflict_type == ConflictType.CONFLICT_CONTENTS
    assert result.shortfalls_by_reason == {}


def test_build_tilt_playbook_ranks_by_subdataset_purity_before_reason_purity():
    targets = (TiltTarget("content", ConflictType.CONFLICT_BINARY, 1),)
    redis = FakeRedis(
        {
            tilt_key("owner/repo.git", "lower-subdataset-purity"): tilt_info(
                merge_sha="lower-subdataset-purity",
                subdatasets=[
                    subdataset("content", 0.5, [(ConflictType.CONFLICT_BINARY, 0.5)]),
                ],
            ),
            tilt_key("owner/repo.git", "higher-subdataset-purity"): tilt_info(
                merge_sha="higher-subdataset-purity",
                logical_conflict_count=2,
                subdatasets=[
                    subdataset("content", 1.0, [(ConflictType.CONFLICT_BINARY, 0.5)]),
                ],
            ),
        }
    )

    result = build_tilt_playbook_result(redis, targets=targets)

    assert [candidate.identity.merge_sha for candidate in result.selected] == [
        "higher-subdataset-purity"
    ]


def test_generate_tilt_playbook_writes_comments_and_dataset_records(tmp_path):
    targets = (
        TiltTarget("content", ConflictType.CONFLICT_BINARY, 1),
        TiltTarget("directory", ConflictType.CONFLICT_DIR_RENAME_SPLIT, 1),
    )
    redis = FakeRedis(
        {
            "dataset:tilt:stale/repo.git:old": {"stale": True},
            tilt_key("owner/repo.git", "binary"): tilt_info(
                merge_sha="binary",
                subdatasets=[
                    subdataset("content", 1.0, [(ConflictType.CONFLICT_BINARY, 1.0)]),
                ],
            ),
            tilt_key("owner/repo.git", "split"): tilt_info(
                merge_sha="split",
                subdatasets=[
                    subdataset(
                        "directory",
                        1.0,
                        [(ConflictType.CONFLICT_DIR_RENAME_SPLIT, 1.0)],
                    ),
                ],
            ),
        }
    )
    output = tmp_path / "tilt.yaml"

    result = generate_tilt_playbook(output, redis=redis, targets=targets)

    playbook = output.read_text(encoding="utf-8")
    assert "        - binary # subdataset: content; reason: CONFLICT (binary);" in playbook
    assert (
        "        - split # subdataset: directory; "
        "reason: CONFLICT(directory rename unclear split);"
    ) in playbook

    assert "dataset:tilt:stale/repo.git:old" not in redis.json_api.values
    assert redis.json_api.values[DATASET_TILT_KEY]["selected_count"] == 2
    assert redis.json_api.values[DATASET_TILT_KEY]["subdataset_counts"] == {
        "content": 1,
        "directory": 1,
    }

    binary_record = redis.json_api.values[
        dataset_tilt_conflict_key(result.selected[0].identity)
    ]
    assert binary_record["subdataset"] == "content"
    assert binary_record["reason_conflict_type"] == "CONFLICT (binary)"
