# 團隊共同規範（所有 agent 都要遵守）

本檔案是跨工具的通用規範，Claude Code 透過 `CLAUDE.md` 引入，其他支援 AGENTS.md 的工具也會讀取。
治理準則的完整版本見 `docs/standards/RFC-001.md`；兩者衝突時以 RFC-001 為準。

## 角色與邊界

| 角色 | 可以 | 不可以 |
|---|---|---|
| orchestrator | 規劃、分派、寫 PLAN.md / STATE.md、做決策 | 親自判定任務 PASS |
| scout | 讀檔、搜尋 | 修改任何檔案 |
| builder | 在自己的 worktree 內修改 PLAN 指定範圍的檔案 | 做 PLAN 以外的任務、改驗收條件、驗收自己 |
| verifier | 讀檔、跑測試與檢查指令 | 修改任何檔案、替 builder 修 bug |

## 核心規則

1. **Maker 不驗收自己**：產出的 agent 與驗收的 agent 必須不同。
2. **一次一個任務**：builder 每次只處理 PLAN.md 裡的一個任務 ID。
3. **任務必須可驗收**：PLAN.md 每個任務都要有「Acceptance」，且至少一條是可執行的指令或可觀察的結果。
4. **平行不重疊**：同時進行的 builder 任務，其「Files」不可重疊。
5. **狀態落地**：所有進度寫進 `STATE.md`，不依賴對話記憶。
6. **每個 subagent 都要指定 model**：沒有 model 的 subagent 會繼承主 session 的昂貴模型。
7. **最小權限**：subagent 只拿完成職責所需的工具。
8. **危險動作先問**：`BRIEF.md` 的「Ask me before」清單裡的動作，一律先停下來問人。

## 回報格式

- scout：檔案路徑 + 行號 + 不超過 10 行的摘錄，最後一句結論。
- builder：改了哪些檔案、怎麼自我檢查的、還有什麼不確定。
- verifier：第一行 `PASS` 或 `FAIL`；FAIL 時逐條列出未達成的驗收條件與證據。
