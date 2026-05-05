from pydantic import BaseModel
from datetime import datetime

class Configuration(BaseModel):
    hook_type: str
    playground_version: str
    volume_type: str
    resolution_start: datetime

class ActivePlayground(BaseModel):
    """The top-level object to be stored in Redis."""
    playground_name: str
    configuration: Configuration