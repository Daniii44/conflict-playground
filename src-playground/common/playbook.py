from pathlib import Path

import yaml

from common.repo_cache import repo_cache_key


def resolve_playbook_path(playbook: str, playbooks_dir: Path) -> Path:
    playbook_path = Path(playbook)
    if playbook_path.is_file():
        return playbook_path

    if playbook_path.suffix in {".yaml", ".yml"}:
        return playbooks_dir / playbook_path

    return playbooks_dir / f"{playbook}.yaml"


def load_playbook_data(playbook_path: Path) -> dict:
    with playbook_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_playbook_repo_urls(playbook_path: Path) -> list[str]:
    data = load_playbook_data(playbook_path)
    sources = data.get("playbook", {}).get("sources") or []
    return [
        source["repo_url"]
        for source in sources
        if isinstance(source, dict) and source.get("repo_url")
    ]


def load_playbook_repos(playbook_path: Path) -> list[str]:
    repos = []
    seen = set()
    for repo_url in load_playbook_repo_urls(playbook_path):
        repo_name = repo_cache_key(repo_url)
        if repo_name in seen:
            continue

        repos.append(repo_name)
        seen.add(repo_name)

    return repos
