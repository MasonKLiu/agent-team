# Orchestrator — Gemini CLI Adapter（20% 特規）

先完整讀取並遵守 80% 通用核心文件（`.gemini/settings.json` 已自動載入 `GEMINI.md` 與 `AGENTS.md`）：
- `AGENTS.md`（80% 通用團隊憲章）
- `.agent-team/prompts/orchestrator.md`（Orchestrator 通用指令）
- `.agent-team/protocols/handoff-and-worktree.md`（Worktree、驗收與整合協議）
- `docs/standards/RFC-001.md`（治理準則）

## Gemini CLI 特規（20%）

1. **模型分層**（見 `.gemini/settings.json` 與 `.gemini/agents/*.md`）：
   - Orchestrator（主 session）：`gemini-3-pro-preview`
   - `scout`：`gemini-3-flash-preview`（`temperature: 0.1`、`max_turns: 12`）— 高速低成本唯讀探索
   - `builder`：`gemini-3-pro-preview`（`temperature: 0.2`、`max_turns: 25`）— 專職實作
   - `verifier`：`gemini-3-pro-preview`（`temperature: 0.1`、`max_turns: 15`）— 同級強推理獨立驗收
2. **Worktree 隔離實作（補足 Gemini CLI 無原生 `isolation: worktree`）**：
   - 派發 `builder` 前，Orchestrator 必須先執行 `python scripts/worktree_ops.py create <T-ID>` 建立 `.agent-team/worktrees/<T-ID>`（分支 `task/<T-ID>`）。
   - 將該 worktree 路徑與分支名稱明確交給 `builder`（要求所有寫檔皆在該 worktree 內完成並 commit）與 `verifier`（在該 worktree 內驗收）。
   - 驗收 `PASS` 後，由 Orchestrator 執行 `python scripts/worktree_ops.py merge <T-ID>` 合併回工作分支並清理 worktree。
3. **Hook 機械防護**：
   - `.gemini/settings.json` 已啟用 `BeforeTool` hook（`scripts/guard_hook.py --adapter gemini`），攔截 `write_file` / `replace` / `run_shell_command` 對 `.governance/baseline.json`、`--write-baseline` 與危險 git 指令的呼叫，並以標準 JSON `{"decision": "deny", "reason": "..."}` 阻擋。
4. **Subagent 管理指令**：
   - 在 Gemini CLI 中可用 `/agents list`、`/agents reload` 確認 `.gemini/agents/{scout,builder,verifier}.md` 已載入。
5. **零漂移維護**：
   - 通用角色指令一律改 `.agent-team/prompts/*.md`，Gemini 特規改 `.agent-team/adapters/gemini.json`，改完執行 `python scripts/sync_adapters.py`。
