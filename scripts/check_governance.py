"""RFC-001 governance checks for source code under src/.

Zero dependencies. Every violation carries Rule ID, Root Cause and Remediation (RFC-001 §1.2).

Usage:
  python scripts/check_governance.py
  python scripts/check_governance.py --changed-from origin/main
  python scripts/check_governance.py --changed-from origin/main --pr-body-file body.md
  python scripts/check_governance.py --baseline-ref origin/main
  python scripts/check_governance.py --write-baseline
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

from _report import Violation, print_report

IMPORT_RE = re.compile(
    r"""(?:import\s+(?:[\w*{}\s,]+\s+from\s+)?|export\s+[\w*{}\s,]+\s+from\s+|require\s*\(\s*|import\s*\(\s*)['"]([^'"]+)['"]"""
)
REGISTRATION_RE = re.compile(r"expires=(\d{4}-\d{2}-\d{2})\s+ticket=([A-Z][A-Z0-9]*-\d+)")
ARTIFACT_RE = re.compile(r"^\s*[-*]?\s*Artifact:\s*\S+", re.IGNORECASE | re.MULTILINE)


def load_config(root: Path) -> dict:
    return json.loads((root / ".governance" / "config.json").read_text(encoding="utf-8"))


def load_baseline(root: Path) -> set[tuple[str, str]]:
    path = root / ".governance" / "baseline.json"
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {tuple(item) for item in data.get("violations", [])}


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def source_files(root: Path, cfg: dict) -> list[Path]:
    base = root / cfg["source_root"]
    if not base.exists():
        return []
    exts = set(cfg["extensions"])
    return sorted(p for p in base.rglob("*") if p.is_file() and p.suffix in exts)


def layer_of(root: Path, path: Path, cfg: dict) -> str | None:
    r = rel(root, path)
    for name, layer in cfg["layers"].items():
        prefix = layer["path"].rstrip("/") + "/"
        if r.startswith(prefix):
            return name
    return None


def resolve_import(root: Path, importer: Path, spec: str, cfg: dict) -> Path | None:
    if spec.startswith("."):
        candidate = (importer.parent / spec).resolve()
    elif spec.startswith("@/"):
        candidate = (root / cfg["source_root"] / spec[2:]).resolve()
    else:
        return None
    options = [candidate]
    options += [candidate.with_name(candidate.name + ext) for ext in cfg["extensions"]]
    options += [candidate / f"index{ext}" for ext in cfg["extensions"]]
    for option in options:
        if option.is_file():
            return option
    return None


def check_file_lines(root: Path, path: Path, cfg: dict, today: dt.date) -> list[Violation]:
    out: list[Violation] = []
    r = rel(root, path)
    layer = layer_of(root, path, cfg)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for no, line in enumerate(lines, start=1):
        for banned in cfg["banned_primitives"]:
            if layer in banned["layers"] and re.search(banned["pattern"], line):
                out.append(Violation(
                    "GOV-201", r, no,
                    f"{banned['name']} is banned in the '{layer}' layer (RFC-001 §2.1).",
                    banned["remediation"],
                ))
        for pattern in cfg["suppression_patterns"]:
            if not re.search(pattern, line):
                continue
            reg = REGISTRATION_RE.search(line)
            if not reg:
                out.append(Violation(
                    "GOV-231", r, no,
                    f"Escape hatch '{pattern}' has no registered expiry and ticket (RFC-001 §2.3).",
                    "Remove the escape hatch and fix the underlying issue. If it is truly unavoidable, "
                    "append 'expires=YYYY-MM-DD ticket=ABC-123' on the same line.",
                ))
            elif dt.date.fromisoformat(reg.group(1)) < today:
                out.append(Violation(
                    "GOV-232", r, no,
                    f"Escape hatch registered under {reg.group(2)} expired on {reg.group(1)} (RFC-001 §2.3).",
                    f"Resolve ticket {reg.group(2)} and delete the escape hatch. Do not extend the date.",
                ))
        for pattern in cfg["justification_comment_patterns"]:
            if re.search(pattern, line, re.IGNORECASE):
                out.append(Violation(
                    "GOV-233", r, no,
                    "Justification comment found; code must explain itself (RFC-001 §2.3).",
                    "Delete the comment. If the constraint matters, encode it as a type, a named "
                    "function, or a check in scripts/check_governance.py.",
                ))
        for pattern in cfg["unauthorized_type_assertions"]:
            if re.search(pattern, line):
                out.append(Violation(
                    "GOV-234", r, no,
                    "Unauthorized type assertion bypasses the type checker (RFC-001 Gate 2).",
                    "Replace the assertion with a type guard or a properly typed API.",
                ))
    return out


def build_graph(root: Path, files: list[Path], cfg: dict) -> tuple[dict[Path, list[tuple[Path, int]]], list[Violation]]:
    graph: dict[Path, list[tuple[Path, int]]] = {}
    out: list[Violation] = []
    layers = cfg["layers"]
    for path in files:
        edges: list[tuple[Path, int]] = []
        src_layer = layer_of(root, path, cfg)
        for no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            for spec in IMPORT_RE.findall(line):
                target = resolve_import(root, path, spec, cfg)
                if target is None:
                    continue
                edges.append((target, no))
                dst_layer = layer_of(root, target, cfg)
                if src_layer and dst_layer and dst_layer != src_layer and dst_layer not in layers[src_layer]["may_import"]:
                    allowed = ", ".join(layers[src_layer]["may_import"]) or "nothing outside itself"
                    out.append(Violation(
                        "GOV-221", rel(root, path), no,
                        f"Layer '{src_layer}' imports from '{dst_layer}' ({spec}); '{src_layer}' may only import {allowed} (RFC-001 §2.2).",
                        f"Move the needed code down into an allowed layer, or invert the dependency so '{dst_layer}' depends on '{src_layer}' through an interface defined in '{src_layer}'.",
                    ))
        graph[path] = edges
    return graph, out


def find_cycles(root: Path, graph: dict[Path, list[tuple[Path, int]]]) -> list[Violation]:
    index: dict[Path, int] = {}
    low: dict[Path, int] = {}
    stack: list[Path] = []
    on_stack: set[Path] = set()
    sccs: list[list[Path]] = []
    counter = [0]

    def strong(v: Path) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w, _ in graph.get(v, []):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1 or any(t == v for t, _ in graph.get(v, [])):
                sccs.append(comp)

    sys.setrecursionlimit(max(10000, len(graph) * 4))
    for node in graph:
        if node not in index:
            strong(node)

    out = []
    for comp in sccs:
        names = sorted(rel(root, p) for p in comp)
        out.append(Violation(
            "GOV-222", names[0], 0,
            f"Circular dependency between: {' -> '.join(names)} (RFC-001 §2.2).",
            "Extract the shared part into a lower module that all of them import, so the import graph becomes acyclic.",
        ))
    return out


def check_invariants(root: Path, cfg: dict) -> list[Violation]:
    out = []
    for pattern in cfg.get("invariant_paths", []):
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            stem = path.name.split(".")[0]
            siblings = list(path.parent.glob(f"{stem}.*"))
            proofs = [s for s in siblings if re.search(r"\.(test|spec|property|invariant)\.|\.tla$", s.name)]
            if not proofs:
                out.append(Violation(
                    "GOV-321", rel(root, path), 0,
                    "Core state machine has no formal invariant or property-based test (RFC-001 §3.2).",
                    f"Add {stem}.property.test.ts (property-based) or {stem}.tla (TLA+ spec) next to it.",
                ))
    return out


def changed_files(root: Path, ref: str) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{ref}...HEAD"],
        cwd=root, capture_output=True, text=True, check=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def check_artifacts(changed: set[str], body: str, cfg: dict) -> list[Violation]:
    touched = sorted(f for f in changed if any(f.startswith(p) for p in cfg["artifact_required_paths"]))
    if touched and not ARTIFACT_RE.search(body):
        return [Violation(
            "GOV-311", "PR description", 0,
            f"PR touches {', '.join(touched[:5])} but has no review artifact (RFC-001 §3.1).",
            "Add a line 'Artifact: <link>' to the PR description pointing to an E2E recording, a statechart, or a benchmark diff.",
        )]
    return []


def baseline_at(root: Path, ref: str) -> set[tuple[str, str]]:
    result = subprocess.run(
        ["git", "show", f"{ref}:.governance/baseline.json"],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return set()
    return {tuple(item) for item in json.loads(result.stdout).get("violations", [])}


def run(root: Path, changed: set[str] | None = None, today: dt.date | None = None,
        pr_body: str | None = None, baseline_ref: str | None = None) -> tuple[list[Violation], list[Violation], list[str]]:
    """Return (blocking violations, all raw violations, notes)."""
    cfg = load_config(root)
    today = today or dt.date.today()
    files = source_files(root, cfg)
    raw: list[Violation] = []
    for path in files:
        raw += check_file_lines(root, path, cfg, today)
    graph, layer_violations = build_graph(root, files, cfg)
    raw += layer_violations
    raw += find_cycles(root, graph)
    raw += check_invariants(root, cfg)

    baseline = load_baseline(root)
    changed = changed or set()
    blocking = [v for v in raw if v.key() not in baseline or v.file in changed]
    grandfathered = len(raw) - len(blocking)
    notes = [f"Grandfathered by baseline (RFC-001 §4.1): {grandfathered}"] if grandfathered else []

    current = {v.key() for v in raw}
    for rule_id, file in sorted(baseline - current):
        blocking.append(Violation(
            "GOV-411", ".governance/baseline.json", 0,
            f"Baseline entry [{rule_id}, {file}] no longer occurs; the debt is paid and the rule must be locked (RFC-001 §4.1).",
            f"Remove [\"{rule_id}\", \"{file}\"] from .governance/baseline.json.",
        ))

    if baseline_ref:
        for rule_id, file in sorted(baseline - baseline_at(root, baseline_ref)):
            blocking.append(Violation(
                "GOV-412", ".governance/baseline.json", 0,
                f"Baseline gained [{rule_id}, {file}]; the ratchet only moves one way (RFC-001 §4.1).",
                "Fix the new violation instead of adding it to the baseline.",
            ))

    if pr_body is not None:
        blocking += check_artifacts(changed, pr_body, cfg)

    return blocking, raw, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=Path(__file__).resolve().parent.parent, type=Path)
    parser.add_argument("--changed-from", help="git ref; files changed since it lose baseline protection")
    parser.add_argument("--pr-body-file", type=Path, help="PR description, enables GOV-311")
    parser.add_argument("--baseline-ref", help="git ref whose baseline the current one must not exceed")
    parser.add_argument("--write-baseline", action="store_true", help="record current violations as legacy debt")
    args = parser.parse_args()

    root = args.root.resolve()
    changed = changed_files(root, args.changed_from) if args.changed_from else set()
    body = args.pr_body_file.read_text(encoding="utf-8") if args.pr_body_file else None
    blocking, raw, notes = run(root, changed, pr_body=body, baseline_ref=args.baseline_ref)

    if args.write_baseline:
        entries = sorted({v.key() for v in raw})
        path = root / ".governance" / "baseline.json"
        path.write_text(json.dumps({"violations": [list(e) for e in entries]}, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(entries)} baseline entries to {rel(root, path)}")
        return 0

    return print_report("RFC-001 governance", blocking, notes)


if __name__ == "__main__":
    sys.exit(main())
