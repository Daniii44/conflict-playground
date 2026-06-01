from redis import Redis, ResponseError
from redis.commands.search.field import TagField, TextField, NumericField
from redis.commands.search.index_definition import IndexDefinition, IndexType

IDX_INFO_CONFLICT_CORE = "idx:info:conflict:core"
RUNTIME_ACTIVE_PLAYGROUND_PREFIX = "runtime:active_playground:"
EVALUATION_CONFLICT_PREFIX = "evaluation:conflict:"
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
    schema = [
        TagField("$.repo", as_name="repo"),
        TagField("$.merge_commit_oid", as_name="merge_commit_oid"),
        NumericField("$.parent_count", as_name="parent_count"),
        TagField("$.merge_result.logical_conflicts[*].type", as_name="type"),
    ]
    definition = IndexDefinition(prefix=["info:conflict:core"], index_type=IndexType.JSON)

    _ensure_exists_idx(redis, IDX_INFO_CONFLICT_CORE, definition, schema)

def _ensure_exists_idx(redis: Redis, idx_name: str, definition: IndexDefinition, schema: list) -> None:
    index = redis.ft(idx_name)
    try:
        index.info()
    except ResponseError:
        index.create_index(schema, definition=definition)
