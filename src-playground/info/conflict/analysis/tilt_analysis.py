from collections import Counter

from loguru import logger
from pydantic import BaseModel, Field

from common.merge_tree import ConflictType, MergeLogicalConflict
from common.redis_util import setup_redis_connection
from info.conflict.analysis.common import Analysis, AnalysisInput, InfoConflict
from info.conflict.analysis.core_analysis import InfoConflictCore


CONTENT_SUBDATASET = "content"
MODIFY_DELETE_SUBDATASET = "modify/delete"
DIRECTORY_SUBDATASET = "directory"
RENAME_SUBDATASET = "rename"

CONFLICT_TYPE_SUBDATASETS: dict[ConflictType, str] = {
    ConflictType.CONFLICT_CONTENTS: CONTENT_SUBDATASET,
    ConflictType.CONFLICT_BINARY: CONTENT_SUBDATASET,
    ConflictType.CONFLICT_MODIFY_DELETE: MODIFY_DELETE_SUBDATASET,
    ConflictType.CONFLICT_DIR_RENAME_SUGGESTED: DIRECTORY_SUBDATASET,
    ConflictType.CONFLICT_DIR_RENAME_SPLIT: DIRECTORY_SUBDATASET,
    ConflictType.CONFLICT_RENAME_DELETE: RENAME_SUBDATASET,
    ConflictType.CONFLICT_RENAME_RENAME: RENAME_SUBDATASET,
}


class TiltConflictTypePurity(BaseModel):
    type: ConflictType
    count: int
    purity: float


class TiltSubdataset(BaseModel):
    name: str
    conflict_count: int
    purity: float
    conflict_types: list[TiltConflictTypePurity]


class InfoConflictTilt(InfoConflict):
    logical_conflict_count: int
    conflict_type_counts: dict[ConflictType, int] = Field(default_factory=dict)
    subdatasets: list[TiltSubdataset] = Field(default_factory=list)


class TiltAnalysis(Analysis):
    def __init__(self, analysis_name: str, redis_client=None):
        super().__init__(analysis_name)
        self._redis = redis_client or setup_redis_connection()

    def core_key(self, analysis_input: AnalysisInput) -> str:
        return (
            f"info:conflict:core:{analysis_input.git_repo_name}:"
            f"{analysis_input.merge_commit_oid}"
        )

    def collect_core_conflict(self, analysis_input: AnalysisInput) -> InfoConflictCore | None:
        key = self.core_key(analysis_input)
        data = self._redis.json().get(key)
        if data is None:
            # In this case the merge didn't produce an actual conflict so this merge is not of any interest.
            return None

        return InfoConflictCore.model_validate(data)

    def build_subdatasets(
        self,
        logical_conflicts: list[MergeLogicalConflict],
    ) -> list[TiltSubdataset]:
        total_conflicts = len(logical_conflicts)
        if total_conflicts == 0:
            return []

        conflict_type_counts = Counter(conflict.type for conflict in logical_conflicts)
        subdataset_counts: dict[str, Counter[ConflictType]] = {}

        for conflict_type, count in conflict_type_counts.items():
            subdataset = CONFLICT_TYPE_SUBDATASETS.get(conflict_type)
            if subdataset is None:
                continue

            subdataset_counts.setdefault(subdataset, Counter())[conflict_type] = count

        subdatasets = []
        for subdataset_name in [
            CONTENT_SUBDATASET,
            MODIFY_DELETE_SUBDATASET,
            DIRECTORY_SUBDATASET,
            RENAME_SUBDATASET,
        ]:
            counts = subdataset_counts.get(subdataset_name)
            if not counts:
                continue

            conflict_count = sum(counts.values())
            subdatasets.append(
                TiltSubdataset(
                    name=subdataset_name,
                    conflict_count=conflict_count,
                    purity=conflict_count / total_conflicts,
                    conflict_types=[
                        TiltConflictTypePurity(
                            type=conflict_type,
                            count=count,
                            purity=count / total_conflicts,
                        )
                        for conflict_type, count in sorted(
                            counts.items(),
                            key=lambda item: item[0].value,
                        )
                    ],
                )
            )

        return subdatasets

    def analyse(self, analysis_input: AnalysisInput) -> tuple[AnalysisInput, BaseModel] | None:
        core_conflict = self.collect_core_conflict(analysis_input)
        if core_conflict is None:
            return None

        logical_conflicts = core_conflict.merge_result.logical_conflicts
        conflict_type_counts = Counter(conflict.type for conflict in logical_conflicts)

        return (
            analysis_input,
            InfoConflictTilt(
                repo=analysis_input.git_repo_name,
                merge_commit_oid=analysis_input.merge_commit_oid,
                logical_conflict_count=len(logical_conflicts),
                conflict_type_counts=dict(conflict_type_counts),
                subdatasets=self.build_subdatasets(logical_conflicts),
            ),
        )
