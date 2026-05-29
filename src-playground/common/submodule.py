import configparser
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from common.git_util import capture_git


@dataclass(frozen=True)
class SubmoduleReference:
    name: str
    path: str | None
    url: str
    blob: str
    present_in_head: bool = False

    @property
    def key(self) -> tuple[str, str | None, str]:
        return (self.name, self.path, self.url)


def format_breadcrumbs(breadcrumbs: tuple[str, ...]) -> str:
    return " > ".join(breadcrumbs)


def gitmodules_blobs(repo_path: Path, breadcrumbs: tuple[str, ...]) -> list[str]:
    result = capture_git(
        f"--git-dir={repo_path}",
        "rev-list",
        "--objects",
        "--all",
        "--",
        ".gitmodules",
        check=False,
    )

    if result.returncode != 0:
        logger.warning(
            "[{}] Failed to inspect .gitmodules history for {}",
            format_breadcrumbs(breadcrumbs),
            repo_path,
        )
        return []

    blobs = {
        line.split(" ", 1)[0]
        for line in result.stdout.splitlines()
        if line.endswith(" .gitmodules")
    }
    return sorted(blobs)


def submodule_references(
    repo_path: Path,
    blob: str,
    breadcrumbs: tuple[str, ...],
) -> list[SubmoduleReference]:
    result = capture_git(
        f"--git-dir={repo_path}",
        "cat-file",
        "-p",
        blob,
        check=False,
    )

    if result.returncode != 0:
        logger.warning(
            "[{}] Failed to read .gitmodules blob {}",
            format_breadcrumbs(breadcrumbs),
            blob,
        )
        return []

    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(result.stdout)
    except configparser.Error as e:
        logger.warning(
            "[{}] Failed to parse .gitmodules blob {}: {}",
            format_breadcrumbs(breadcrumbs),
            blob,
            e,
        )
        return []

    references = []
    for section in parser.sections():
        if not section.startswith("submodule ") or not parser.has_option(section, "url"):
            continue

        name = section.removeprefix("submodule ").strip().strip('"')
        references.append(
            SubmoduleReference(
                name=name,
                path=parser.get(section, "path", fallback=None),
                url=parser.get(section, "url"),
                blob=blob,
            )
        )

    return references


def all_submodule_references(
    repo_path: Path,
    breadcrumbs: tuple[str, ...],
) -> list[SubmoduleReference]:
    head_references = head_submodule_references(repo_path, breadcrumbs)
    head_keys = {reference.key for reference in head_references}
    references_by_key: dict[tuple[str, str | None, str], SubmoduleReference] = {}
    for reference in head_references:
        references_by_key[reference.key] = reference

    for blob in gitmodules_blobs(repo_path, breadcrumbs):
        for reference in submodule_references(repo_path, blob, breadcrumbs):
            references_by_key.setdefault(
                reference.key,
                SubmoduleReference(
                    name=reference.name,
                    path=reference.path,
                    url=reference.url,
                    blob=reference.blob,
                    present_in_head=reference.key in head_keys,
                ),
            )

    return list(references_by_key.values())


def head_submodule_references(
    repo_path: Path,
    breadcrumbs: tuple[str, ...],
) -> list[SubmoduleReference]:
    result = capture_git(
        f"--git-dir={repo_path}",
        "rev-parse",
        "HEAD:.gitmodules",
        check=False,
    )
    if result.returncode != 0:
        return []

    blob = result.stdout.strip()
    if not blob:
        return []

    return [
        SubmoduleReference(
            name=reference.name,
            path=reference.path,
            url=reference.url,
            blob=reference.blob,
            present_in_head=True,
        )
        for reference in submodule_references(repo_path, blob, breadcrumbs)
    ]


def submodule_urls(repo_path: Path, blob: str, breadcrumbs: tuple[str, ...]) -> list[str]:
    return [
        reference.url
        for reference in submodule_references(repo_path, blob, breadcrumbs)
    ]
