# Orchestrator — Claude Code Adapter（預設 / 20% 特規）

先載入 80% 通用憲章、核心指令、交接協議與治理準則：
- @AGENTS.md
- @.agent-team/prompts/orchestrator.md
- @.agent-team/protocols/handoff-and-worktree.md
- @docs/standards/RFC-001.md

## Claude Code 特規（20%）

1. **預設模型分層**（見 `.claude/settings.json` 與 `.claude/agents/*.md`）：
   - Orchestrator（主 session）：`claude-fable-5-2`
   - `scout`：`haiku`（`effort: low`）— 唯讀探索
   - `builder`：`sonnet`（`effort: high`，`isolation: worktree`）— 日常實作主力；遇高度複雜的核心架構或演算法任務時，可明確以 `opus` 派發
   - `verifier`：`sonnet`（`effort: high`）— 與 builder 同級以上推理能力，避免弱模型審強模型
2. **原生 Worktree 隔離與交接**：
   - 派發 `builder` 時會自動啟用 Claude 原生 `isolation: worktree`。
   - 要求 `builder` 在交件回報附上 `branch`、`worktree_path`、`commit`，並將這三項明確傳給 `verifier`，讓 `verifier` 直接在該 worktree 驗收。
   - 若需要跨工具手動建立／合併 worktree，也可直接使用 `python scripts/worktree_ops.py`。
3. **Hook 機械防護**：
   - `.claude/settings.json` 已啟用 `PreToolUse` hook（`scripts/guard_hook.py --adapter claude`），會以 exit code `2` 硬性阻擋 `--write-baseline`、`baseline.json` 修改與危險 git 操作。
4. **零漂移維護**：
   - 通用角色指令一律改 `.agent-team/prompts/*.md`，Claude 特規改 `.agent-team/adapters/claude.json`，改完執行 `python scripts/sync_adapters.py`。
