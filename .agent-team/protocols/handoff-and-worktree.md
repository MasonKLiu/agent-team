# Worktree、驗收交接與重複錯誤升級協議（80% 通用）

本協議補齊多 Agent 平行開發中最容易斷鏈的四個環節：**隔離建立 → 範圍驗證 → 驗收與合併 → 重複錯誤升級**。Claude（原生 `isolation: worktree`）與 Gemini（透過 `scripts/worktree_ops.py`）共用同一套交接契約。

---

## 1. 狀態機（Task Lifecycle）

```
todo ──(派 builder + 建 worktree)──▶ doing
doing ──(builder commit + 交件)────▶ verify
verify ──(verifier PASS + 合併)────▶ done
verify ──(verifier FAIL < 3次)─────▶ doing   (先寫 Failure log，再退回原 worktree)
verify ──(連續 FAIL 3次)───────────▶ blocked (升級人類介入)
```

---

## 2. 標準交接步驟

### Step A：派工與隔離建立
1. Orchestrator 檢查 `PLAN.md`：
   - 該任務的 `Depends on` 全部皆為 `done`。
   - 該任務的 `Files` 與所有 `doing` / `verify` 任務完全無重疊（含目錄前綴）。
2. 將任務狀態更新為 `doing`，執行 `python scripts/check_team.py` 驗證無衝突。
3. 建立隔離環境：
   - **Claude Adapter**：派發 `builder` subagent（frontmatter 內建 `isolation: worktree`）。
   - **Gemini Adapter**（或其他無內建 worktree 的 AI）：Orchestrator 先執行 `python scripts/worktree_ops.py create <T-ID>`，再將回傳的 `.agent-team/worktrees/<T-ID>` 與分支 `task/<T-ID>` 傳給 `builder`。

### Step B：Builder 實作與交件
1. Builder 僅修改 `Files` 清單內檔案。
2. 交件前在 worktree 內執行：
   - `python scripts/verify_scope.py --task <T-ID>`
   - `python scripts/check_governance.py`
   - 任務 `Acceptance` 指令
3. Builder 將改動 commit 到該 worktree 分支（`task(<T-ID>): ...`），保持工作目錄乾淨，並以結構化欄位回報 Orchestrator：
   - `Task ID`、`Branch`、`Worktree Path`、`Commit`、`Changed Files`、`Self-Check Output`、`Uncertainties`。

### Step C：Verifier 獨立驗收（在目標 Worktree 執行）
1. Orchestrator 將任務狀態更新為 `verify`，並把 `Task ID`、`Worktree Path`、`Branch`、`Base Ref`（通常是 `HEAD` 或 `main`）傳給 `verifier`。
2. Verifier **先讀 `STATE.md`**（含 `Failure log` 與 `Rules learned`），再到指定 `Worktree Path` 執行：
   - `python scripts/verify_scope.py --task <T-ID> --base <base_ref>`
   - 任務 `Acceptance` 的每條檢查
   - `python scripts/check_governance.py --changed-from <base_ref>`
   - `python scripts/check_team.py`
3. Verifier 確認自身沒有修改任何檔案，輸出第一行為 `PASS` 或 `FAIL`。

### Step D：合併與平行整合驗證
- **若 `PASS`**：
  1. Orchestrator 在主工作目錄合併該任務分支（`python scripts/worktree_ops.py merge <T-ID>` 或對原生 worktree 分支執行 `git merge --no-ff <branch>`）並清理 worktree。
  2. 更新 `PLAN.md` 狀態為 `done`，更新 `STATE.md`「Done (verified PASS)」。
  3. **整合驗證（Integration Gate）**：若本輪平行合併了 **≥ 2 個任務**，合併完成後必須在主工作目錄重跑一次完整測試 + `python scripts/check_governance.py` + `python scripts/check_team.py`，攔截跨任務介面衝突與跨檔循環依賴。
- **若 `FAIL`**：
  1. Orchestrator 在 `STATE.md`「Failure log (1st occurrence)」記錄 `- [<T-ID>] <pattern-key>: <簡述>`（**即使下一輪修好也要保留，作為跨 session 重複偵測依據**）。
  2. 若 Verifier 輸出含 `REPEAT: <pattern-key>`，見第 3 節升級流程。
  3. 若未達 3 次，將任務狀態改回 `doing`，把 Verifier 意見原封不動退回 builder 在同一個 worktree / 分支續修。
  4. 連續 3 次 `FAIL` 則改為 `blocked` 並停止詢問人類。

---

## 3. 重複錯誤升級為確定性檢查（RFC-001 §1.1 閉環）

1. Verifier 比對 `STATE.md` 的「Failure log (1st occurrence)」，若同類錯誤再次出現，輸出 `REPEAT: <pattern-key> — <簡述>`。
2. Orchestrator 在 `PLAN.md` 建立一個獨立治理任務（例如 `T-015: Add GOV-XXX / test_xxx check for <pattern-key>`），明確在 `Files` 授權修改對應檢查檔（`scripts/check_governance.py`、`.governance/config.json` 或 `tests/...`）。
3. 派 `builder` 實作確定性檢查與對應單元測試 → 經 `verifier` 驗證 `PASS` → 合併。
4. Orchestrator 將條目從「Failure log」升級至「Rules learned」，格式為：
   `- <簡述> Check: <EXACT-RULE-ID-OR-TEST-NAME>`
5. 執行 `python scripts/check_team.py`，由 `TEAM-005` 確認該 Check ID 真實存在於 `scripts/`、`.governance/`、lint 設定或 `tests/` 中。
