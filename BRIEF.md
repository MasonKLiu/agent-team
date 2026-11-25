# Brief

> 這份是你（人）交給團隊的任務書。每次開新任務就改寫這份。

## Goal

（一句話寫你要達成什麼）

## Done when

（任何人都能執行的檢查，例如：`npm test` 全部通過、`curl localhost:3000/health` 回 200）

- [ ] `python -m unittest discover -s tests` 通過
- [ ] `python scripts/check_team.py` 通過
- [ ] `python scripts/check_governance.py` 通過

## Ask me before

- 部署到任何環境
- 刪除資料或檔案（worktree 內的暫存檔除外）
- 新增外部依賴套件
- push 到 `main` / 建立 PR
- 任何花錢或對外發送訊息的動作

## Context

- 預設 AI Adapter：`claude`（可選：`gemini`，見 `.agent-team/protocols/adapters.md`）
- （補充相關連結、限制、偏好）
