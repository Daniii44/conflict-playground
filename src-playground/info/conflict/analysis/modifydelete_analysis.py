from pydantic import BaseModel, Field

from common.merge_tree import ConflictType, MergeConflictedFile
from common.redis_util import setup_redis_connection
from info.conflict.analysis.common import Analysis, AnalysisInput, InfoConflict
from info.conflict.analysis.core_analysis import InfoConflictCore


class ModifyDeleteConflictPath(BaseModel):
    logical_conflict_index: int
    path: str
    base_oid: str | None = None
    ours_oid: str | None = None
    theirs_oid: str | None = None


class InfoConflictModifyDelete(InfoConflict):
    conflicted_tree_oid: str
    conflicts: list[ModifyDeleteConflictPath] = Field(default_factory=list)


class ModifyDeleteInfoAnalysis(Analysis):
    """Extract modify/delete conflict inputs from the already-recorded merge tree."""

    def __init__(self, analysis_name: str, redis_client=None):
        super().__init__(analysis_name)
        self._redis = redis_client or setup_redis_connection()

    def core_key(self, analysis_input: AnalysisInput) -> str:
        return (
            f"info:conflict:core:{analysis_input.git_repo_name}:"
            f"{analysis_input.merge_commit_oid}"
        )

    def collect_core_conflict(self, analysis_input: AnalysisInput) -> InfoConflictCore | None:
        data = self._redis.json().get(self.core_key(analysis_input))
        return InfoConflictCore.model_validate(data) if data is not None else None

    @staticmethod
    def stage_oids(files: list[MergeConflictedFile]) -> dict[int, str]:
        return {file.stage: file.oid for file in files}

    def extract_conflicts(self, core_conflict: InfoConflictCore) -> list[ModifyDeleteConflictPath]:
        files_by_path: dict[str, list[MergeConflictedFile]] = {}
        for file in core_conflict.merge_result.conflicted_files:
            files_by_path.setdefault(file.path, []).append(file)

        conflicts = []
        for index, logical_conflict in enumerate(core_conflict.merge_result.logical_conflicts):
            if logical_conflict.type != ConflictType.CONFLICT_MODIFY_DELETE:
                continue
            for path in logical_conflict.paths:
                oids = self.stage_oids(files_by_path.get(path, []))
                conflicts.append(
                    ModifyDeleteConflictPath(
                        logical_conflict_index=index,
                        path=path,
                        base_oid=oids.get(1),
                        ours_oid=oids.get(2),
                        theirs_oid=oids.get(3),
                    )
                )
        return conflicts

    def analyse(self, analysis_input: AnalysisInput) -> tuple[AnalysisInput, BaseModel] | None:
        core_conflict = self.collect_core_conflict(analysis_input)
        if core_conflict is None:
            return None

        conflicts = self.extract_conflicts(core_conflict)
        if not conflicts:
            return None

        return (
            analysis_input,
            InfoConflictModifyDelete(
                repo=analysis_input.git_repo_name,
                merge_commit_oid=analysis_input.merge_commit_oid,
                conflicted_tree_oid=core_conflict.merge_result.result_tree_oid,
                conflicts=conflicts,
            ),
        )
