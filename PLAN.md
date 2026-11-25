# Plan

> 由 orchestrator 撰寫。每個任務都要有 `Status`、`Owner`、`Files`、`Depends on` 與 `Acceptance`，`scripts/check_team.py` 與 `scripts/verify_scope.py` 會檢查。
> Status 可用值：`todo` / `doing` / `verify` / `done` / `blocked`
> Owner 可用值：`builder` / `scout` / `verifier` / `orchestrator`

<!-- 任務範本（複製後改 ID）：

## T-001: 封裝宣告式資料訂閱 Hook
- Status: todo
- Owner: builder
- Files: src/core/useSubscription.ts, tests/useSubscription.test.ts
- Depends on: none
- Acceptance:
  - `npm test -- tests/useSubscription.test.ts` 全部通過
  - `python scripts/check_governance.py` 無違規
  - `src/core/useSubscription.ts` 匯出完整 TypeScript 型別定義

-->
