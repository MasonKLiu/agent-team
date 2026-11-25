# 團隊共同規範（80% 通用憲章）

本檔案是跨 AI 平台（Claude Code、Gemini CLI、Codex 等）共同遵守的 **80% 通用規範**。
- 平台特規（20%）：Claude 見 `CLAUDE.md` 與 `.claude/`（預設）；Gemini 見 `GEMINI.md` 與 `.gemini/`。
- 單一事實來源（SSOT）：角色指令與協議統一維護於 `.agent-team/`，由 `scripts/sync_adapters.py` 同步至各 AI 平台。
- 治理準則完整版本見 `docs/standards/RFC-001.md`；衝突時以 RFC-001 為準。

## 角色與邊界

| 角色 | 存取層級 | 可以 | 不可以 |
|---|---|---|---|
| `orchestrator` | coordinator | 規劃、寫 `PLAN.md` / `STATE.md`、派工、合併 PASS 分支、做決策 | 親自大規模實作、**親自判定任務 PASS** |
| `scout` | read-only | 讀檔、搜尋、回報路徑與短摘錄 | 修改任何檔案、執行有副作用指令、提實作方案 |
| `builder` | write (isolated) | 在獨立 worktree 內修改 `PLAN.md` 指定 `Files` 範圍的檔案並 commit | 改 `Files` 以外檔案、改 Acceptance、動 `baseline.json`、驗收自己 |
| `verifier` | read-only-exec | 讀 `STATE.md`、在目標 worktree 跑範圍/測試/治理檢查並判 `PASS`/`FAIL` | 修改任何檔案、替 builder 修 bug、信任 builder 自述 |

## 10 條核心通用準則

1. **Maker 不驗收自己**：產出者（`builder`）與驗收者（`verifier`）必須隔離；`orchestrator` 也不可自判 PASS。
2. **一次一個任務與嚴格範圍鎖定**：`builder` 每次只做 `PLAN.md` 的一個任務 ID，且實際 `git diff` 必須通過 `scripts/verify_scope.py`（不得超出 `Files` 白名單）。
3. **任務必須可驗收且宣告依賴**：每個任務都要有 `Owner`、`Files`、`Depends on`、`Acceptance`（至少一條可執行指令或可觀察結果）。
4. **平行不重疊 + 合併後整合驗證**：所有進行中（`doing` 與 `verify`）任務的 `Files` 不可重疊（含正規化路徑與目錄前綴）；同時合併 ≥ 2 個平行任務後必須重跑整合驗證。
5. **完整 Worktree → Verifier → Merge 交接**：詳見 `.agent-team/protocols/handoff-and-worktree.md`。Builder 必須在隔離 worktree commit 並回報 `worktree_path` / `branch` / `commit`，Verifier 必須在該目標環境驗證，PASS 後才由 Orchestrator 合併。
6. **跨 Session 錯誤帳本與 `REPEAT:` 升級（RFC-001 §1.1）**：首次 `FAIL` 必記於 `STATE.md`「Failure log (1st occurrence)」；Verifier 每次必讀它，抓到第二次即輸出 `REPEAT: <pattern-key>`，由 Orchestrator 開專門治理任務寫成確定性檢查，再寫入 `Rules learned` 並標註 `Check: <RULE-ID>`。
7. **狀態落地**：所有進度、失敗紀錄、規則與下一步一律寫入 `PLAN.md` / `STATE.md`，不依賴對話記憶。
8. **明確模型分層**：每個啟用 Adapter 的 subagent 都必須明示 `model`，禁止隱性繼承主 session 的昂貴模型，且 Verifier 模型能力不得低於 Builder。
9. **最小權限 + Hook 機械防護**：唯讀角色不給寫入工具；所有具 shell 權限的角色皆受 `scripts/guard_hook.py` 攔截危險指令與 baseline 篡改。
10. **危險動作先問人**：`BRIEF.md`「Ask me before」清單、缺資訊、或同一任務連 FAIL 3 次，一律停下來詢問人類。

## 固定回報格式

- **scout**：`路徑:行號` + ≤ 10 行摘錄；最後 1–2 句客觀結論。
- **builder**：`Task ID`、`Branch`、`Worktree Path`、`Commit`、`Changed Files`、`Self-Check Output`、`Uncertainties`。
- **verifier**：第一行只能是 `PASS` 或 `FAIL`；`FAIL` 逐條附證據與根因；若命中 `Failure log` 則於文末加 `REPEAT: <pattern-key> — <簡述>`。
