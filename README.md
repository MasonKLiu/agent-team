# Agent Team

用「一個 orchestrator + 多個專職 worker」取代「一個什麼都做的 agent」的 Claude Code 專案骨架。

## 為什麼要 team，而不是單一 agent

單一 agent 的問題：

1. **貴的模型在做便宜的事**：搜尋檔案、讀程式碼、跑測試，都在燒最強模型的 token。
2. **自己改自己的考卷**：同一個 context 寫的程式碼，由同一個 context 驗收，很容易「自己同意自己」。
3. **context 會爆**：長任務把所有探索過程都塞進同一個視窗，越跑越笨，重開就全忘。
4. **無法平行**：一次只能做一件事。

Agent team 的解法：

| 問題 | 解法 |
|---|---|
| 成本 | 強模型只做規劃與決策，大量工作交給便宜模型 |
| 自我驗收 | 由獨立的 verifier 判定 PASS / FAIL，maker 不能 grade 自己 |
| context 爆掉 | 每個 subagent 有自己的 context，只回傳精簡結果；進度寫進 `STATE.md` |
| 平行 | 不同檔案的任務交給多個 builder，各自在獨立 worktree |

## 團隊組成

```
                 ┌───────────────────────────┐
     你 ───────▶ │ Orchestrator (主 session)  │  規劃、分派、做決定
     BRIEF.md    │ CLAUDE.md / AGENTS.md      │  讀寫 PLAN.md、STATE.md
                 └─────┬──────────┬──────────┬┘
                       │          │          │
              ┌────────▼──┐ ┌─────▼─────┐ ┌──▼────────┐
              │  scout    │ │  builder  │ │ verifier  │
              │  haiku    │ │  opus     │ │ sonnet    │
              │  唯讀探索  │ │  一次一個  │ │  唯讀驗收  │
              │  回傳摘要  │ │  任務     │ │ PASS/FAIL │
              └───────────┘ │ worktree  │ └───────────┘
                            └───────────┘
```

| 角色 | 檔案 | 模型 | 權限 | 職責 |
|---|---|---|---|---|
| Orchestrator | `CLAUDE.md` | 主 session（最強模型） | 全部 | 拆任務、寫 PLAN、分派、整合、決策 |
| Scout | `.claude/agents/scout.md` | haiku | Read/Grep/Glob | 找檔案、讀程式碼，只回傳路徑與短摘錄 |
| Builder | `.claude/agents/builder.md` | opus | 可寫，worktree 隔離 | 完成 PLAN 中的「一個」任務 |
| Verifier | `.claude/agents/verifier.md` | sonnet | 唯讀 + Bash 跑測試 | 依驗收條件判 PASS / FAIL |

## 工作流程

1. 你填寫 `BRIEF.md`：目標、完成條件（可執行的檢查）、哪些事要先問你。
2. Orchestrator 派 scout 摸清 repo，寫出 `PLAN.md`（小任務，每個都有驗收條件）。
3. 每個任務交給 builder；改不同檔案的任務可平行。
4. Builder 完成後一律交給 verifier。FAIL 帶著 verifier 的意見退回 builder，不是丟給你。
5. 每個任務結束都更新 `STATE.md`；新 session 開始時先讀它。
6. 同一個錯被 verifier 抓到兩次 → 先把它寫成一條自動檢查，再記到 `STATE.md` 的「Rules learned」並標註 `Check: <RULE-ID>`（RFC-001 §1.1：不准只靠 prompt 修正）。
7. 只有真正的 blocker 或 `BRIEF.md` 列出的「先問我」事項才停下來找你。

## 目錄結構

```
.
├── CLAUDE.md                 # Orchestrator 的指令（Claude Code 自動載入）
├── AGENTS.md                 # 跨工具通用的團隊規範（Codex 等工具也讀）
├── BRIEF.md                  # 你給團隊的任務書
├── PLAN.md                   # Orchestrator 寫的任務清單
├── STATE.md                  # 長期記憶：完成、失敗、學到的規則、下一步
├── .claude/
│   ├── settings.json         # 主 session 模型、權限、hooks
│   └── agents/               # subagent 定義
│       ├── scout.md
│       ├── builder.md
│       └── verifier.md
├── .governance/
│   └── config.json           # 分層、禁用語法、escape hatch 規則
├── src/{core,domain,ui}/     # RFC-001 §2.2 分層
├── tests/                    # 檢查器本身的測試
├── docs/
│   ├── ARCHITECTURE.md       # 設計說明
│   └── standards/
│       └── RFC-001.md        # 團隊治理準則
├── scripts/
│   ├── check_team.py         # 團隊結構檢查（TEAM-*）
│   └── check_governance.py   # RFC-001 程式碼檢查（GOV-*）
└── .github/workflows/
    └── team-check.yml        # CI 上跑同一份檢查
```

## 開始使用

```powershell
cd D:\AI\Agent_Team
python -m unittest discover -s tests
python scripts/check_team.py
python scripts/check_governance.py
claude
```

把既有專案搬進 `src/` 時，先跑 `python scripts/check_governance.py --write-baseline` 建立 ratchet baseline（見 `docs/ARCHITECTURE.md`）。

進入 Claude Code 後，先編輯 `BRIEF.md`，再對 orchestrator 說：「讀 BRIEF.md 開始工作」。

## 準則

團隊治理以 [`docs/standards/RFC-001.md`](docs/standards/RFC-001.md) 為準。能自動檢查的規則都寫在 `scripts/check_team.py`，本機與 CI 都會跑。
