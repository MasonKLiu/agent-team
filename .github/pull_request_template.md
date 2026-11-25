## 任務

- PLAN 任務 ID：`T-`
- 使用的 AI Adapter：`claude`（預設） / `gemini`

## 驗收

- [ ] `verifier` 獨立驗收結論：`PASS`（貼上 verifier 輸出第一行、驗證 commit 與摘要）
- [ ] `python scripts/verify_scope.py --task T-XXX --base main` 通過
- [ ] `python scripts/check_governance.py --changed-from main` 通過
- [ ] `python scripts/check_team.py`（含 `TEAM-007` 80/20 同步）通過
- [ ] `python -m unittest discover -s tests` 通過

## Review artifact（RFC-001 §3.1）

觸及 `src/ui/` 或 `src/core/` 時必填，CI 會檢查（`GOV-311`，必須為真實 URL、Markdown 連結或檔案路徑；不接受 `none` / `N/A`）。

Artifact:

## SHOULD 條款的偏離（RFC-001 §0）

（沒有就留空。有的話附上量化理由。）
