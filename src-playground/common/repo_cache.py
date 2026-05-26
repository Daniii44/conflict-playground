import posixpath
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def repo_cache_key(url: str) -> str:
    path = repo_url_path(url)
    parts = [part for part in path.split("/") if part and part not in {".", ".."}]

    if not parts:
        repo_name = Path(url.rstrip("/")).name
        return repo_name if repo_name.endswith(".git") else f"{repo_name}.git"

    if not parts[-1].endswith(".git"):
        parts[-1] = f"{parts[-1]}.git"
    return "/".join(parts)


def repo_url_path(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc:
        return parsed.path

    if ":" in url and "/" not in url.split(":", 1)[0]:
        return url.split(":", 1)[1]

    return url


def resolve_submodule_url(parent_url: str, submodule_url: str) -> str:
    if is_absolute_submodule_url(submodule_url):
        return submodule_url

    if not (submodule_url.startswith("./") or submodule_url.startswith("../")):
        return submodule_url

    parent_base = parent_url.rstrip("/")

    if "://" in parent_base:
        return normalize_url_path(f"{parent_base}/{submodule_url}")

    if ":" in parent_base and "/" not in parent_base.split(":", 1)[0]:
        prefix, path = parent_base.split(":", 1)
        return f"{prefix}:{posixpath.normpath(f'{path}/{submodule_url}')}"

    return posixpath.normpath(f"{parent_base}/{submodule_url}")


def is_absolute_submodule_url(url: str) -> bool:
    return (
        bool(urlsplit(url).scheme)
        or url.startswith("/")
        or (":" in url and "/" not in url.split(":", 1)[0])
    )


def normalize_url_path(url: str) -> str:
    parts = urlsplit(url)
    normalized_path = posixpath.normpath(parts.path)

    if parts.path.endswith("/") and not normalized_path.endswith("/"):
        normalized_path += "/"

    return urlunsplit((parts.scheme, parts.netloc, normalized_path, parts.query, parts.fragment))
