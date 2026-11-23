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

TODAY = dt.date(2026, 11, 23)


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

    def test_reverse_layer_import_fails(self):
        self.s.write("src/ui/page.tsx", "export const p = 1;\n")
        self.s.write("src/core/api.ts", "import { p } from '../ui/page';\n")
        self.assertEqual(self.s.gov(), ["GOV-221"])

    def test_cycle_fails(self):
        self.s.write("src/core/a.ts", "import './b';\n")
        self.s.write("src/core/b.ts", "import './a';\n")
        self.assertEqual(self.s.gov(), ["GOV-222"])

    def test_use_effect_banned_in_ui_only(self):
        self.s.write("src/ui/c.tsx", "useEffect(() => {}, []);\n")
        self.s.write("src/core/hooks.ts", "useEffect(() => {}, []);\n")
        self.assertEqual(self.s.gov(), ["GOV-201"])

    def test_suppressions(self):
        self.s.write("src/core/a.ts", "// @ts-ignore\n")
        self.s.write("src/core/b.ts", "// @ts-ignore expires=2026-01-01 ticket=ABC-1\n")
        self.s.write("src/core/c.ts", "// @ts-ignore expires=2027-01-01 ticket=ABC-2\n")
        self.assertEqual(self.s.gov(), ["GOV-231", "GOV-232"])

    def test_comment_and_assertion(self):
        self.s.write("src/core/a.ts", "// because the API is flaky\nconst y = z as any;\n")
        self.assertEqual(self.s.gov(), ["GOV-233", "GOV-234"])

    def test_ratchet(self):
        self.s.write("src/core/a.ts", "const y = z as any;\n")
        self.s.write(".governance/baseline.json", json.dumps({"violations": [["GOV-234", "src/core/a.ts"]]}))
        self.assertEqual(self.s.gov(), [])
        self.assertEqual(self.s.gov(changed={"src/core/a.ts"}), ["GOV-234"])
        self.s.write("src/core/a.ts", "const y = 1;\n")
        self.assertEqual(self.s.gov(), ["GOV-411"])

    def test_artifact_required(self):
        changed = {"src/ui/page.tsx"}
        self.assertEqual(self.s.gov(changed=changed, pr_body="no artifact"), ["GOV-311"])
        self.assertEqual(self.s.gov(changed=changed, pr_body="Artifact: https://example.com/rec.mp4"), [])


class TeamTests(unittest.TestCase):
    def test_repo_itself_passes(self):
        self.assertEqual([v.render() for v in check_team.run(REPO)], [])

    def test_bad_team(self):
        root = Path(tempfile.mkdtemp())
        try:
            (root / ".claude" / "agents").mkdir(parents=True)
            (root / ".claude" / "agents" / "verifier.md").write_text(
                "---\nname: verifier\ndescription: d\nmodel: sonnet\ntools: Read, Edit\n---\n", encoding="utf-8")
            (root / "PLAN.md").write_text(
                "## T-001: a\n- Status: doing\n- Files: a.py\n- Acceptance:\n  - pytest\n"
                "## T-002: b\n- Status: doing\n- Files: a.py\n", encoding="utf-8")
            (root / "STATE.md").write_text("## Rules learned\n- always do X\n", encoding="utf-8")
            ids = sorted({v.rule_id for v in check_team.run(root)})
            self.assertEqual(ids, ["TEAM-002", "TEAM-003", "TEAM-004", "TEAM-005", "TEAM-006"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
