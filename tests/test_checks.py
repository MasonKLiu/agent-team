import datetime as dt
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import check_governance  # noqa: E402
import check_team  # noqa: E402
import guard_hook  # noqa: E402
import sync_adapters  # noqa: E402
import verify_scope  # noqa: E402

TODAY = dt.date(2026, 11, 25)


class Sandbox:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / ".governance", self.root / ".governance")

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def gov(self, **kwargs):
        blocking, _, _ = check_governance.run(self.root, today=TODAY, **kwargs)
        return sorted(v.rule_id for v in blocking)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.s = Sandbox()

    def tearDown(self):
        self.s.cleanup()

    def test_clean_layers_pass(self):
        self.s.write("src/core/api.ts", "export const x = 1;\n")
        self.s.write("src/domain/user.ts", "import { x } from '../core/api';\n")
        self.s.write("src/ui/page.tsx", "import { x } from '@/core/api';\nimport '../domain/user';\n")
        self.assertEqual(self.s.gov(), [])

    def test_reverse_layer_import_and_multiline_import_fail(self):
        self.s.write("src/ui/page.tsx", "export const p = 1;\n")
        self.s.write(
            "src/core/api.ts",
            "import {\n  p,\n} from '../ui/page';\n",
        )
        self.assertEqual(self.s.gov(), ["GOV-221"])

    def test_comments_and_strings_do_not_false_positive(self):
        self.s.write("src/ui/page.tsx", "export const p = 1;\n")
        self.s.write(
            "src/core/api.ts",
            "// import { p } from '../ui/page'\n"
            "const doc = \"useEffect(() => {}) as any\";\n",
        )
        self.s.write(
            "src/ui/view.tsx",
            "// Do not call useEffect() here\n"
            "const msg = 'useEffect(x) and setTimeout(y) as any';\n",
        )
        self.assertEqual(self.s.gov(), [])

    def test_cycle_fails(self):
        self.s.write("src/core/a.ts", "import './b';\n")
        self.s.write("src/core/b.ts", "import './a';\n")
        self.assertEqual(self.s.gov(), ["GOV-222"])

    def test_banned_primitives_ui_only_and_core_timer_allowed(self):
        self.s.write("src/ui/c.tsx", "useEffect(() => {}, []);\nsetTimeout(() => {}, 10);\n")
        self.s.write("src/core/hooks.ts", "useEffect(() => {}, []);\nsetTimeout(() => {}, 10);\n")
        self.assertEqual(self.s.gov(), ["GOV-201", "GOV-201"])

    def test_suppressions_and_invalid_calendar_date(self):
        self.s.write("src/core/a.ts", "// @ts-ignore\n")
        self.s.write("src/core/b.ts", "// @ts-ignore expires=2026-01-01 ticket=ABC-1\n")
        self.s.write("src/core/c.ts", "// @ts-ignore expires=2027-01-01 ticket=ABC-2\n")
        self.s.write("src/core/d.ts", "// @ts-ignore expires=2026-99-99 ticket=ABC-3\n")
        self.assertEqual(self.s.gov(), ["GOV-231", "GOV-231", "GOV-232"])

    def test_english_and_chinese_justification_comments_and_assertions(self):
        self.s.write(
            "src/core/a.ts",
            "// because the API is flaky\n"
            "// 暫時繞過這個問題\n"
            "const y = z as any;\n",
        )
        self.assertEqual(self.s.gov(), ["GOV-233", "GOV-233", "GOV-234"])

    def test_count_aware_ratchet(self):
        self.s.write("src/core/a.ts", "const y = z as any;\n")
        self.s.write(
            ".governance/baseline.json",
            json.dumps({"counts": {"GOV-234::src/core/a.ts": 1}}),
        )
        # 1 grandfathered occurrence passes untouched
        self.assertEqual(self.s.gov(), [])
        # Adding a 2nd occurrence fails even WITHOUT changed_from
        self.s.write("src/core/a.ts", "const y = z as any;\nconst w = q as any;\n")
        self.assertEqual(self.s.gov(), ["GOV-234"])
        # Modifying the file revokes all baseline protection
        self.s.write("src/core/a.ts", "const y = z as any;\n")
        self.assertEqual(self.s.gov(changed={"src/core/a.ts"}), ["GOV-234"])
        # Fixing the violation triggers GOV-411 to tighten baseline
        self.s.write("src/core/a.ts", "const y = 1;\n")
        self.assertEqual(self.s.gov(), ["GOV-411"])

    def test_artifact_required_rejects_placeholders(self):
        changed = {"src/ui/page.tsx"}
        self.assertEqual(self.s.gov(changed=changed, pr_body="no artifact"), ["GOV-311"])
        self.assertEqual(self.s.gov(changed=changed, pr_body="Artifact: none"), ["GOV-311"])
        self.assertEqual(self.s.gov(changed=changed, pr_body="Artifact: N/A"), ["GOV-311"])
        self.assertEqual(self.s.gov(changed=changed, pr_body="Artifact: https://example.com/rec.mp4"), [])
        self.assertEqual(self.s.gov(changed=changed, pr_body="Artifact: artifacts/statechart.svg"), [])

    def test_invariants_accepts_tests_directory(self):
        cfg = json.loads((self.s.root / ".governance" / "config.json").read_text(encoding="utf-8"))
        cfg["invariant_paths"] = ["src/core/machine.ts"]
        self.s.write(".governance/config.json", json.dumps(cfg))
        self.s.write("src/core/machine.ts", "export const state = 'idle';\n")
        self.assertEqual(self.s.gov(), ["GOV-321"])
        self.s.write("tests/machine.property.test.ts", "test('invariants', () => {});\n")
        self.assertEqual(self.s.gov(), [])


class TeamTests(unittest.TestCase):
    def test_repo_itself_passes_all_team_and_sync_checks(self):
        self.assertEqual([v.render() for v in check_team.run(REPO)], [])
        self.assertEqual([v.render() for v in sync_adapters.check_sync(REPO)], [])

    def test_bad_team_and_plan_dependencies_and_exact_check_ids(self):
        root = Path(tempfile.mkdtemp())
        try:
            (root / ".claude" / "agents").mkdir(parents=True)
            (root / ".claude" / "agents" / "verifier.md").write_text(
                "---\nname: verifier\ndescription: d\nmodel: sonnet\ntools: Read, Edit\n---\n",
                encoding="utf-8",
            )
            (root / ".claude" / "settings.json").write_text(
                json.dumps({"permissions": {"allow": ["Bash(python scripts/check_governance.py:*)"]}}),
                encoding="utf-8",
            )
            (root / "PLAN.md").write_text(
                "## T-001: a\n- Status: verify\n- Owner: builder\n- Files: src/core/\n- Depends on: none\n- Acceptance:\n  - pytest\n"
                "## T-002: b\n- Status: doing\n- Owner: builder\n- Files: ./src/core/api.ts\n- Depends on: T-001\n",
                encoding="utf-8",
            )
            (root / "scripts").mkdir()
            (root / "scripts" / "dummy.py").write_text("GOV_RULE = 'GOV-201'\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_demo.py").write_text("def test_valid_rule():\n    pass\n", encoding="utf-8")
            # 'Check: GOV' must NOT match 'GOV-201' via loose substring; 'Check: test_valid_rule' SHOULD match
            (root / "STATE.md").write_text(
                "## Goal\n## Done (verified PASS)\n## Failed / blocked\n"
                "## Failure log (1st occurrence)\n## Rules learned\n"
                "- loose check Check: GOV\n"
                "- valid test check Check: test_valid_rule\n"
                "## Next\n## Last session\n",
                encoding="utf-8",
            )
            violations = check_team.run(root)
            ids = sorted({v.rule_id for v in violations})
            self.assertEqual(ids, ["TEAM-002", "TEAM-003", "TEAM-004", "TEAM-005", "TEAM-006"])
            # Ensure TEAM-005 flagged only 'GOV' and accepted 'test_valid_rule'
            team005 = [v for v in violations if v.rule_id == "TEAM-005"]
            self.assertEqual(len(team005), 1)
            self.assertIn("'GOV'", team005[0].root_cause)
            # Ensure TEAM-004 caught BOTH dependency-not-done AND normalized dir/file overlap across verify+doing
            team004_causes = "\n".join(v.root_cause for v in violations if v.rule_id == "TEAM-004")
            self.assertIn("dependency T-001", team004_causes)
            self.assertIn("overlap", team004_causes)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_adapter_drift_detected_by_team_007(self):
        root = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(REPO / ".agent-team", root / ".agent-team")
            sync_adapters.sync_all(root)
            self.assertEqual(sync_adapters.check_sync(root), [])
            # Tamper with generated Gemini agent file
            gem_verifier = root / ".gemini" / "agents" / "verifier.md"
            gem_verifier.write_text(gem_verifier.read_text(encoding="utf-8") + "\n# drifted\n", encoding="utf-8")
            drifts = sync_adapters.check_sync(root)
            self.assertEqual([v.rule_id for v in drifts], ["TEAM-007"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class ScopeAndHookTests(unittest.TestCase):
    def test_verify_scope_allowlist_and_baseline_protection(self):
        root = Path(tempfile.mkdtemp())
        try:
            (root / "PLAN.md").write_text(
                "## T-001: sample\n"
                "- Status: doing\n"
                "- Owner: builder\n"
                "- Files: src/core/, tests/test_core.ts\n"
                "- Depends on: none\n"
                "- Acceptance:\n"
                "  - pass\n",
                encoding="utf-8",
            )
            self.assertEqual(
                verify_scope.check_scope(root, "T-001", {"src/core/api.ts", "tests/test_core.ts"}),
                [],
            )
            bad = verify_scope.check_scope(
                root,
                "T-001",
                {"src/ui/sneaky.tsx", ".governance/baseline.json"},
            )
            self.assertEqual(sorted(v.rule_id for v in bad), ["SCOPE-001", "SCOPE-002"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_guard_hook_blocks_dangerous_ops_for_claude_and_gemini(self):
        # Block baseline Edit (Claude) & write_file (Gemini)
        ok, reason = guard_hook.evaluate_event(
            {"tool_name": "Edit", "tool_input": {"file_path": ".governance/baseline.json"}}
        )
        self.assertFalse(ok)
        self.assertIn("GUARD-005", reason)

        ok, reason = guard_hook.evaluate_event(
            {"tool_name": "write_file", "tool_input": {"path": "d:/repo/.governance/baseline.json"}}
        )
        self.assertFalse(ok)
        self.assertIn("GUARD-005", reason)

        # Block --write-baseline via shell (both Bash and run_shell_command)
        for tool in ("Bash", "run_shell_command"):
            ok, reason = guard_hook.evaluate_event(
                {"tool_name": tool, "tool_input": {"command": "python scripts/check_governance.py --write-baseline"}}
            )
            self.assertFalse(ok)
            self.assertIn("GUARD-005", reason)

        # Block force push & hard reset
        ok, reason = guard_hook.evaluate_event(
            {"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}}
        )
        self.assertFalse(ok)
        self.assertIn("GUARD-001", reason)

        # Allow normal governance check
        ok, reason = guard_hook.evaluate_event(
            {"tool_name": "Bash", "tool_input": {"command": "python scripts/check_governance.py"}}
        )
        self.assertTrue(ok)
        self.assertIsNone(reason)

        # Read-only mode blocks mutating shell commands
        ok, reason = guard_hook.evaluate_event(
            {"tool_name": "Bash", "tool_input": {"command": "echo hack > src/core/a.ts"}},
            read_only=True,
        )
        self.assertFalse(ok)
        self.assertIn("GUARD-004", reason)


if __name__ == "__main__":
    unittest.main()
