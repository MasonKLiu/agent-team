# 架構說明

## 設計來源

1. **@0xClodex 的文章〈Fable 5.2 Agent Teams〉**：一個強 orchestrator + 三種便宜 worker（scout / builder / verifier），用 `PLAN.md`、`STATE.md` 保存狀態，maker 不驗收自己，重複的錯變成規則。
2. **目前主流的多 agent 設計**：
   - *Orchestrator–worker*：主 agent 拆任務、平行派發給 subagent，各自用獨立 context，只回傳結論（Anthropic multi-agent research system、Claude Code subagents）。
   - *角色專職 + 最小權限*：每個 subagent 有固定職責、固定工具、固定模型。
   - *Generator–critic*：產出與驗收分離，驗收者預設「這是錯的」。
   - *檔案化記憶*：`AGENTS.md` / `CLAUDE.md` 放穩定規範，`STATE.md` 放會變的進度，跨 session 不靠對話記憶。
3. **RFC-001**：規則不能只寫在 prompt 裡，必須變成確定性的檢查（§1.1）。

## 本 repo 對原文章做的關鍵調整

文章把「Rules learned」寫進 `STATE.md` 讓 builder 每次讀。RFC-001 §1.1 明確禁止只靠 prompt 修正 agent 的重複錯誤。所以本 repo 的規則是：

> verifier 抓到同一種錯兩次 → orchestrator 必須新增一條確定性檢查（`scripts/check_governance.py` 的規則、ESLint 規則或測試），再把 `- 描述 Check: <RULE-ID>` 寫進 `STATE.md`。

`check_team.py` 的 TEAM-005 會擋下沒有 `Check:` 或指向不存在檢查的規則。prompt 只是提示，CI 才是保證。

## 三層防線

```
prompt 層     CLAUDE.md / AGENTS.md / agents/*.md     告訴 agent 該怎麼做
權限層       .claude/settings.json + subagent tools    讓 agent 做不到不該做的事
確定性檢查層  scripts/*.py + GitHub Actions            做錯了一定會被擋下
```

越下層越可靠。新規則優先往下層放。

## 模型分配

| 角色 | 模型 | 原因 |
|---|---|---|
| Orchestrator | `claude-fable-5-2`（主 session，見 `.claude/settings.json`） | 規劃與判斷品質決定整個團隊上限 |
| Builder | opus | 寫程式需要強推理，但範圍已被 PLAN 限縮 |
| Verifier | sonnet | 對照驗收條件，不需要最強模型 |
| Scout | haiku | 大量讀檔，便宜快速 |

每個 subagent 都必須指定 `model`（TEAM-001），否則會繼承主 session 的模型。

## 程式碼分層（RFC-001 §2.2）

```
src/ui      → 可 import domain、core
src/domain  → 可 import core
src/core    → 不可 import 上層；所有副作用都在這層，並對外提供宣告式 API（§2.1）
```

分層規則寫在 `.governance/config.json`，換成 `main/`、`renderer/` 等結構時改這份設定即可。

## Ratchet（RFC-001 §4.1）

導入既有專案時：

```powershell
python scripts/check_governance.py --write-baseline
```

會把現有違規記錄到 `.governance/baseline.json`。之後：

- baseline 內的違規暫時放行；
- 檔案一旦在 PR 中被修改，該檔所有違規都必須清掉；
- baseline 只能變少（GOV-412），已清掉的條目必須移除（GOV-411），等於把規則鎖死。

agent 無法直接編輯 baseline（`.claude/settings.json` 的 deny 規則）。

## 已知限制

- import 解析用正規表達式，支援相對路徑與 `@/` alias。專案變大後建議改用 dependency-cruiser，並把它的設定檔納入 `known_check_ids` 掃描範圍（已支援 `.dependency-cruiser.js`）。
- 說明型註解偵測依關鍵字，會有漏網之魚；可在 `.governance/config.json` 擴充。
- §3.2 TLA+ 只檢查「有沒有對應的 spec 或 property test」，不會執行 TLC。需要時在 CI 加 TLC 步驟。
