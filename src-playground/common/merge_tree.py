from enum import Enum
from construct import Array, CString, Check, Const, ExprAdapter, GreedyBytes, GreedyRange, NullTerminated, StringEncoded, Struct
from pydantic import BaseModel

# Pydantic Models
class ConflictType(str, Enum):
    INFO_AUTO_MERGING = "Auto-merging"

    CONFLICT_CONTENTS = "CONFLICT (contents)"
    CONFLICT_BINARY = "CONFLICT (binary)"
    CONFLICT_FILE_DIRECTORY = "CONFLICT (file/directory)"
    CONFLICT_DISTINCT_MODES = "CONFLICT (distinct modes)"
    CONFLICT_MODIFY_DELETE = "CONFLICT (modify/delete)"

    CONFLICT_RENAME_RENAME = "CONFLICT (rename/rename)"
    CONFLICT_RENAME_COLLIDES = "CONFLICT (rename involved in collision)"
    CONFLICT_RENAME_DELETE = "CONFLICT (rename/delete)"

    CONFLICT_DIR_RENAME_SUGGESTED = "CONFLICT (directory rename suggested)"
    INFO_DIR_RENAME_APPLIED = "Path updated due to directory rename"

    INFO_DIR_RENAME_SKIPPED_DUE_TO_RERENAME = (
        "Directory rename skipped since directory was renamed on both sides"
    )

    CONFLICT_DIR_RENAME_FILE_IN_WAY = "CONFLICT (file in way of directory rename)"
    CONFLICT_DIR_RENAME_COLLISION = "CONFLICT(directory rename collision)"
    CONFLICT_DIR_RENAME_SPLIT = "CONFLICT(directory rename unclear split)"

    INFO_SUBMODULE_FAST_FORWARDING = "Fast forwarding submodule"
    CONFLICT_SUBMODULE_FAILED_TO_MERGE = "CONFLICT (submodule)"

    CONFLICT_SUBMODULE_FAILED_TO_MERGE_BUT_POSSIBLE_RESOLUTION = (
        "CONFLICT (submodule with possible resolution)"
    )
    CONFLICT_SUBMODULE_NOT_INITIALIZED = "CONFLICT (submodule not initialized)"
    CONFLICT_SUBMODULE_HISTORY_NOT_AVAILABLE = "CONFLICT (submodule history not available)"
    CONFLICT_SUBMODULE_MAY_HAVE_REWINDS = "CONFLICT (submodule may have rewinds)"
    CONFLICT_SUBMODULE_NULL_MERGE_BASE = "CONFLICT (submodule lacks merge base)"

    ERROR_SUBMODULE_CORRUPT = "ERROR (submodule corrupt)"
    ERROR_THREEWAY_CONTENT_MERGE_FAILED = "ERROR (three-way content merge failed)"
    ERROR_OBJECT_WRITE_FAILED = "ERROR (object write failed)"
    ERROR_OBJECT_READ_FAILED = "ERROR (object read failed)"
    ERROR_OBJECT_NOT_A_BLOB = "ERROR (object is not a blob)"
class MergeConflictedFile(BaseModel):
    mode: str
    oid: str
    stage: int
    path: str
class MergeLogicalConflict(BaseModel):
    type: ConflictType
    info: str
    paths: list[str]
class MergeResult(BaseModel):
    result_tree_oid: str
    conflicted_files: list[MergeConflictedFile]
    logical_conflicts: list[MergeLogicalConflict]

# Construct Models
_TabTerminatedString = StringEncoded(NullTerminated(GreedyBytes, term=b"\t"), "utf8")
_WhitespaceTerminatedString = StringEncoded(NullTerminated(GreedyBytes, term=b" "), "utf8")
_ConstructConflictedFile = Struct(
    "mode" / _WhitespaceTerminatedString,
    Check(lambda ctx: len(ctx.mode) > 0),
    "oid" / _WhitespaceTerminatedString,
    "stage" / _TabTerminatedString,
    "path" / CString("utf8")
)
_ConstructMergeLogicalConflict = Struct(
    "path_count" / CString("utf8"),
    "paths" / Array(lambda this: int(this.path_count), CString("utf8")),
    "type" / CString("utf8"),
    "info" / ExprAdapter(CString("utf8"), lambda obj,_: obj.strip(), lambda obj,_: obj)
)
_ConstructMergeResult = Struct(
    "result_tree_oid" / CString("utf8"),
    "conflicted_files" / GreedyRange(_ConstructConflictedFile),
    "null_byte" / Const(b"\x00"),
    "logical_conflicts" / GreedyRange(_ConstructMergeLogicalConflict)
)

def parse_merge_result(raw_merge_result: bytes):
    parsed_result = _ConstructMergeResult.parse(raw_merge_result)
    return MergeResult.model_validate(parsed_result)

def prune_auto_merged(mergeResult: MergeResult) -> MergeResult:
    # Prune auto merged files, since they are not really conflicts.
    pruned_logical_conflicts = [
        MergeLogicalConflict(
            type=conflict.type,
            info=conflict.info.strip(),
            paths=[path.strip() for path in conflict.paths]
        )
        for conflict in mergeResult.logical_conflicts if conflict.type != ConflictType.INFO_AUTO_MERGING
    ]

    return MergeResult(
        result_tree_oid=mergeResult.result_tree_oid.strip(),
        conflicted_files=mergeResult.conflicted_files,
        logical_conflicts=pruned_logical_conflicts
    )