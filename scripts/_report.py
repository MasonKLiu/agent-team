"""Shared violation format and path helpers for every check (RFC-001 §1.2)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class Violation:
    rule_id: str
    file: str
    line: int
    root_cause: str
    remediation: str

    def key(self) -> tuple[str, str]:
        return (self.rule_id, self.file)

    def render(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        return (
            f"[{self.rule_id}] {where}\n"
            f"  Root Cause: {self.root_cause}\n"
            f"  Remediation: {self.remediation}"
        )


def normalize_posix_path(raw: str) -> tuple[str, bool]:
    """Normalize a repo-relative path to POSIX form and return (normalized, is_dir)."""
    cleaned = raw.strip().replace("\\", "/")
    is_dir = cleaned.endswith("/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.strip("/")
    if not cleaned:
        return ("", is_dir)
    normalized = PurePosixPath(cleaned).as_posix()
    return (normalized, is_dir)


def paths_overlap(raw_a: str, raw_b: str) -> bool:
    """Return True if two repo-relative file or directory entries overlap."""
    a, a_dir = normalize_posix_path(raw_a)
    b, b_dir = normalize_posix_path(raw_b)
    if not a or not b:
        return False
    if a == b:
        return True
    if a_dir and b.startswith(a + "/"):
        return True
    if b_dir and a.startswith(b + "/"):
        return True
    return False


def path_matches_allowlist(file_path: str, allowlist: list[str]) -> bool:
    """Return True if a changed file falls inside a PLAN.md Files allowlist."""
    norm_file, _ = normalize_posix_path(file_path)
    if not norm_file:
        return False
    for entry in allowlist:
        norm_entry, is_dir = normalize_posix_path(entry)
        if not norm_entry:
            continue
        if norm_file == norm_entry:
            return True
        if is_dir and norm_file.startswith(norm_entry + "/"):
            return True
    return False


def print_report(title: str, violations: list[Violation], notes: list[str] | None = None) -> int:
    for note in notes or []:
        print(note)
    if not violations:
        print(f"{title}: OK")
        return 0
    for v in sorted(violations, key=lambda v: (v.file, v.line, v.rule_id)):
        print(v.render())
    print(f"{title}: {len(violations)} violation(s)")
    return 1
