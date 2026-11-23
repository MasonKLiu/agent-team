"""Structural checks for the agent team itself (subagents, PLAN.md, STATE.md).

Zero dependencies. Output follows RFC-001 §1.2 (Rule ID, Root Cause, Remediation).

Usage:
  python scripts/check_team.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _report import Violation, print_report

WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
READ_ONLY_AGENTS = {"scout", "verifier"}
PLAN_STATUSES = {"todo", "doing", "verify", "done", "blocked"}
STATE_SECTIONS = ["Goal", "Done (verified PASS)", "Failed / blocked", "Rules learned", "Next", "Last session"]


def parse_frontmatter(text: str) -> dict[str, str] | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fields = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def check_agents(root: Path) -> list[Violation]:
    out = []
    names: set[str] = set()
    agents_dir = root / ".claude" / "agents"
    files = sorted(agents_dir.glob("*.md")) if agents_dir.exists() else []
    if not files:
        out.append(Violation(
            "TEAM-001", ".claude/agents", 0,
            "No subagents defined; the orchestrator has no team to delegate to.",
            "Add at least scout.md, builder.md and verifier.md under .claude/agents/.",
        ))
    for path in files:
        r = path.relative_to(root).as_posix()
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        if fm is None:
            out.append(Violation(
                "TEAM-001", r, 1, "Subagent file has no YAML frontmatter.",
                "Start the file with '---', then name, description, model, tools, then '---'.",
            ))
            continue
        for key in ("name", "description", "model", "tools"):
            if not fm.get(key):
                cause = {
                    "model": "Without a model line the subagent inherits the expensive orchestrator model.",
                    "tools": "Without a tools line the subagent gets every tool, breaking least privilege.",
                }.get(key, f"Frontmatter is missing '{key}'.")
                out.append(Violation(
                    "TEAM-001", r, 1, cause,
                    f"Add '{key}: ...' to the frontmatter (model: haiku | sonnet | opus).",
                ))
        tools = {t.strip() for t in fm.get("tools", "").split(",") if t.strip()}
        name = fm.get("name", path.stem)
        names.add(name)
        if name in READ_ONLY_AGENTS and tools & WRITE_TOOLS:
            out.append(Violation(
                "TEAM-002", r, 1,
                f"'{name}' must be read-only but has {', '.join(sorted(tools & WRITE_TOOLS))}; a verifier that can edit can grade its own fixes.",
                f"Remove {', '.join(sorted(tools & WRITE_TOOLS))} from the tools line.",
            ))
        if tools & WRITE_TOOLS and fm.get("isolation") != "worktree":
            out.append(Violation(
                "TEAM-003", r, 1,
                f"'{name}' can write files but is not isolated; parallel builders would overwrite each other.",
                "Add 'isolation: worktree' to the frontmatter.",
            ))
    if files and "verifier" not in names:
        out.append(Violation(
            "TEAM-002", ".claude/agents", 0,
            "No verifier subagent; builders would be graded by the orchestrator or themselves.",
            "Add .claude/agents/verifier.md with read-only tools.",
        ))
    return out


def parse_plan(text: str) -> list[dict]:
    tasks = []
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)
    for header in re.finditer(r"^## (T-\d+)\b.*$", text, flags=re.MULTILINE):
        end = re.compile(r"^## ", re.MULTILINE).search(text, header.end())
        block = text[header.end(): end.start() if end else len(text)]
        task = {"id": header.group(1), "line": text[: header.start()].count("\n") + 1,
                "status": None, "files": [], "acceptance": []}
        in_acceptance = False
        for line in block.splitlines():
            fm = re.match(r"\s*-\s*(Status|Files|Acceptance|Owner|Depends on):\s*(.*)", line)
            if fm:
                key, value = fm.group(1), fm.group(2).strip()
                in_acceptance = key == "Acceptance"
                if key == "Status":
                    task["status"] = value
                elif key == "Files":
                    task["files"] = [f.strip() for f in value.split(",") if f.strip()]
                elif key == "Acceptance" and value:
                    task["acceptance"].append(value)
            elif in_acceptance and re.match(r"\s{2,}-\s*\S", line):
                task["acceptance"].append(line.strip()[1:].strip())
        tasks.append(task)
    return tasks


def check_plan(root: Path) -> list[Violation]:
    out = []
    path = root / "PLAN.md"
    if not path.exists():
        return [Violation("TEAM-004", "PLAN.md", 0, "PLAN.md is missing.", "Create PLAN.md from the template in README.md.")]
    tasks = parse_plan(path.read_text(encoding="utf-8"))
    seen = set()
    for t in tasks:
        if t["id"] in seen:
            out.append(Violation("TEAM-004", "PLAN.md", t["line"], f"Duplicate task id {t['id']}.", "Give every task a unique T-### id."))
        seen.add(t["id"])
        if t["status"] not in PLAN_STATUSES:
            out.append(Violation(
                "TEAM-004", "PLAN.md", t["line"], f"{t['id']} has status '{t['status']}'.",
                f"Set '- Status:' to one of {', '.join(sorted(PLAN_STATUSES))}.",
            ))
        if not t["files"]:
            out.append(Violation(
                "TEAM-004", "PLAN.md", t["line"], f"{t['id']} has no Files; parallel safety cannot be checked.",
                "Add '- Files: path/a, path/b' listing every file the task may touch.",
            ))
        if not t["acceptance"]:
            out.append(Violation(
                "TEAM-004", "PLAN.md", t["line"], f"{t['id']} has no acceptance criteria; the verifier has nothing to check.",
                "Add '- Acceptance:' with at least one runnable command or observable result.",
            ))
    active = [t for t in tasks if t["status"] == "doing"]
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            overlap = set(a["files"]) & set(b["files"])
            if overlap:
                out.append(Violation(
                    "TEAM-004", "PLAN.md", b["line"],
                    f"{a['id']} and {b['id']} are both 'doing' and share {', '.join(sorted(overlap))}.",
                    f"Set one of them back to 'todo' and add 'Depends on: {a['id']}' to it.",
                ))
    return out


def known_check_ids(root: Path) -> str:
    corpus = []
    for folder in ("scripts", ".governance", "eslint-rules"):
        base = root / folder
        if base.exists():
            corpus += [p.read_text(encoding="utf-8", errors="replace") for p in base.rglob("*") if p.is_file()]
    for name in ("eslint.config.js", "eslint.config.mjs", ".eslintrc.json", ".dependency-cruiser.js", ".dependency-cruiser.cjs"):
        p = root / name
        if p.exists():
            corpus.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(corpus)


def check_state(root: Path) -> list[Violation]:
    out = []
    path = root / "STATE.md"
    if not path.exists():
        return [Violation("TEAM-005", "STATE.md", 0, "STATE.md is missing; the team loses memory between sessions.", "Create STATE.md from the template.")]
    text = path.read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+?)\s*$", text, flags=re.MULTILINE)
    for section in STATE_SECTIONS:
        if section not in headings:
            out.append(Violation("TEAM-005", "STATE.md", 0, f"Section '## {section}' is missing.", f"Add '## {section}' to STATE.md."))
    m = re.search(r"^## Rules learned\s*$(.*?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL)
    if m:
        corpus = known_check_ids(root)
        start = text[: m.start(1)].count("\n") + 1
        for offset, line in enumerate(m.group(1).splitlines()):
            if not re.match(r"\s*[-*]\s+\S", line):
                continue
            check = re.search(r"Check:\s*(\S+)", line)
            if not check:
                out.append(Violation(
                    "TEAM-005", "STATE.md", start + offset,
                    "Rule learned exists only as prose; prompt patching is forbidden (RFC-001 §1.1).",
                    "Add a deterministic check (scripts/check_governance.py, ESLint rule, or test) and append 'Check: <RULE-ID>' to this line.",
                ))
            elif check.group(1) not in corpus:
                out.append(Violation(
                    "TEAM-005", "STATE.md", start + offset,
                    f"Rule learned points to check '{check.group(1)}', which is not defined in scripts/, .governance/ or lint config.",
                    f"Implement {check.group(1)} as a deterministic check, or fix the id.",
                ))
    return out


def check_entrypoints(root: Path) -> list[Violation]:
    out = []
    claude = root / "CLAUDE.md"
    text = claude.read_text(encoding="utf-8") if claude.exists() else ""
    for ref in ("AGENTS.md", "docs/standards/RFC-001.md"):
        if ref not in text:
            out.append(Violation(
                "TEAM-006", "CLAUDE.md", 0, f"The orchestrator prompt does not load {ref}.",
                f"Add '@{ref}' to CLAUDE.md.",
            ))
    return out


def run(root: Path) -> list[Violation]:
    return check_agents(root) + check_plan(root) + check_state(root) + check_entrypoints(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=Path(__file__).resolve().parent.parent, type=Path)
    args = parser.parse_args()
    return print_report("Agent team", run(args.root.resolve()))


if __name__ == "__main__":
    sys.exit(main())
