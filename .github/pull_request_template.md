## 任務

- PLAN 任務 ID：`T-`
- 使用的 AI Adapter：`claude`（預設） / `gemini`

## 驗收

- [ ] `verifier` 獨立驗收結論：`PASS`（貼上 verifier 輸出第一行、驗證 commit 與摘要）
- [ ] `python scripts/verify_scope.py --task T-XXX --base main` 通過
- [ ] `python scripts/check_governance.py --changed-from main` 通過
- [ ] `python scripts/check_team.py`（含 `TEAM-007` 80/20 同步）通過
- [ ] `python -m unittest discover -s tests` 通過
