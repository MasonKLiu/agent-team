# State

> 團隊的長期記憶（80% 通用，跨 session 與跨 AI 工具共享）。每個任務結束後由 orchestrator 更新；每個 session 與每次 verifier 開始前必讀。

## Goal

（從 BRIEF.md 複製）

## Done (verified PASS)

## Failed / blocked

## Failure log (1st occurrence)

> 每次 verifier 回 FAIL 時，orchestrator 必須在此記下 `- [T-XXX] <pattern-key>: <簡述>`，即使該任務重做後 PASS 也要保留。
> verifier 每次驗收前必讀此區；若再次抓到同類錯誤即輸出 `REPEAT: <pattern-key>`，升級為確定性檢查後再移至下方 Rules learned。

## Rules learned

> 每一條都必須對應一條真實存在的確定性檢查（RFC-001 §1.1），格式：`- 描述 Check: <EXACT-RULE-ID-OR-TEST-NAME>`。
> `scripts/check_team.py`（TEAM-005）會驗證該 ID 是否存在於 `scripts/`、`.governance/`、lint 設定或 `tests/`。

## Next

## Last session
