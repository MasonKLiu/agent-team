"""Structural checks for the 80/20 agent team (adapters, hooks, PLAN.md, STATE.md).

Zero dependencies. Output follows RFC-001 §1.2 (Rule ID, Root Cause, Remediation).

Rules:
  TEAM-001  Subagent metadata, explicit model, and tools across all enabled adapters
  TEAM-002  Read-only role boundaries (scout, verifier) and shell guard hook enforcement
  TEAM-003  Write-capable role isolation (Claude native worktree / Gemini worktree_ops)
  TEAM-004  PLAN.md structure, valid Owner, Depends on DAG/readiness, and active overlap
  TEAM-005  STATE.md sections (including Failure log) and exact Check ID verification
  TEAM-006  Entrypoints (CLAUDE.md, GEMINI.md) and settings security (no baseline loophole)
  TEAM-007  80/20 adapter synchronization (no drift from .agent-team/prompts/*.md)

Usage:
  python scripts/check_team.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _report import Violation, paths_overlap, print_report
import sync_adapters

CLAUDE_WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
GEMINI_WRITE_TOOLS = {"write_file", "replace"}
ALL_WRITE_TOOLS = CLAUDE_WRITE_TOOLS | GEMINI_WRITE_TOOLS
SHELL_TOOLS = {"Bash", "run_shell_command"}
READ_ONLY_AGENTS = {"scout", "verifier"}
PLAN_STATUSES = {"todo", "doing", "verify", "done", "blocked"}
ACTIVE_STATUSES = {"doing", "verify"}
VALID_OWNERS = {"orchestrator", "scout", "builder", "verifier"}
STATE_SECTIONS = [
    "Goal",
    "Done (verified PASS)",
    "Failed / blocked",
    "Failure log (1st occurrence)",
    "Rules learned",
    "Next",
    "Last session",
]


def parse_frontmatter(text: str) -> dict[str, object] | None:
    """Parse minimal YAML frontmatter supporting both scalar values and YAML lists."""
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return None
    end = normalized.find("\n---", 3)
    if end == -1:
        return None
    fields: dict[str, object] = {}
    current_list_key: str | None = None
    for line in normalized[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        list_item = re.match(r"^\s+-\s+(.+?)\s*$", line)
        if list_item and current_list_key:
            items = fields.setdefault(current_list_key, [])
            assert isinstance(items, list)
            items.append(list_item.group(1).strip().strip("'\""))
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value == "":
                fields[key] = []
                current_list_key = key
            else:
                fields[key] = value.strip("'\"")
                current_list_key = None
    return fields


def extract_tools(fm: dict[str, object]) -> set[str]:
    raw = fm.get("tools")
    if isinstance(raw, list):
        return {str(t).strip() for t in raw if str(t).strip()}
    if isinstance(raw, str):
        return {t.strip() for t in raw.split(",") if t.strip()}
    return set()


def _load_enabled_adapters(root: Path) -> list[dict]:
    cfg_path = root / ".agent-team" / "config.json"
    if not cfg_path.exists():
        # Legacy fallback so isolated unit tests with only .claude/agents still work
        return [
            {
                "name": "claude",
                "entrypoint": "CLAUDE.md",
                "settings_file": ".claude/settings.json",
                "agents_dir": ".claude/agents",
                "agent_format": "claude_md",
                "write_tools": sorted(CLAUDE_WRITE_TOOLS),
                "shell_tools": ["Bash"],
            }
        ]
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    adapters = []
    for name in cfg.get("enabled_adapters", []):
        rel = cfg["adapters"][name]
        adapters.append(json.loads((root / rel).read_text(encoding="utf-8")))
    return adapters


def _settings_has_guard_hook(root: Path, adapter: dict) -> bool:
    settings_rel = adapter.get("settings_file")
    if not settings_rel:
        return False
    path = root / settings_rel
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return "guard_hook.py" in text


def check_agents(root: Path) -> list[Violation]:
    out: list[Violation] = []
    adapters = _load_enabled_adapters(root)

    for adapter in adapters:
        adapter_name = adapter["name"]
        agents_dir = root / adapter["agents_dir"]
        write_tools = set(adapter.get("write_tools", ALL_WRITE_TOOLS))
        shell_tools = set(adapter.get("shell_tools", SHELL_TOOLS))
        files = sorted(agents_dir.glob("*.md")) if agents_dir.exists() else []
        if not files:
            out.append(
                Violation(
                    "TEAM-001",
                    adapter["agents_dir"],
                    0,
                    f"No subagents defined for adapter '{adapter_name}'; the orchestrator has no team to delegate to.",
                    f"Run 'python scripts/sync_adapters.py' or add scout.md, builder.md and verifier.md under {adapter['agents_dir']}/.",
                )
            )
            continue

        names: set[str] = set()
        for path in files:
            r = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8")
            fm = parse_frontmatter(text)
            if fm is None:
                out.append(
                    Violation(
                        "TEAM-001",
                        r,
                        1,
                        "Subagent file has no YAML frontmatter.",
                        "Start the file with '---', then name, description, model, tools, then '---'.",
                    )
                )
                continue

            for key in ("name", "description", "model", "tools"):
                val = fm.get(key)
                if not val:
                    cause = {
                        "model": "Without a model line the subagent inherits the expensive orchestrator model.",
                        "tools": "Without a tools line the subagent gets every tool, breaking least privilege.",
                    }.get(key, f"Frontmatter is missing '{key}'.")
                    out.append(
                        Violation(
                            "TEAM-001",
                            r,
                            1,
                            cause,
                            f"Add '{key}' to the frontmatter via .agent-team/adapters/{adapter_name}.json and sync.",
                        )
                    )

            tools = extract_tools(fm)
            name = str(fm.get("name") or path.stem)
            names.add(name)

            if name in READ_ONLY_AGENTS and (tools & write_tools):
                bad = ", ".join(sorted(tools & write_tools))
                out.append(
                    Violation(
                        "TEAM-002",
                        r,
                        1,
                        f"'{name}' ({adapter_name}) must be read-only but has {bad}; a verifier that can edit can grade its own fixes.",
                        f"Remove {bad} from the tools list.",
                    )
                )

            if name == "verifier" and (tools & shell_tools):
                settings_path = root / adapter.get("settings_file", "")
                if settings_path.exists() and not _settings_has_guard_hook(root, adapter):
                    out.append(
                        Violation(
                            "TEAM-002",
                            adapter["settings_file"],
                            1,
                            f"Verifier ({adapter_name}) has shell access without scripts/guard_hook.py wired in {adapter['settings_file']}.",
                            f"Configure scripts/guard_hook.py in {adapter['settings_file']} hooks to prevent unauthorized writes.",
                        )
                    )

            if tools & write_tools:
                if adapter["agent_format"] == "claude_md":
                    if fm.get("isolation") != "worktree":
                        out.append(
                            Violation(
                                "TEAM-003",
                                r,
                                1,
                                f"'{name}' ({adapter_name}) can write files but is not isolated; parallel builders would overwrite each other.",
                                "Add 'isolation: worktree' to the frontmatter.",
                            )
                        )
                elif adapter["agent_format"] == "gemini_md":
                    if "worktree_ops.py" not in text:
                        out.append(
                            Violation(
                                "TEAM-003",
                                r,
                                1,
                                f"'{name}' ({adapter_name}) can write files but does not require scripts/worktree_ops.py isolation.",
                                "Include scripts/worktree_ops.py isolation instructions in .agent-team/adapters/gemini.json and sync.",
                            )
                        )

        if "verifier" not in names:
            out.append(
                Violation(
                    "TEAM-002",
                    adapter["agents_dir"],
                    0,
                    f"No verifier subagent for adapter '{adapter_name}'; builders would be graded by the orchestrator or themselves.",
                    f"Add verifier to .agent-team/adapters/{adapter_name}.json and run 'python scripts/sync_adapters.py'.",
                )
            )
    return out


def parse_plan(text: str) -> list[dict]:
    tasks = []
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)
    for header in re.finditer(r"^## (T-\d+)\b.*$", text, flags=re.MULTILINE):
        end = re.compile(r"^## ", re.MULTILINE).search(text, header.end())
        block = text[header.end() : end.start() if end else len(text)]
        task = {
            "id": header.group(1),
            "line": text[: header.start()].count("\n") + 1,
            "status": None,
            "owner": None,
            "depends_on": [],
            "files": [],
            "acceptance": [],
        }
        in_acceptance = False
        for line in block.splitlines():
            fm = re.match(r"\s*-\s*(Status|Files|Acceptance|Owner|Depends on):\s*(.*)", line)
            if fm:
                key, value = fm.group(1), fm.group(2).strip()
                in_acceptance = key == "Acceptance"
                if key == "Status":
                    task["status"] = value
                elif key == "Owner":
                    task["owner"] = value
                elif key == "Depends on":
                    if value and value.lower() not in {"none", "n/a", "-"}:
                        task["depends_on"] = [d.strip() for d in value.split(",") if d.strip()]
                elif key == "Files":
                    task["files"] = [f.strip() for f in value.split(",") if f.strip()]
                elif key == "Acceptance" and value:
                    task["acceptance"].append(value)
            elif in_acceptance and re.match(r"\s{2,}-\s*\S", line):
                task["acceptance"].append(line.strip()[1:].strip())
        tasks.append(task)
    return tasks


def check_plan(root: Path) -> list[Violation]:
    out: list[Violation] = []
    path = root / "PLAN.md"
    if not path.exists():
        return [
            Violation(
                "TEAM-004",
                "PLAN.md",
                0,
                "PLAN.md is missing.",
                "Create PLAN.md from the template in README.md.",
            )
        ]
    tasks = parse_plan(path.read_text(encoding="utf-8"))
    by_id: dict[str, dict] = {}
    for t in tasks:
        if t["id"] in by_id:
            out.append(
                Violation(
                    "TEAM-004",
                    "PLAN.md",
                    t["line"],
                    f"Duplicate task id {t['id']}.",
                    "Give every task a unique T-### id.",
                )
            )
        by_id[t["id"]] = t

        if t["status"] not in PLAN_STATUSES:
            out.append(
                Violation(
                    "TEAM-004",
                    "PLAN.md",
                    t["line"],
                    f"{t['id']} has status '{t['status']}'.",
                    f"Set '- Status:' to one of {', '.join(sorted(PLAN_STATUSES))}.",
                )
            )
        if t["owner"] and t["owner"] not in VALID_OWNERS:
            out.append(
                Violation(
                    "TEAM-004",
                    "PLAN.md",
                    t["line"],
                    f"{t['id']} has invalid owner '{t['owner']}'.",
                    f"Set '- Owner:' to one of {', '.join(sorted(VALID_OWNERS))}.",
                )
            )
        if not t["files"]:
            out.append(
                Violation(
                    "TEAM-004",
                    "PLAN.md",
                    t["line"],
                    f"{t['id']} has no Files; parallel safety cannot be checked.",
                    "Add '- Files: path/a, path/b' listing every file the task may touch.",
                )
            )
        if not t["acceptance"]:
            out.append(
                Violation(
                    "TEAM-004",
                    "PLAN.md",
                    t["line"],
                    f"{t['id']} has no acceptance criteria; the verifier has nothing to check.",
                    "Add '- Acceptance:' with at least one runnable command or observable result.",
                )
            )

    for t in tasks:
        for dep in t["depends_on"]:
            if dep == t["id"]:
                out.append(
                    Violation(
                        "TEAM-004",
                        "PLAN.md",
                        t["line"],
                        f"{t['id']} depends on itself.",
                        "Remove the self-reference from 'Depends on'.",
                    )
                )
            elif dep not in by_id:
                out.append(
                    Violation(
                        "TEAM-004",
                        "PLAN.md",
                        t["line"],
                        f"{t['id']} depends on unknown task '{dep}'.",
                        f"Add task {dep} to PLAN.md or fix the 'Depends on' field.",
                    )
                )
            elif t["status"] in {"doing", "verify", "done"} and by_id[dep]["status"] != "done":
                out.append(
                    Violation(
                        "TEAM-004",
                        "PLAN.md",
                        t["line"],
                        f"{t['id']} is '{t['status']}' while dependency {dep} is '{by_id[dep]['status']}' (not 'done').",
                        f"Complete and merge {dep} first, or set {t['id']} back to 'todo'.",
                    )
                )

    active = [t for t in tasks if t["status"] in ACTIVE_STATUSES]
    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            overlaps = sorted(
                {f"{fa} <-> {fb}" if fa != fb else fa for fa in a["files"] for fb in b["files"] if paths_overlap(fa, fb)}
            )
            if overlaps:
                out.append(
                    Violation(
                        "TEAM-004",
                        "PLAN.md",
                        b["line"],
                        f"{a['id']} ({a['status']}) and {b['id']} ({b['status']}) are both active and overlap on {', '.join(overlaps)}.",
                        f"Set one of them back to 'todo' and add 'Depends on: {a['id']}' to it.",
                    )
                )
    return out


def known_check_ids(root: Path) -> set[str]:
    """Extract exact defined rule IDs and test identifiers (no loose substring matching)."""
    ids: set[str] = set()
    rule_id_re = re.compile(r"\b(?:GOV|TEAM|SCOPE|GUARD)-\d{3}\b")
    py_test_re = re.compile(r"^\s*def\s+(test_[A-Za-z0-9_]+)\s*\(", re.MULTILINE)
    js_test_re = re.compile(r"""\b(?:it|test)\s*\(\s*['"]([A-Za-z0-9_.-]+)['"]""")
    eslint_rule_re = re.compile(r"""['"]([a-z0-9-]+/[a-z0-9-]+|[a-z0-9-]+)['"]\s*:""")

    for folder in ("scripts", ".governance", "eslint-rules", "tests"):
        base = root / folder
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            ids.update(rule_id_re.findall(text))
            if folder == "tests":
                ids.update(py_test_re.findall(text))
                ids.update(js_test_re.findall(text))
            if folder == "eslint-rules":
                ids.add(p.stem)

    for name in ("eslint.config.js", "eslint.config.mjs", ".eslintrc.json", ".dependency-cruiser.js", ".dependency-cruiser.cjs"):
        p = root / name
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            ids.update(rule_id_re.findall(text))
            ids.update(eslint_rule_re.findall(text))
    return ids


def check_state(root: Path) -> list[Violation]:
    out: list[Violation] = []
    path = root / "STATE.md"
    if not path.exists():
        return [
            Violation(
                "TEAM-005",
                "STATE.md",
                0,
                "STATE.md is missing; the team loses memory between sessions.",
                "Create STATE.md from the template.",
            )
        ]
    text = path.read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+?)\s*$", text, flags=re.MULTILINE)
    for section in STATE_SECTIONS:
        if section not in headings:
            out.append(
                Violation(
                    "TEAM-005",
                    "STATE.md",
                    0,
                    f"Section '## {section}' is missing.",
                    f"Add '## {section}' to STATE.md.",
                )
            )
    m = re.search(r"^## Rules learned\s*$(.*?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL)
    if m:
        defined_ids = known_check_ids(root)
        start = text[: m.start(1)].count("\n") + 1
        for offset, line in enumerate(m.group(1).splitlines()):
            if not re.match(r"\s*[-*]\s+\S", line):
                continue
            check = re.search(r"Check:\s*([A-Za-z0-9_./-]+)", line)
            if not check:
                out.append(
                    Violation(
                        "TEAM-005",
                        "STATE.md",
                        start + offset,
                        "Rule learned exists only as prose; prompt patching is forbidden (RFC-001 §1.1).",
                        "Add a deterministic check (scripts/check_governance.py, ESLint rule, or test in tests/) and append 'Check: <EXACT-RULE-ID>' to this line.",
                    )
                )
            elif check.group(1) not in defined_ids:
                out.append(
                    Violation(
                        "TEAM-005",
                        "STATE.md",
                        start + offset,
                        f"Rule learned points to check '{check.group(1)}', which is not a defined rule ID or test name in scripts/, .governance/, lint config, or tests/.",
                        f"Implement {check.group(1)} as a deterministic check or test, or fix the exact ID.",
                    )
                )
    return out


def check_entrypoints(root: Path) -> list[Violation]:
    out: list[Violation] = []
    adapters = _load_enabled_adapters(root)
    has_team_cfg = (root / ".agent-team" / "config.json").exists()
    required_refs = (
        ("AGENTS.md", ".agent-team/prompts/orchestrator.md", ".agent-team/protocols/handoff-and-worktree.md", "docs/standards/RFC-001.md")
        if has_team_cfg
        else ("AGENTS.md", "docs/standards/RFC-001.md")
    )

    for adapter in adapters:
        entry_rel = adapter["entrypoint"]
        entry_path = root / entry_rel
        text = entry_path.read_text(encoding="utf-8") if entry_path.exists() else ""
        for ref in required_refs:
            if ref not in text:
                out.append(
                    Violation(
                        "TEAM-006",
                        entry_rel,
                        0,
                        f"The {adapter['name']} orchestrator entrypoint does not load {ref}.",
                        f"Reference '{ref}' in {entry_rel}.",
                    )
                )

        settings_rel = adapter.get("settings_file")
        if settings_rel and (root / settings_rel).exists():
            settings = json.loads((root / settings_rel).read_text(encoding="utf-8"))
            settings_text = json.dumps(settings)
            if adapter["name"] == "claude":
                allow = settings.get("permissions", {}).get("allow", [])
                for item in allow:
                    if "--write-baseline" in item or re.search(r"check_governance\.py:\*", item):
                        out.append(
                            Violation(
                                "TEAM-006",
                                settings_rel,
                                0,
                                f"Permission allow rule '{item}' permits agents to run '--write-baseline' and bypass the RFC-001 §3.1 ratchet.",
                                "Restrict allow rules to safe read-only invocations of check_governance.py and deny '--write-baseline'.",
                            )
                        )
                if "guard_hook.py" not in settings_text:
                    out.append(
                        Violation(
                            "TEAM-006",
                            settings_rel,
                            0,
                            "Claude settings do not wire scripts/guard_hook.py into hooks.PreToolUse.",
                            "Add a PreToolUse command hook calling scripts/guard_hook.py --adapter claude.",
                        )
                    )
            elif adapter["name"] == "gemini":
                if "guard_hook.py" not in settings_text:
                    out.append(
                        Violation(
                            "TEAM-006",
                            settings_rel,
                            0,
                            "Gemini settings do not wire scripts/guard_hook.py into hooks.BeforeTool.",
                            "Add a BeforeTool command hook calling scripts/guard_hook.py --adapter gemini.",
                        )
                    )
                if not settings.get("model", {}).get("name"):
                    out.append(
                        Violation(
                            "TEAM-006",
                            settings_rel,
                            0,
                            "Gemini settings do not pin an explicit orchestrator model.name.",
                            "Set 'model': {'name': 'gemini-3-pro-preview'} in .gemini/settings.json.",
                        )
                    )
    return out


def run(root: Path) -> list[Violation]:
    violations = check_agents(root) + check_plan(root) + check_state(root) + check_entrypoints(root)
    if (root / ".agent-team" / "config.json").exists():
        violations += sync_adapters.check_sync(root)
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=Path(__file__).resolve().parent.parent, type=Path)
    args = parser.parse_args()
    return print_report("Agent team", run(args.root.resolve()))


if __name__ == "__main__":
    sys.exit(main())
