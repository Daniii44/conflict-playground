import os
from pathlib import Path
from typing import Any

import yaml


CONFIG_ENV_VAR = "CONFLICT_PLAYGROUND_CONFIG"
DEFAULT_CONFIG_PATHS = (
    Path("/root/config.yaml"),
    Path.cwd() / "config.yaml",
)


def load_config(config_path: str | None = None) -> dict[str, Any]:
    if config_path is not None:
        paths = (Path(config_path),)
    elif os.environ.get(CONFIG_ENV_VAR):
        paths = (Path(os.environ[CONFIG_ENV_VAR]),)
    else:
        paths = DEFAULT_CONFIG_PATHS

    for path in paths:
        if path.is_file():
            with path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise RuntimeError(f"Configuration file {path} must contain a YAML mapping")
            return data

    return {}
