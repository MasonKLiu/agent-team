"""Cross-platform Git worktree lifecycle helper for Claude & Gemini orchestrators.

Provides deterministic task isolation even on AI CLIs without native worktree support (e.g. Gemini CLI),
and standardizes the Worktree -> Verifier -> Merge handoff protocol.

Usage:
  python scripts/worktree_ops.py create T-001 [--base HEAD]
  python scripts/worktree_ops.py status
  python scripts/worktree_ops.py merge T-001 [--keep-worktree]
  python scripts/worktree_ops.py cleanup T-001
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from check_team import parse_plan

TASK_ID_RE = re.compile(r"^T-\d+$")


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)


def validate_task_id(root: Path, task_id: str) -> None:
    if not TASK_ID_RE.match(task_id):
        raise SystemExit(f"Invalid task ID '{task_id}'. Expected format: T-001.")
    plan_path = root / "PLAN.md"
    if not plan_path.exists():
        raise SystemExit("PLAN.md not found.")
    tasks = {t["id"] for t in parse_plan(plan_path.read_text(encoding="utf-8"))}
    if task_id not in tasks:
        raise SystemExit(f"Task '{task_id}' is not defined in PLAN.md.")


def cmd_create(root: Path, task_id: str, base_ref: str) -> int:
    validate_task_id(root, task_id)
    worktrees_dir = root / ".agent-team" / "worktrees"
    worktrees_dir.mkdir(parents=True, exist_ok=True)
    wt_path = worktrees_dir / task_id
    branch = f"task/{task_id}"
    if wt_path.exists():
        raise SystemExit(f"Worktree already exists: {wt_path}")
    run_git(root, "worktree", "add", "-b", branch, str(wt_path), base_ref)
    base_commit = run_git(root, "rev-parse", base_ref).stdout.strip()
    info = {
        "task_id": task_id,
        "branch": branch,
        "worktree_path": wt_path.as_posix(),
        "base_ref": base_ref,
        "base_commit": base_commit,
    }
    print(json.dumps(info, indent=2))
    return 0


def cmd_status(root: Path) -> int:
    out = run_git(root, "worktree", "list").stdout.strip()
    print(out or "(no worktrees)")
    return 0


def cmd_merge(root: Path, task_id: str, keep_worktree: bool) -> int:
    if not TASK_ID_RE.match(task_id):
        raise SystemExit(f"Invalid task ID '{task_id}'. Expected format: T-001.")
    branch = f"task/{task_id}"
    wt_path = root / ".agent-team" / "worktrees" / task_id
    if wt_path.exists():
        dirty = run_git(wt_path, "status", "--porcelain").stdout.strip()
        if dirty:
            raise SystemExit(f"Worktree {wt_path} has uncommitted changes; commit or discard before merge.")
    run_git(root, "merge", "--no-ff", branch, "-m", f"merge({task_id}): integrate verified task branch")
    if not keep_worktree:
        if wt_path.exists():
            run_git(root, "worktree", "remove", str(wt_path))
        run_git(root, "branch", "-d", branch)
    print(f"Merged {branch} successfully. If >= 2 parallel tasks were merged, run integration checks now.")
    return 0


def cmd_cleanup(root: Path, task_id: str) -> int:
    if not TASK_ID_RE.match(task_id):
        raise SystemExit(f"Invalid task ID '{task_id}'. Expected format: T-001.")
    branch = f"task/{task_id}"
    wt_path = root / ".agent-team" / "worktrees" / task_id
    if wt_path.exists():
        run_git(root, "worktree", "remove", str(wt_path))
    branches = run_git(root, "branch", "--list", branch).stdout.strip()
    if branches:
        run_git(root, "branch", "-d", branch)
    print(f"Cleaned up worktree and branch for {task_id}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=Path(__file__).resolve().parent.parent, type=Path)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="create an isolated worktree for a PLAN.md task")
    p_create.add_argument("task_id")
    p_create.add_argument("--base", default="HEAD")

    sub.add_parser("status", help="list active git worktrees")

    p_merge = sub.add_parser("merge", help="merge a verified task branch with --no-ff and clean up")
    p_merge.add_argument("task_id")
    p_merge.add_argument("--keep-worktree", action="store_true")

    p_cleanup = sub.add_parser("cleanup", help="remove a task worktree and merged branch")
    p_cleanup.add_argument("task_id")

    args = parser.parse_args()
    root = args.root.resolve()
    if args.cmd == "create":
        return cmd_create(root, args.task_id, args.base)
    if args.cmd == "status":
        return cmd_status(root)
    if args.cmd == "merge":
        return cmd_merge(root, args.task_id, args.keep_worktree)
    if args.cmd == "cleanup":
        return cmd_cleanup(root, args.task_id)
    return 1


if __name__ == "__main__":
    sys.exit(main())
