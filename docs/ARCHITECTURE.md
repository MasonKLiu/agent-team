# 架構說明（v2 — 80/20 跨 AI 工程治理框架）

## 設計來源與 GitHub 最佳實踐整合

本框架整合了目前開源社群與主流實戰驗證過的四套核心模式：

1. **Orchestrator–Worker + Generator–Critic**（Anthropic Multi-Agent Research System、Claude Code Subagents）：主 session 負責拆解與整合，專職 subagent 各享獨立 context，產出者與驗收者嚴格分離。
2. **Verification-Before-Completion & Git Worktree 隔離**（`obra/superpowers`、`using-git-worktrees`）：任何改動都在獨立 worktree 實作並 commit，必須先經實測證據與範圍驗證（Scope Gate），才能進入合併流程。
3. **跨平台 80/20 單一事實來源（SSOT）**：以 `AGENTS.md` + `.agent-team/` 作為 80% 通用核心，各 AI 平台（預設 Claude Code、次選 Gemini CLI）只保留 20% 特規 Adapter，並由 `scripts/sync_adapters.py` 與 `TEAM-007` 機械保證零漂移。
4. **RFC-001 確定性優先（Determinism First）**：所有反覆出現的錯誤不能只補 prompt，必須升級為靜態檢查、Hook 攔截或單元測試（§1.1），並提供自癒型三段錯誤訊息（§1.2）。

---

## 三層防線（v2 補齊機械防護）

```
層級 1：Prompt 層     AGENTS.md + .agent-team/prompts/ + CLAUDE.md / GEMINI.md   告訴 agent 該怎麼做
層級 2：權限與 Hook層 settings.json + subagent tools + scripts/guard_hook.py      機械阻擋越權與 baseline 篡改
層級 3：確定性檢查層  check_team.py + check_governance.py + verify_scope.py + CI 做錯一定被擋下
```

越下層越可靠。v2 特別修補了 v1 在層級 2 與層級 3 的多個實戰破口：
- **堵住 `Bash` 繞過洞**：移除 `.claude/settings.json` 的 `check_governance.py:*` 寬鬆白名單，並在 Claude（`PreToolUse`）與 Gemini（`BeforeTool`）同步掛載 `scripts/guard_hook.py`，硬性攔截 `--write-baseline`、`baseline.json` 寫入、強制推送與 `git reset --hard`。
- **補齊 Worktree → Verifier → Merge → Integration 交接**：明確定義 builder commit 格式、verifier 進入目標 worktree 驗收、以及平行合併 ≥ 2 個任務後的整合驗證（見 `.agent-team/protocols/handoff-and-worktree.md`）。
- **打通 `REPEAT:` 閉環**：在 `STATE.md` 新增 `## Failure log (1st occurrence)`，解決無狀態 verifier 永遠記不得上一次失敗的矛盾；且 `TEAM-005` 改採精確規則 ID／測試函式名稱比對，並納入 `tests/` 掃描。
- **補齊 `Files` 範圍檢查與依賴檢查**：新增 `scripts/verify_scope.py`（`SCOPE-001/002`）實際比對 `git diff` 與 `PLAN.md` 白名單；`TEAM-004` 驗證 `Owner`、`Depends on` 就緒狀態、以及 `doing + verify` 跨狀態路徑正規化重疊（含目錄前綴）。
- **升級靜態掃描與計數型 Ratchet**：`check_governance.py` 改為具註解／字串感知的全文掃描，能正確抓出多行 import、不誤報註解字串、不因無效過期日 crash、以違規次數鎖死棘輪、將 `setTimeout` 限定於 `ui/domain` 禁用（保留 `core` 封裝能力）、支援中英文補丁註解偵測，並移除缺乏配套工具的空泛條款（如強制錄影與 TLA+ 檔案檢查），確保 RFC-001 每一條文皆有 100% 實際自動化檢查。

---

## 80/20 切分與雙 AI 適配

詳見 `.agent-team/protocols/adapters.md`：
- **80% 通用**：`AGENTS.md`、`.agent-team/{config.json,prompts/,protocols/}`、`BRIEF.md`、`PLAN.md`、`STATE.md`、`.governance/config.json`、`scripts/*.py`、`.github/workflows/team-check.yml`。
- **20% Claude（預設）**：`CLAUDE.md`、`.claude/settings.json`（`PreToolUse` exit code 2）、`.claude/agents/*.md`（原生 `isolation: worktree`）。
- **20% Gemini**：`GEMINI.md`、`.gemini/settings.json`（`BeforeTool` JSON `decision: deny`）、`.gemini/agents/*.md`（`kind: local`、`temperature`、`max_turns`，搭配 `scripts/worktree_ops.py` 實作等價 worktree 隔離）。

---

## 模型分層策略（避免成本倒掛與弱審強）

| 角色 | Claude（預設） | Gemini | 設計理由 |
|---|---|---|---|
| Orchestrator | `claude-fable-5-2` | `gemini-3-pro-preview` | 規劃、拆解與風險判斷決定整體上限 |
| Builder | `sonnet` (`effort: high`)；複雜核心任務可升 `opus` | `gemini-3-pro-preview` (`temp: 0.2`) | 範圍已被 `PLAN.md` 與 `Files` 限縮，日常主力兼顧品質與成本 |
| Verifier | `sonnet` (`effort: high`) | `gemini-3-pro-preview` (`temp: 0.1`) | 能力不低於 Builder，避免「弱模型審強模型」漏抓深層邏輯錯誤 |
| Scout | `haiku` (`effort: low`) | `gemini-3-flash-preview` (`temp: 0.1`) | 大量唯讀檢索，高速且低成本 |

---

## 程式碼分層（RFC-001 §2.2）

```
src/ui      → 可 import domain、core（禁止直接使用 useEffect / useLayoutEffect / setTimeout）
src/domain  → 可 import core（禁止直接使用 useEffect / useLayoutEffect / setTimeout）
src/core    → 不可 import 上層；所有副作用與計時器都封裝在此層，對外提供宣告式 API（§2.1）
```

---

## 計數型 Ratchet（RFC-001 §3.1）

導入既有專案時（限人類設定 `ALLOW_BASELINE_WRITE=1` 後執行）：

```powershell
$env:ALLOW_BASELINE_WRITE = "1"
python scripts/check_governance.py --write-baseline
```

產生 `.governance/baseline.json`（以 `{"counts": {"RULE::path": N}}` 記錄每個規則在各檔案的既有違規數）：
- 未異動的既有檔案最多放行 `N` 筆；**即使沒有 `--changed-from`，再多加第 `N+1` 筆也會立刻阻擋**。
- 檔案一旦在 PR 或 push diff 中被修改，該檔所有違規都必須 100% 清零。
- 當實際違規數低於 baseline 計數時觸發 `GOV-411`，強制收緊 baseline；baseline 任何新增或計數上升皆由 `GOV-412` 攔截。

---

## 已知邊界與擴充建議

- import 掃描目前支援 JS/TS（相對路徑、`@/` alias、多行 `import`/`export`/`require`/動態 `import()`）。當專案規模超過數百檔時，建議引入 `dependency-cruiser` 並將其設定檔保留於專案根目錄（`TEAM-005` 已自動納入規則 ID 掃描）。
- 若目標專案改為 Python / Go 等非 JS/TS 技術棧，請依專案語言調整 `.governance/config.json` 或於 CI 接上該語言的 linter（如 `ruff`、`mypy`、`import-linter`）。
- 若未來要重新加入 Codex 或 Cursor 等第三個 AI 平台，只需依 `.agent-team/protocols/adapters.md` 新增 `.agent-team/adapters/<name>.json` 並註冊至 `.agent-team/config.json`。
