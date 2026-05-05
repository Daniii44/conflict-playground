from redis import Redis, ResponseError
from redis.commands.search.field import TagField, TextField, NumericField
from redis.commands.search.index_definition import IndexDefinition, IndexType

IDX_INFO_CONFLICT = "idx:info:conflict"

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
        TagField("repo"),
        TagField("sha"),
        NumericField("parent_count"),
        NumericField("conflict_count"),
        TextField("conflict_difficulty")
    ]
    definition = IndexDefinition(prefix=["info:conflict"], index_type=IndexType.HASH)

    _ensure_exists_idx(redis, IDX_INFO_CONFLICT, definition, schema)

def _ensure_exists_idx(redis: Redis, idx_name: str, definition: IndexDefinition, schema: list) -> None:
    index = redis.ft(idx_name)
    try:
        index.info()
    except ResponseError:
        index.create_index(schema, definition=definition)