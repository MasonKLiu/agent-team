"""RFC-001 governance checks for source code under src/.

Zero dependencies. Every violation carries Rule ID, Root Cause and Remediation (RFC-001 §1.2).

Improvements over v1:
  - Comment/string-aware JS/TS scanner: eliminates false positives in comments/strings
  - Full-file multi-line import/export parsing (catches multi-line imports for GOV-221/222)
  - Safe ISO date validation for GOV-231/232 (no ValueError crashes on invalid dates)
  - Count-aware Ratchet baseline (cannot add extra violations to a grandfathered file)
  - Hardened GOV-311 review artifact validation (rejects placeholder values like 'none')
  - GOV-321 checks both colocated siblings and mirrored tests/ directory

Usage:
  python scripts/check_governance.py
  python scripts/check_governance.py --changed-from origin/main
  python scripts/check_governance.py --changed-from origin/main --pr-body-file body.md
  python scripts/check_governance.py --baseline-ref origin/main
  python scripts/check_governance.py --write-baseline
"""

from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

from _report import Violation, print_report

IMPORT_RE = re.compile(
    r"""(?:import\s+(?:type\s+)?(?:[\w*{}\s,$]+\s+from\s+)?|export\s+(?:type\s+)?[\w*{}\s,$]+\s+from\s+|require\s*\(\s*|import\s*\(\s*)['"]([^'"]+)['"]""",
    re.DOTALL,
)
REGISTRATION_RE = re.compile(r"expires=(\d{4}-\d{2}-\d{2})\s+ticket=([A-Z][A-Z0-9]*-\d+)")
ARTIFACT_LINE_RE = re.compile(r"^\s*[-*]?\s*Artifact:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
ARTIFACT_VALID_VALUE_RE = re.compile(
    r"(?:https?://\S+|!?\[[^\]]*\]\([^)]+\)|(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9]{2,5})"
)
ARTIFACT_PLACEHOLDERS = {"none", "n/a", "na", "todo", "tbd", "-", "null", "skip"}


def load_config(root: Path) -> dict:
    return json.loads((root / ".governance" / "config.json").read_text(encoding="utf-8"))


def _parse_baseline_data(data: dict) -> dict[tuple[str, str], int]:
    """Support both v2 count-aware {'counts': {'RULE::file': n}} and legacy {'violations': [[rule, file]]}."""
    counts: dict[tuple[str, str], int] = {}
    if isinstance(data.get("counts"), dict):
        for raw_key, count in data["counts"].items():
            if "::" in raw_key:
                rule_id, file = raw_key.split("::", 1)
                counts[(rule_id, file)] = int(count)
    for item in data.get("violations", []):
        if isinstance(item, list) and len(item) == 2:
            key = (str(item[0]), str(item[1]))
            counts[key] = max(counts.get(key, 0), 1)
    return counts


def load_baseline(root: Path) -> dict[tuple[str, str], int]:
    path = root / ".governance" / "baseline.json"
    if not path.exists():
        return {}
    return _parse_baseline_data(json.loads(path.read_text(encoding="utf-8")))


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


def split_code_and_comments(text: str) -> tuple[str, str, str]:
    """Return (code_no_strings_or_comments, code_no_comments, comments_only), preserving newlines."""
    no_comments: list[str] = []
    no_strings_or_comments: list[str] = []
    comments_only: list[str] = []

    i = 0
    n = len(text)
    state = "code"  # code | line_comment | block_comment | single | double | template
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if state == "code":
            if ch == "/" and nxt == "/":
                state = "line_comment"
                no_comments.append("  ")
                no_strings_or_comments.append("  ")
                comments_only.append("//")
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block_comment"
                no_comments.append("  ")
                no_strings_or_comments.append("  ")
                comments_only.append("/*")
                i += 2
                continue
            if ch in ("'", '"', "`"):
                state = {"'": "single", '"': "double", "`": "template"}[ch]
                no_comments.append(ch)
                no_strings_or_comments.append(" ")
                comments_only.append(" ")
                i += 1
                continue
            no_comments.append(ch)
            no_strings_or_comments.append(ch)
            comments_only.append("\n" if ch == "\n" else " ")
            i += 1
        elif state == "line_comment":
            if ch == "\n":
                state = "code"
                no_comments.append("\n")
                no_strings_or_comments.append("\n")
                comments_only.append("\n")
            else:
                no_comments.append(" ")
                no_strings_or_comments.append(" ")
                comments_only.append(ch)
            i += 1
        elif state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "code"
                no_comments.append("  ")
                no_strings_or_comments.append("  ")
                comments_only.append("*/")
                i += 2
                continue
            if ch == "\n":
                no_comments.append("\n")
                no_strings_or_comments.append("\n")
                comments_only.append("\n")
            else:
                no_comments.append(" ")
                no_strings_or_comments.append(" ")
                comments_only.append(ch)
            i += 1
        else:
            quote = {"single": "'", "double": '"', "template": "`"}[state]
            if ch == "\\" and i + 1 < n:
                no_comments.append(ch + nxt)
                no_strings_or_comments.append("\n" if nxt == "\n" else "  ")
                comments_only.append("\n" if nxt == "\n" else "  ")
                i += 2
                continue
            if ch == quote:
                state = "code"
                no_comments.append(ch)
                no_strings_or_comments.append(" ")
                comments_only.append(" ")
                i += 1
                continue
            no_comments.append(ch)
            no_strings_or_comments.append("\n" if ch == "\n" else " ")
            comments_only.append("\n" if ch == "\n" else " ")
            i += 1

    return ("".join(no_strings_or_comments), "".join(no_comments), "".join(comments_only))


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
    raw_text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    code_only, _, comments_only = split_code_and_comments(raw_text)

    raw_lines = raw_text.splitlines()
    code_lines = code_only.splitlines()
    comment_lines = comments_only.splitlines()

    for no, raw_line in enumerate(raw_lines, start=1):
        code_line = code_lines[no - 1] if no - 1 < len(code_lines) else ""
        comment_line = comment_lines[no - 1] if no - 1 < len(comment_lines) else ""

        for banned in cfg["banned_primitives"]:
            if layer in banned["layers"] and re.search(banned["pattern"], code_line):
                out.append(
                    Violation(
                        "GOV-201",
                        r,
                        no,
                        f"{banned['name']} is banned in the '{layer}' layer (RFC-001 §2.1).",
                        banned["remediation"],
                    )
                )

        for pattern in cfg["suppression_patterns"]:
            if not re.search(pattern, raw_line):
                continue
            reg = REGISTRATION_RE.search(raw_line)
            if not reg:
                out.append(
                    Violation(
                        "GOV-231",
                        r,
                        no,
                        f"Escape hatch '{pattern}' has no registered expiry and ticket (RFC-001 §2.3).",
                        "Remove the escape hatch and fix the underlying issue. If it is truly unavoidable, "
                        "append 'expires=YYYY-MM-DD ticket=ABC-123' on the same line.",
                    )
                )
            else:
                try:
                    expiry = dt.date.fromisoformat(reg.group(1))
                except ValueError:
                    out.append(
                        Violation(
                            "GOV-231",
                            r,
                            no,
                            f"Escape hatch '{pattern}' has an invalid expiry date '{reg.group(1)}' (RFC-001 §2.3).",
                            "Use a valid calendar date in ISO format: 'expires=YYYY-MM-DD ticket=ABC-123'.",
                        )
                    )
                    continue
                if expiry < today:
                    out.append(
                        Violation(
                            "GOV-232",
                            r,
                            no,
                            f"Escape hatch registered under {reg.group(2)} expired on {reg.group(1)} (RFC-001 §2.3).",
                            f"Resolve ticket {reg.group(2)} and delete the escape hatch. Do not extend the date.",
                        )
                    )

        for pattern in cfg["justification_comment_patterns"]:
            if re.search(pattern, comment_line, re.IGNORECASE):
                out.append(
                    Violation(
                        "GOV-233",
                        r,
                        no,
                        "Justification comment found; code must explain itself (RFC-001 §2.3).",
                        "Delete the comment. If the constraint matters, encode it as a type, a named "
                        "function, or a check in scripts/check_governance.py.",
                    )
                )
                break

        for pattern in cfg["unauthorized_type_assertions"]:
            if re.search(pattern, code_line):
                out.append(
                    Violation(
                        "GOV-234",
                        r,
                        no,
                        "Unauthorized type assertion bypasses the type checker (RFC-001 Gate 2).",
                        "Replace the assertion with a type guard or a properly typed API.",
                    )
                )
    return out


def build_graph(root: Path, files: list[Path], cfg: dict) -> tuple[dict[Path, list[tuple[Path, int]]], list[Violation]]:
    graph: dict[Path, list[tuple[Path, int]]] = {}
    out: list[Violation] = []
    layers = cfg["layers"]
    for path in files:
        edges: list[tuple[Path, int]] = []
        src_layer = layer_of(root, path, cfg)
        raw_text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        _, code_no_comments, _ = split_code_and_comments(raw_text)
        for match in IMPORT_RE.finditer(code_no_comments):
            spec = match.group(1)
            no = code_no_comments[: match.start()].count("\n") + 1
            target = resolve_import(root, path, spec, cfg)
            if target is None:
                continue
            edges.append((target, no))
            dst_layer = layer_of(root, target, cfg)
            if src_layer and dst_layer and dst_layer != src_layer and dst_layer not in layers[src_layer]["may_import"]:
                allowed = ", ".join(layers[src_layer]["may_import"]) or "nothing outside itself"
                out.append(
                    Violation(
                        "GOV-221",
                        rel(root, path),
                        no,
                        f"Layer '{src_layer}' imports from '{dst_layer}' ({spec}); '{src_layer}' may only import {allowed} (RFC-001 §2.2).",
                        f"Move the needed code down into an allowed layer, or invert the dependency so '{dst_layer}' depends on '{src_layer}' through an interface defined in '{src_layer}'.",
                    )
                )
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
        out.append(
            Violation(
                "GOV-222",
                names[0],
                0,
                f"Circular dependency between: {' -> '.join(names)} (RFC-001 §2.2).",
                "Extract the shared part into a lower module that all of them import, so the import graph becomes acyclic.",
            )
        )
    return out


def check_invariants(root: Path, cfg: dict) -> list[Violation]:
    out = []
    tests_dir = root / "tests"
    proof_re = re.compile(r"\.(test|spec|property|invariant)\.|\.tla$")
    for pattern in cfg.get("invariant_paths", []):
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            stem = path.name.split(".")[0]
            candidates = list(path.parent.glob(f"{stem}.*"))
            if tests_dir.exists():
                candidates += list(tests_dir.rglob(f"{stem}.*"))
                candidates += list(tests_dir.rglob(f"test_{stem}.*"))
            proofs = [c for c in candidates if proof_re.search(c.name) or c.name.startswith(f"test_{stem}.")]
            if not proofs:
                out.append(
                    Violation(
                        "GOV-321",
                        rel(root, path),
                        0,
                        "Core state machine has no formal invariant or property-based test (RFC-001 §3.2).",
                        f"Add {stem}.property.test.ts (next to it or under tests/) or {stem}.tla (TLA+ spec).",
                    )
                )
    return out


def changed_files(root: Path, ref: str) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{ref}...HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def has_valid_artifact(body: str) -> bool:
    for match in ARTIFACT_LINE_RE.finditer(body):
        val = match.group(1).strip()
        if val.lower() in ARTIFACT_PLACEHOLDERS:
            continue
        if ARTIFACT_VALID_VALUE_RE.search(val):
            return True
    return False


def check_artifacts(changed: set[str], body: str, cfg: dict) -> list[Violation]:
    touched = sorted(f for f in changed if any(f.startswith(p) for p in cfg["artifact_required_paths"]))
    if touched and not has_valid_artifact(body):
        return [
            Violation(
                "GOV-311",
                "PR description",
                0,
                f"PR touches {', '.join(touched[:5])} but has no valid review artifact link/path (RFC-001 §3.1).",
                "Add 'Artifact: https://...' or 'Artifact: artifacts/recording.mp4' (placeholders like 'none' are rejected).",
            )
        ]
    return []


def baseline_at(root: Path, ref: str) -> dict[tuple[str, str], int]:
    result = subprocess.run(
        ["git", "show", f"{ref}:.governance/baseline.json"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}
    return _parse_baseline_data(json.loads(result.stdout))


def run(
    root: Path,
    changed: set[str] | None = None,
    today: dt.date | None = None,
    pr_body: str | None = None,
    baseline_ref: str | None = None,
) -> tuple[list[Violation], list[Violation], list[str]]:
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

    # Count-aware ratchet: allow up to baseline[key] occurrences ONLY for untouched files.
    remaining_allowance = dict(baseline)
    blocking: list[Violation] = []
    grandfathered = 0
    for v in raw:
        key = v.key()
        if v.file not in changed and remaining_allowance.get(key, 0) > 0:
            remaining_allowance[key] -= 1
            grandfathered += 1
        else:
            blocking.append(v)

    notes = [f"Grandfathered by baseline (RFC-001 §4.1): {grandfathered}"] if grandfathered else []

    current_counts = Counter(v.key() for v in raw)
    for (rule_id, file), base_count in sorted(baseline.items()):
        actual_count = current_counts.get((rule_id, file), 0)
        if actual_count < base_count:
            blocking.append(
                Violation(
                    "GOV-411",
                    ".governance/baseline.json",
                    0,
                    f"Baseline entry [{rule_id}, {file}] dropped from {base_count} to {actual_count}; the debt is paid and the ratchet must tighten (RFC-001 §4.1).",
                    f"Update or remove '{rule_id}::{file}' in .governance/baseline.json to {actual_count}.",
                )
            )

    if baseline_ref:
        prev_baseline = baseline_at(root, baseline_ref)
        for (rule_id, file), count in sorted(baseline.items()):
            prev_count = prev_baseline.get((rule_id, file), 0)
            if count > prev_count:
                blocking.append(
                    Violation(
                        "GOV-412",
                        ".governance/baseline.json",
                        0,
                        f"Baseline grew for [{rule_id}, {file}] ({prev_count} -> {count}); the ratchet only moves one way (RFC-001 §4.1).",
                        "Fix the new violation instead of increasing the baseline.",
                    )
                )

    if pr_body is not None:
        blocking += check_artifacts(changed, pr_body, cfg)

    return blocking, raw, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=Path(__file__).resolve().parent.parent, type=Path)
    parser.add_argument("--changed-from", help="git ref; files changed since it lose baseline protection")
    parser.add_argument("--pr-body-file", type=Path, help="PR description, enables GOV-311")
    parser.add_argument("--baseline-ref", help="git ref whose baseline the current one must not exceed")
    parser.add_argument("--write-baseline", action="store_true", help="record current violations as legacy debt (human only)")
    args = parser.parse_args()

    root = args.root.resolve()
    changed = changed_files(root, args.changed_from) if args.changed_from else set()
    body = args.pr_body_file.read_text(encoding="utf-8") if args.pr_body_file else None
    blocking, raw, notes = run(root, changed, pr_body=body, baseline_ref=args.baseline_ref)

    if args.write_baseline:
        counts = Counter(v.key() for v in raw)
        payload = {"counts": {f"{rule}::{file}": cnt for (rule, file), cnt in sorted(counts.items())}}
        path = root / ".governance" / "baseline.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(counts)} baseline entries to {rel(root, path)}")
        return 0

    return print_report("RFC-001 governance", blocking, notes)


if __name__ == "__main__":
    sys.exit(main())
