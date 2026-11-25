# 80/20 跨 AI 適配架構規範

本框架將多 Agent 團隊設計嚴格切分為 **80% 通用核心** 與 **20% AI 平台特規（Adapter）**，確保切換 AI 工具時治理準則、角色邊界與自動化防線完全一致，且不會因人工複製貼上產生漂移（drift）。

---

## 1. 切分原則（What Goes Where）

### 80% 通用層（與 AI 廠商無關）
| 資產 | 路徑 | 職責 |
|---|---|---|
| 團隊憲章 | `AGENTS.md` | 所有 AI 共同遵守的角色邊界與 10 條核心規範 |
| 治理準則 | `docs/standards/RFC-001.md` | 靜態分層、API 衛生、Ratchet 與 Merge Gates |
| 團隊清單 | `.agent-team/config.json` | 預設與啟用的 Adapter、標準角色與權限矩陣 |
| 標準角色指令 | `.agent-team/prompts/*.md` | 單一事實來源（SSOT）：`orchestrator` / `scout` / `builder` / `verifier` |
| 交接協議 | `.agent-team/protocols/*.md` | Worktree、Scope Gate、合併、Integration Gate、`REPEAT:` 升級 |
| 任務與記憶檔 | `BRIEF.md`、`PLAN.md`、`STATE.md` | 跨 session、跨 AI 工具共享的持久化狀態 |
| 確定性防線 | `scripts/*.py`、`.governance/config.json`、`.github/workflows/team-check.yml` | 零依賴 Python 檢查器、Hook 守衛引擎、Worktree 工具、CI |

### 20% 特規層（依 AI 平台能力與檔案格式適配）
| 面向 | Claude Code（預設） | Gemini CLI |
|---|---|---|
| 入口檔 | `CLAUDE.md`（使用 `@path` 引入） | `GEMINI.md`（透過 `.gemini/settings.json` `context.fileName` 載入） |
| 平台設定 | `.claude/settings.json` | `.gemini/settings.json` |
| Subagent 定義 | `.claude/agents/*.md`（`model`, `effort`, `isolation`, 逗號 `tools`） | `.gemini/agents/*.md`（`kind`, `model`, `temperature`, `max_turns`, YAML 清單 `tools`） |
| 模型分層 | `claude-fable-5-2` / `sonnet` / `haiku` | `gemini-3-pro-preview` / `gemini-3-flash-preview` |
| 工具命名 | `Read`, `Grep`, `Glob`, `Edit`, `Write`, `Bash` | `read_file`, `grep_search`, `glob`, `write_file`, `replace`, `run_shell_command` |
| Worktree 隔離 | 原生 `isolation: worktree` | 透過 `scripts/worktree_ops.py` 建立與合併 |
| Hook 協議 | `PreToolUse` → `guard_hook.py --adapter claude`（exit code `2` + stderr 阻擋） | `BeforeTool` → `guard_hook.py --adapter gemini`（exit code `0` + JSON `{"decision":"deny"}` 阻擋） |

---

## 2. 零漂移機制（Single Source of Truth）

不要手動分頭修改 `.claude/agents/*.md` 或 `.gemini/agents/*.md` 的通用規範：
1. 調整通用角色邏輯 → 修改 `.agent-team/prompts/<role>.md`。
2. 調整特定 AI 的模型、工具或特規附註 → 修改 `.agent-team/adapters/<adapter>.json`。
3. 執行同步腳本重新產生 20% 檔案：
   ```powershell
   python scripts/sync_adapters.py
   ```
4. CI 與本機執行 `python scripts/check_team.py` 時，`TEAM-007` 會自動驗證 20% 檔案是否與 80% 來源完全同步。

---

## 3. 如何擴充新的 AI 平台（例如 Codex、Cursor）

1. 在 `.agent-team/adapters/<name>.json` 新增該 AI 的模型分層、工具名稱、檔案格式與特規附註。
2. 在 `.agent-team/config.json` 的 `enabled_adapters` 與 `adapters` 註冊它。
3. 在 `scripts/sync_adapters.py` 與 `scripts/guard_hook.py` 補上該平台的輸出格式與 hook 協議（若有）。
4. 執行 `python scripts/sync_adapters.py` 並跑 `python scripts/check_team.py` 確認全部規則通過。
