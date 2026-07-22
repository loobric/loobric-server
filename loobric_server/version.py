# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Single source of truth for the server's build identity: version + git commit.

`__version__` is the package version. `commit()` resolves the git commit of the
*running* code — an env override (baked in at build time) wins, else the repo's
`.git` is read directly (no `git` binary required), else `"unknown"`.

`"unknown"` is itself informative: it means the server is an installed build with
no working tree beside it — exactly the signal you want when diagnosing "is this
server actually running my checkout?"
"""
import os
from functools import lru_cache
from pathlib import Path

__version__ = "0.3.6"


def build_info() -> dict:
    """Version + commit, as returned by the unauthenticated /version endpoint."""
    return {"version": __version__, "commit": commit()}


@lru_cache(maxsize=1)
def commit() -> str:
    """Short git commit of the running code, or 'unknown'.

    Resolution order: the LOOBRIC_COMMIT env var (set by Docker/CI builds), then
    the repository's `.git` walking up from this file, then 'unknown'. Every file
    read is guarded — a missing or unexpected `.git` degrades to 'unknown', never
    an exception."""
    env = os.environ.get("LOOBRIC_COMMIT")
    if env:
        return env.strip()[:12]
    here = Path(__file__).resolve()
    for parent in here.parents:
        git = parent / ".git"
        if git.exists():
            try:
                return _read_git_commit(git)
            except OSError:
                return "unknown"
    return "unknown"


def _read_git_commit(git: Path) -> str:
    """Read the current commit sha from a `.git` directory (or worktree file)."""
    # A linked worktree stores `.git` as a file: 'gitdir: <path>'.
    if git.is_file():
        gitdir = git.read_text().split(":", 1)[1].strip()
        git = (git.parent / gitdir).resolve()
    head = (git / "HEAD").read_text().strip()
    if not head.startswith("ref:"):
        return head[:12]                                  # detached HEAD: sha directly
    ref = head.split(":", 1)[1].strip()
    loose = git / ref
    if loose.exists():
        return loose.read_text().strip()[:12]
    # Packed refs (no loose ref file) — find the line ending in this ref.
    packed = git / "packed-refs"
    if packed.exists():
        for line in packed.read_text().splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0][:12]
    return "unknown"
