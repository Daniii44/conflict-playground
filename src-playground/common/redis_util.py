from redis import Redis, ResponseError
from redis.commands.search.field import TagField, TextField, NumericField
from redis.commands.search.index_definition import IndexDefinition, IndexType

IDX_INFO_CONFLICT_CORE = "idx:info:conflict:core"
IDX_INFO_CONFLICT_TILT = "idx:info:conflict:tilt"
IDX_INFO_CONFLICT_OCTOPUS = "idx:info:conflict:octopus"
IDX_INFO_CONFLICT_SCHESCH = "idx:info:conflict:schesch"
RUNTIME_ACTIVE_PLAYGROUND_PREFIX = "runtime:active_playground:"
RESOLUTION_CONFLICT_PREFIX = "resolution:conflict:"
EVALUATION_MERGE_PREFIX = "evaluation:merge:"
EVALUATION_MERGE_CORE_PREFIX = "evaluation:merge:core:"
EVALUATION_MERGE_DIFF_PREFIX = "evaluation:merge:diff:"
EVALUATION_MERGE_SEM_PREFIX = "evaluation:merge:sem:"
INFO_SUBMODULE_PREFIX = "info:submodule:"

def setup_redis_connection() -> Redis:
    redis = Redis(
        host="redis",
        port=6379,
        decode_responses=True
    )

    _ensure_exists_all_idx(redis)
    return redis

def _ensure_exists_all_idx(redis: Redis) -> None:
    _ensure_exists_conflicts_info_idx(redis)

def _ensure_exists_conflicts_info_idx(redis: Redis) -> None:
    core_schema = [
        TagField("$.repo", as_name="repo"),
        TagField("$.merge_commit_oid", as_name="merge_commit_oid"),
        NumericField("$.parent_count", as_name="parent_count"),
        TagField("$.merge_result.logical_conflicts[*].type", as_name="type"),
    ]
    core_definition = IndexDefinition(prefix=["info:conflict:core"], index_type=IndexType.JSON)

    _ensure_exists_idx(redis, IDX_INFO_CONFLICT_CORE, core_definition, core_schema)

    tilt_schema = [
        TagField("$.repo", as_name="repo"),
        TagField("$.merge_commit_oid", as_name="merge_commit_oid"),
        NumericField("$.logical_conflict_count", as_name="logical_conflict_count"),
        TagField("$.subdatasets[*].name", as_name="subdataset"),
        NumericField("$.subdatasets[*].purity", as_name="subdataset_purity"),
        TagField("$.subdatasets[*].conflict_types[*].type", as_name="type"),
        NumericField("$.subdatasets[*].conflict_types[*].purity", as_name="type_purity"),
    ]
    tilt_definition = IndexDefinition(prefix=["info:conflict:tilt"], index_type=IndexType.JSON)

    _ensure_exists_idx(redis, IDX_INFO_CONFLICT_TILT, tilt_definition, tilt_schema)

    octopus_schema = [
        TagField("$.repo", as_name="repo"),
        TagField("$.merge_commit_oid", as_name="merge_commit_oid"),
        NumericField("$.parent_count", as_name="parent_count"),
        TagField("$.octopus_merge_clean", as_name="octopus_merge_clean"),
        TagField("$.pairwise_conflicts[*].merge_result.logical_conflicts[*].type", as_name="type"),
    ]
    octopus_definition = IndexDefinition(prefix=["info:conflict:octopus"], index_type=IndexType.JSON)

    _ensure_exists_idx(redis, IDX_INFO_CONFLICT_OCTOPUS, octopus_definition, octopus_schema)

    schesch_schema = [
        TagField("$.repo", as_name="repo"),
        TagField("$.merge_commit_oid", as_name="merge_commit_oid"),
        TagField("$.human.passed", as_name="human_passed"),
        TagField("$.parents[*].passed", as_name="parent_passed"),
    ]
    schesch_definition = IndexDefinition(prefix=["info:conflict:schesch"], index_type=IndexType.JSON)

    _ensure_exists_idx(redis, IDX_INFO_CONFLICT_SCHESCH, schesch_definition, schesch_schema)

def _ensure_exists_idx(redis: Redis, idx_name: str, definition: IndexDefinition, schema: list) -> None:
    index = redis.ft(idx_name)
    try:
        index.info()
    except ResponseError:
        index.create_index(schema, definition=definition)
