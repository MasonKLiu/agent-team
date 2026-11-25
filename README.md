# Agent Team（v2 — 80/20 跨 AI 工程治理框架）

一套參考 GitHub 最佳多 Agent 實踐（Orchestrator–Worker、Generator–Critic、Superpowers Verification-Before-Completion、Git Worktree 隔離、Deterministic Hook Guard）並整合 **RFC-001 工程治理準則** 的 Agent Team 骨架。

採用 **80% 通用核心 + 20% AI 平台特規（Adapter）** 設計：
- **預設 AI**：Claude Code（`CLAUDE.md` + `.claude/`）
- **內建第二 AI**：Gemini CLI（`GEMINI.md` + `.gemini/`）
- **單一事實來源（SSOT）**：所有通用角色指令與協議統一維護在 `.agent-team/`，透過 `scripts/sync_adapters.py` 自動同步至各平台，由 CI 鎖死零漂移。

---

## 為什麼採用 80/20 Agent Team

| 傳統單一 Agent 痛點 | 本框架解法 |
|---|---|
| 貴模型在做便宜搜尋、context 膨脹 | 強模型 Orchestrator 負責規劃與決策；便宜 `scout` 專責唯讀探索；獨立 context + `STATE.md` 持久化記憶 |
| 自己改自己考卷 | `builder` 不可自判 PASS；獨立 `verifier`（能力不低於 builder）在隔離 worktree 跑確定性驗收 |
| 平行寫檔互踩、交接斷裂 | 完整 **Worktree → Scope Gate → Verifier → Merge → Integration Gate** 交接協議 |
| 靠 prompt 補丁治標不治本 | `STATE.md` 內建 `Failure log (1st occurrence)`，同類錯誤第二次必升級為確定性檢查（RFC-001 §1.1） |
| 換 AI 工具整套規則重寫又漂移 | 80% 規範與防線完全跨平台共用；20% 僅處理各 AI 的模型、工具名、Worktree 與 Hook 協議 |

---

## 團隊角色與模型分層（預設 Claude / 另支援 Gemini）

```
                    ┌──────────────────────────────────────┐
     你 ──────────▶ │  Orchestrator (主 session)            │  規劃、拆解、派工、合併、決策
     BRIEF.md       │  Claude: claude-fable-5-2 (預設)      │  讀寫 PLAN.md / STATE.md
                    │  Gemini: gemini-3-pro-preview        │  絕不可自判 PASS
                    └──────┬───────────────┬──────────────┬┘
                           │               │              │
                  ┌────────▼───┐  ┌────────▼────┐  ┌──────▼──────┐
                  │   scout    │  │   builder   │  │  verifier   │
                  │ 唯讀探索    │  │ 一次一個任務 │  │  獨立驗收    │
                  │ haiku /    │  │ worktree隔離 │  │ Scope+Gates │
                  │ 3-flash    │  │ sonnet /    │  │ sonnet(hi)/ │
                  └────────────┘  │ 3-pro       │  │ 3-pro       │
                                  └─────────────┘  └─────────────┘
```

| 角色 | 權限層級 | Claude Code（預設 20%） | Gemini CLI（20%） | 職責 |
|---|---|---|---|---|
| **Orchestrator** | coordinator | `claude-fable-5-2` | `gemini-3-pro-preview` | 拆任務、寫 `PLAN.md`/`STATE.md`、合併 PASS 分支 |
| **Scout** | read-only | `haiku` (`effort: low`) | `gemini-3-flash-preview` (`max_turns: 12`) | 唯讀定位檔案與摘要回報 |
| **Builder** | write (worktree) | `sonnet` (`effort: high`, 原生 `isolation: worktree`；高難度任務可升 `opus`) | `gemini-3-pro-preview` (`max_turns: 25`, 搭配 `worktree_ops.py`) | 完成 `PLAN.md` 單一任務並 commit |
| **Verifier** | read-only-exec | `sonnet` (`effort: high`, 無寫入工具 + `PreToolUse` hook) | `gemini-3-pro-preview` (`max_turns: 15`, 無寫入工具 + `BeforeTool` hook) | 於目標 worktree 驗收 `PASS`/`FAIL` 與 `REPEAT:` |

---

## 工作流程（完整閉環）

1. 你填寫 `BRIEF.md`：目標、可執行的「Done when」、與「Ask me before」紅線清單。
2. Orchestrator 讀 `STATE.md` 與 `BRIEF.md`，派 `scout` 摸清 repo，撰寫 `PLAN.md`（每任務含 `Status`、`Owner`、`Files`、`Depends on`、`Acceptance`）。
3. Orchestrator 為任務建立隔離 worktree（Claude 原生；Gemini 用 `scripts/worktree_ops.py create <T-ID>`），派 `builder` 實作並 commit。
4. `builder` 交件前跑 `verify_scope.py`、`check_governance.py` 與 Acceptance，回報 `worktree_path`、`branch`、`commit`。
5. Orchestrator 將狀態改為 `verify`，派 `verifier` **進入該 worktree** 獨立執行 Scope Gate + Acceptance + RFC-001 Gates + `check_team.py`，並對照 `STATE.md` 的 `Failure log`。
6. 若 `FAIL`：先記進 `STATE.md`「Failure log (1st occurrence)」，退回 builder 重做（連 FAIL 3 次算 blocker）；若命中重複錯誤輸出 `REPEAT:`，開治理任務寫成確定性檢查，再寫入 `Rules learned`（`Check: <RULE-ID>`）。
7. 若 `PASS`：Orchestrator 合併分支並清理 worktree；若同批合併 ≥ 2 個平行任務，重跑一次整合驗證。

---

## 目錄結構（80% 通用 / 20% 特規）

```
.
├── AGENTS.md                         # [80%] 跨 AI 團隊憲章（10 條通用準則）
├── BRIEF.md                          # [80%] 人類交給團隊的任務書
├── PLAN.md                           # [80%] 任務清單（含 Files、Depends on、Acceptance）
├── STATE.md                          # [80%] 長期記憶（含 Failure log 與 Rules learned）
├── .agent-team/                      # [80%] 團隊單一事實來源（SSOT）
│   ├── config.json                   #       預設/啟用 Adapter 與角色矩陣
│   ├── prompts/                      #       orchestrator / scout / builder / verifier 通用指令
│   ├── protocols/                    #       Worktree 交接協議、80/20 Adapter 規範
│   └── adapters/                     #       claude.json / gemini.json（20% 特規宣告）
├── CLAUDE.md                         # [20%] Claude Code 入口（預設）
├── .claude/
│   ├── settings.json                 #       Claude 模型、細粒度權限、PreToolUse Hook
│   └── agents/*.md                   #       由 sync_adapters.py 產生（禁手改）
├── GEMINI.md                         # [20%] Gemini CLI 入口
├── .gemini/
│   ├── settings.json                 #       Gemini 模型、context 載入、BeforeTool Hook
│   └── agents/*.md                   #       由 sync_adapters.py 產生（禁手改）
├── .governance/
│   └── config.json                   # [80%] 分層、禁用原語、中英補丁註解與豁免規則
├── src/{core,domain,ui}/             # [80%] RFC-001 §2.2 單向依賴分層
├── scripts/
│   ├── _report.py                    #       RFC-001 §1.2 自癒錯誤格式與路徑工具
│   ├── check_team.py                 #       TEAM-001..007 團隊與跨平台結構檢查
│   ├── check_governance.py           #       GOV-* 靜態分層、多行 import、計數型 Ratchet
│   ├── verify_scope.py               #       SCOPE-001..002 PLAN.md Files 白名單檢查
│   ├── guard_hook.py                 #       GUARD-001..005 跨 Claude/Gemini 工具攔截 Hook
│   ├── sync_adapters.py              #       80/20 Subagent 同步與漂移檢查
│   └── worktree_ops.py               #       跨平台 Worktree 建立／合併／清理工具
├── tests/test_checks.py              #       所有檢查器與 Hook 的單元測試
├── docs/
│   ├── ARCHITECTURE.md               #       架構說明與設計決策
│   └── standards/RFC-001.md          #       工程治理準則與 Enforcement Map
└── .github/workflows/team-check.yml  #       CI Merge Gates（PR 與 push 皆保護）
```

---

## 開始使用

### 1. 驗證框架本身

```powershell
cd D:\AI\Agent_Team
python -m unittest discover -s tests -v
python scripts/sync_adapters.py --check
python scripts/check_team.py
python scripts/check_governance.py
```

導入既有專案至 `src/` 時（限人類執行）：
```powershell
$env:ALLOW_BASELINE_WRITE = "1"
python scripts/check_governance.py --write-baseline
```

### 2. 使用預設 AI：Claude Code

```powershell
claude
```
先填寫 `BRIEF.md`，再告訴 Orchestrator：「讀 `BRIEF.md` 與 `STATE.md` 開始工作」。

### 3. 切換使用 Gemini CLI

```powershell
gemini
```
進入後可用 `/agents list` 確認 `.gemini/agents/{scout,builder,verifier}.md` 已載入，再告訴 Orchestrator：「讀 `BRIEF.md` 與 `STATE.md` 開始工作」。

### 4. 修改規則或角色指令

- 改通用規則 → 編輯 `.agent-team/prompts/<role>.md`
- 改平台特規 → 編輯 `.agent-team/adapters/{claude,gemini}.json`
- 重新同步並檢查：
  ```powershell
  python scripts/sync_adapters.py
  python scripts/check_team.py
  ```
