#!/usr/bin/env python3

import argparse
import os
import subprocess
import yaml
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# playbook-start <playbook>

@dataclass
class Playground:
    repo_name: str
    merge_sha: str


def get_repo_name_from_url(url: str) -> str:
    """Extract repo name from URL like https://github.com/git/git.git -> git"""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    # Get the last part and remove .git suffix
    repo_name = path.split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    return repo_name


def get_dirty_merge_sha(repo_name: str, index: int) -> str:
    """Get merge SHA at given index using info-dirty-merges-sha command"""
    result = subprocess.run(
        ["info-dirty-merges-sha", repo_name, str(index)],
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout.strip()


def load_playbook(playbook_path: str) -> list[Playground]:
    """Load playbook and create Playground objects"""
    with open(playbook_path, 'r') as f:
        data = yaml.safe_load(f)

    playgrounds = []
    for source in data['playbook']['sources']:
        repo_url = source['repo_url']
        limit = source.get('limit', 1)
        repo_name = get_repo_name_from_url(repo_url)

        for i in range(limit):
            merge_sha = get_dirty_merge_sha(repo_name, i)
            playgrounds.append(Playground(repo_name=repo_name, merge_sha=merge_sha))

    return playgrounds


def main():
    parser = argparse.ArgumentParser(description="Start a playbook")
    parser.add_argument("playbook", help="Name of the playbook", nargs='?', default="default")
    parser.add_argument("--skip", type=int, default=0, help="Skip the first N playgrounds")
    args = parser.parse_args()

    playbooks = os.environ.get("PLAYBOOKS")
    playbook_path = f"{playbooks}/{args.playbook}.yaml"
    playgrounds = load_playbook(playbook_path)

    print(f"Loaded {len(playgrounds)} playgrounds:")
    for pg in playgrounds:
        print(f"  - {pg.repo_name}: {pg.merge_sha}")

    print("\nStarting playbook execution...")
    for i, pg in enumerate(playgrounds, 1):
        if args.skip > 0 and i <= args.skip:
            print(f"[{i}/{len(playgrounds)}] Skipping {pg.repo_name} ({pg.merge_sha})")
            continue
        print(f"\n[{i}/{len(playgrounds)}] Setting up playground for {pg.repo_name} ({pg.merge_sha})")
        result = subprocess.run(
            ["playgrounds-setup", pg.repo_name, pg.merge_sha], 
            check=True, 
            capture_output=True, 
            text=True
        )
        playground_name = result.stdout.strip()
        print(f"Created Playground: {playground_name}")

        print("Dispatching task to hook")
        subprocess.run(["hook-dispatch-task", playground_name], check=True)

        print("Evaluating Result")
        subprocess.run(["evaluation-assess", playground_name], check=True)
        
        print(f"Cleaning up playground for {pg.repo_name}...")
        subprocess.run(["playgrounds-rm", pg.repo_name], check=True)

    print("\nPlaybook execution complete!")


if __name__ == "__main__":
    main()
