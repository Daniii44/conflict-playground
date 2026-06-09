import os
import subprocess
from pathlib import Path

from playground.setup import init_submodules_with_alternates


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )


def configure_identity(repo: Path) -> None:
    git("config", "user.email", "test@example.com", cwd=repo)
    git("config", "user.name", "Test User", cwd=repo)


def test_init_submodules_uses_alternates_without_object_duplication(tmp_path):
    repo_cache_dir = tmp_path / "caches" / "repos"
    cache_repo = repo_cache_dir / "owner" / "sub.git"
    cache_repo.parent.mkdir(parents=True)

    sub_source = tmp_path / "sub-source"
    sub_source.mkdir()
    git("init", cwd=sub_source)
    configure_identity(sub_source)
    (sub_source / "file.txt").write_text("cached contents\n")
    git("add", "file.txt", cwd=sub_source)
    git("commit", "-m", "initial submodule commit", cwd=sub_source)
    submodule_sha = git("rev-parse", "HEAD", cwd=sub_source).stdout.strip()

    git("init", "--bare", str(cache_repo), cwd=tmp_path)
    git("symbolic-ref", "HEAD", "refs/heads/main", cwd=cache_repo)
    git("remote", "add", "origin", str(cache_repo), cwd=sub_source)
    git("push", "origin", "HEAD:main", cwd=sub_source)

    super_repo = tmp_path / "super"
    super_repo.mkdir()
    git("init", cwd=super_repo)
    configure_identity(super_repo)
    (super_repo / ".gitmodules").write_text(
        "\n".join(
            [
                '[submodule "deps/sub"]',
                "\tpath = deps/sub",
                "\turl = https://github.com/owner/sub.git",
                "",
            ]
        )
    )
    git("add", ".gitmodules", cwd=super_repo)
    git("update-index", "--add", "--cacheinfo", f"160000,{submodule_sha},deps/sub", cwd=super_repo)
    git("commit", "-m", "add submodule gitlink", cwd=super_repo)

    init_submodules_with_alternates(
        super_repo,
        "https://github.com/owner/super.git",
        repo_cache_dir,
    )

    assert (super_repo / "deps" / "sub" / "file.txt").read_text() == "cached contents\n"
    assert (
        git("config", "--get", "submodule.deps/sub.url", cwd=super_repo).stdout.strip()
        == str(cache_repo)
    )

    module_objects = super_repo / ".git" / "modules" / "deps" / "sub" / "objects"
    alternates = module_objects / "info" / "alternates"
    alternate_entry = alternates.read_text().strip()

    assert not os.path.isabs(alternate_entry)
    assert (module_objects / alternate_entry).resolve() == (cache_repo / "objects").resolve()
    assert sorted(
        path.relative_to(module_objects)
        for path in module_objects.rglob("*")
        if path.is_file()
    ) == [Path("info/alternates")]
