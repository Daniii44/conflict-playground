from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from common.active_playground_models import Configuration
from common.redis_util import RESOLUTION_CONFLICT_PREFIX


class ProposedResolution(BaseModel):
    commit_sha: str | None = None
    actual_resolution_sha: str | None = None
    git_archive: str | None = None
    error: str | None = None


class ConflictResolution(BaseModel):
    """The top-level resolution object to be stored in Redis."""

    configuration: Configuration
    resolution_end: datetime
    hook_result: dict[str, Any] | None = None
    proposed_resolution: ProposedResolution | None = None


def resolution_record_key(playground_name: str, resolved_at: datetime | None = None) -> str:
    if resolved_at is None:
        resolved_at = datetime.now(timezone.utc)
    timestamp = resolved_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{RESOLUTION_CONFLICT_PREFIX}{playground_name}:{timestamp}"


def resolution_key_parts(resolution_key: str) -> tuple[str, str]:
    suffix = resolution_key.removeprefix(RESOLUTION_CONFLICT_PREFIX)
    playground_name, resolution_timestamp = suffix.rsplit(":", 1)
    return playground_name, resolution_timestamp
