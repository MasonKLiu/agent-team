"""Deterministic PLAN.md Files-allowlist verifier (Scope Gate).

Ensures a builder task only modifies files declared in its PLAN.md 'Files:' field,
and never silently alters .governance/baseline.json or unauthorized governance files.

Usage:
  python scripts/verify_scope.py --task T-001
  python scripts/verify_scope.py --task T-001 --base main
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _report import Violation, normalize_posix_path, path_matches_allowlist, print_report
from check_team import parse_plan


def git_changed_files(root: Path, base_ref: str | None = None, include_working_tree: bool = True) -> set[str]:
    files: set[str] = set()
    if base_ref:
        res = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        for line in res.stdout.splitlines():
            if line.strip():
                files.add(normalize_posix_path(line)[0])
    if include_working_tree:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        for line in res.stdout.splitlines():
            if len(line) < 4:
                continue
            entry = line[3:].strip()
            if " -> " in entry:
                entry = entry.split(" -> ", 1)[1].strip()
            if entry:
                files.add(normalize_posix_path(entry)[0])
    return files


def check_scope(
    root: Path,
    task_id: str,
    changed: set[str],
    *,
    allow_baseline: bool = False,
) -> list[Violation]:
    plan_path = root / "PLAN.md"
    if not plan_path.exists():
        return [
            Violation(
                "SCOPE-001",
                "PLAN.md",
                0,
                "PLAN.md is missing; task scope cannot be verified.",
                "Create PLAN.md and declare the task with its Files allowlist.",
            )
        ]

    tasks = {t["id"]: t for t in parse_plan(plan_path.read_text(encoding="utf-8"))}
    task = tasks.get(task_id)
    if task is None:
        return [
            Violation(
                "SCOPE-001",
                "PLAN.md",
                0,
                f"Task '{task_id}' was not found in PLAN.md.",
                f"Add '## {task_id}: ...' with a Files allowlist to PLAN.md, or pass the right --task ID.",
            )
        ]

    allowlist = task["files"]
    out: list[Violation] = []
    for raw_file in sorted(changed):
        norm, _ = normalize_posix_path(raw_file)
        if not norm:
            continue
        if norm == ".governance/baseline.json" and not allow_baseline:
            out.append(
                Violation(
                    "SCOPE-002",
                    norm,
                    0,
                    f"Task {task_id} modified .governance/baseline.json, which agents are forbidden from altering (RFC-001 §4.1).",
                    "Revert changes to .governance/baseline.json and fix the underlying violation.",
                )
            )
            continue
        if not path_matches_allowlist(norm, allowlist):
            out.append(
                Violation(
                    "SCOPE-001",
                    norm,
                    0,
                    f"Task {task_id} modified '{norm}', which is outside its PLAN.md Files allowlist ({', '.join(allowlist)}).",
                    f"Revert '{norm}', or ask the orchestrator to update {task_id}'s Files field in PLAN.md before editing it.",
                )
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=Path(__file__).resolve().parent.parent, type=Path)
    parser.add_argument("--task", required=True, help="PLAN.md task ID, e.g. T-001")
    parser.add_argument("--base", help="optional git base ref (e.g. main or HEAD~1) to diff against HEAD")
    parser.add_argument("--committed-only", action="store_true", help="ignore uncommitted working tree files")
    parser.add_argument("--allow-baseline", action="store_true", help="allow baseline.json changes (human only)")
    args = parser.parse_args()

    root = args.root.resolve()
    changed = git_changed_files(root, base_ref=args.base, include_working_tree=not args.committed_only)
    return print_report(
        f"Scope gate ({args.task})",
        check_scope(root, args.task, changed, allow_baseline=args.allow_baseline),
    )


if __name__ == "__main__":
    sys.exit(main())
