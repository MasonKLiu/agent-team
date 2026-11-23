"""Shared violation format for every check (RFC-001 §1.2: Rule ID, Root Cause, Exact Remediation)."""

from __future__ import annotations

from dataclasses import dataclass


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
