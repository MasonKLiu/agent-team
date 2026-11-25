"""Cross-platform deterministic tool-execution guard hook for Claude Code & Gemini CLI.

Invoked by:
  - Claude Code PreToolUse hook:  python scripts/guard_hook.py --adapter claude
  - Gemini CLI BeforeTool hook:   python scripts/guard_hook.py --adapter gemini

Blocks:
  1. Direct Edit/Write/replace/write_file mutations to .governance/baseline.json
  2. Shell commands invoking --write-baseline or mutating .governance/baseline.json
  3. Destructive git operations (force push, hard reset, clean -fd)
  4. Optional read-only shell enforcement (--read-only or AGENT_TEAM_READ_ONLY=1)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "write_file", "replace"}
SHELL_TOOLS = {"Bash", "run_shell_command"}

PROTECTED_BASELINE_RE = re.compile(r"(?:^|[/\\])\.governance[/\\]baseline\.json\b")
WRITE_BASELINE_FLAG_RE = re.compile(r"--write-baseline\b")
SHELL_DESTRUCTIVE_PATTERNS = [
    (
        re.compile(r"\bgit\s+push\b[^\n]*(?:\s--force(?:-with-lease)?\b|\s-f\b)"),
        "GUARD-001",
        "Force pushing is prohibited by team governance.",
        "Use a normal push to a feature branch or ask the user explicitly.",
    ),
    (
        re.compile(r"\bgit\s+reset\s+--hard\b"),
        "GUARD-002",
        "Hard reset discards uncommitted work and is prohibited in automated agent runs.",
        "Inspect changes with 'git status' / 'git diff' or use a dedicated task worktree.",
    ),
    (
        re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"),
        "GUARD-003",
        "Forced 'git clean' deletes untracked files irreversibly.",
        "Remove only specific temporary files you created, or ask the user.",
    ),
]
SHELL_BASELINE_MUTATION_RE = re.compile(
    r"(?:>>?|\btee\b|\bsed\s+-i|\brm\b|\bmv\b|\bcp\b|\bpython(?:3)?\s+-c\b|\bnode\s+-e\b|\bSet-Content\b|\bOut-File\b)"
    r"[^\n]*\.governance[/\\]baseline\.json"
    r"|\.governance[/\\]baseline\.json[^\n]*(?:>>?|\btee\b)",
    re.IGNORECASE,
)
READ_ONLY_MUTATION_PATTERNS = [
    re.compile(r"(?:^|[^0-9&])>>?\s*[^\s&]"),
    re.compile(r"\b(?:rm|mv|cp|touch|mkdir|rmdir|tee|chmod|chown)\b"),
    re.compile(r"\bsed\s+-i\b"),
    re.compile(r"\bgit\s+(?:add|commit|checkout|switch|merge|rebase|cherry-pick|apply|reset|clean|stash|rm|mv)\b"),
    re.compile(r"\b(?:Set-Content|Add-Content|Out-File|Remove-Item|Move-Item|Copy-Item|New-Item)\b", re.IGNORECASE),
]


def _extract_target_path(tool_input: dict) -> str:
    for key in ("file_path", "path", "target_file", "TargetFile", "Path"):
        val = tool_input.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _extract_command(tool_input: dict) -> str:
    for key in ("command", "CommandLine", "cmd"):
        val = tool_input.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _format_block(rule_id: str, root_cause: str, remediation: str) -> str:
    return (
        f"[{rule_id}] Hook Guard\n"
        f"  Root Cause: {root_cause}\n"
        f"  Remediation: {remediation}"
    )


def evaluate_event(
    event: dict,
    *,
    read_only: bool = False,
    allow_baseline_write: bool = False,
) -> tuple[bool, str | None]:
    """Return (allowed, reason_if_blocked)."""
    tool_name = str(event.get("tool_name") or event.get("name") or "")
    tool_input = event.get("tool_input") or event.get("args") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    if tool_name in WRITE_TOOLS:
        if read_only:
            return (
                False,
                _format_block(
                    "GUARD-004",
                    f"Read-only role attempted write tool '{tool_name}'.",
                    "Read-only roles (scout, verifier) must never modify files.",
                ),
            )
        target = _extract_target_path(tool_input)
        if target and PROTECTED_BASELINE_RE.search(target) and not allow_baseline_write:
            return (
                False,
                _format_block(
                    "GUARD-005",
                    "Direct modification of .governance/baseline.json violates the RFC-001 §3.1 ratchet.",
                    "Fix the underlying violation instead of editing baseline.json. Only humans may refresh the baseline.",
                ),
            )
        return (True, None)

    if tool_name in SHELL_TOOLS:
        cmd = _extract_command(tool_input)
        if not cmd:
            return (True, None)
        if WRITE_BASELINE_FLAG_RE.search(cmd) and not allow_baseline_write:
            return (
                False,
                _format_block(
                    "GUARD-005",
                    "Running '--write-baseline' is forbidden for autonomous agents (RFC-001 §3.1).",
                    "Run 'python scripts/check_governance.py' without '--write-baseline' and fix reported violations.",
                ),
            )
        if SHELL_BASELINE_MUTATION_RE.search(cmd) and not allow_baseline_write:
            return (
                False,
                _format_block(
                    "GUARD-005",
                    "Shell command attempts to mutate .governance/baseline.json.",
                    "Do not alter baseline.json via shell; fix the code violation instead.",
                ),
            )
        for pattern, rule_id, root_cause, remediation in SHELL_DESTRUCTIVE_PATTERNS:
            if pattern.search(cmd):
                return (False, _format_block(rule_id, root_cause, remediation))
        if read_only:
            for pattern in READ_ONLY_MUTATION_PATTERNS:
                if pattern.search(cmd):
                    return (
                        False,
                        _format_block(
                            "GUARD-004",
                            f"Read-only role attempted potentially mutating shell command: {cmd[:120]}",
                            "Use read-only inspection or test/check commands that do not modify workspace files.",
                        ),
                    )
        return (True, None)

    return (True, None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adapter", choices=["claude", "gemini"], default="claude")
    parser.add_argument("--read-only", action="store_true", help="enforce read-only shell guard")
    args = parser.parse_args()

    raw = sys.stdin.read().strip()
    try:
        event = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        event = {}

    read_only = args.read_only or os.environ.get("AGENT_TEAM_READ_ONLY") == "1"
    allow_baseline = os.environ.get("ALLOW_BASELINE_WRITE") == "1"
    allowed, reason = evaluate_event(event, read_only=read_only, allow_baseline_write=allow_baseline)

    if args.adapter == "gemini":
        if allowed:
            print(json.dumps({"decision": "allow"}))
        else:
            print(
                json.dumps(
                    {
                        "decision": "deny",
                        "reason": reason,
                        "systemMessage": "Blocked by scripts/guard_hook.py",
                    }
                )
            )
        return 0

    if not allowed:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
