# LLM Wiki Forge

[English](README.md) | [繁體中文](README.zh-TW.md)

LLM Wiki Forge 是本機 LLM Wiki 的版本化正確性引擎。

它負責所有會影響證據正確性的流程：

- 更新已註冊的來源 repo
- 刷新產生出的 Wiki artifacts
- 透過 packaged runtime 查詢程式碼行為
- 執行可重現的精確 source search
- 驗證 evidence pack 的 freshness 與 reuse
- 保存 Hermes tool / skill / guard / tests 的 integration 正本

Hermes 仍然可以是對話與回答整理層。Forge 是查詢與維護行為的 source of truth。

Repository: <https://github.com/TedHsuAI/llm-wiki-forge>

## 目前支援範圍

LLM Wiki Forge 目前僅支援兩類程式碼：

- `.NET / C#`
- `Android / Kotlin / Java`

兩類 parser 都會預設安裝。`.NET / C#` 是目前驗證最多的路徑；Android 已可使用，但仍應依目標 repo 做實際驗證。

## 專案分類

```text
llm_wiki_forge/
  cli.py                         # CLI 指令
  workflows.py                   # update, refresh, code query orchestration
  query_adapter.py               # Hermes-compatible query/source-search payload
  repo_sync.py                   # repo sync state
  runtime.py                     # packaged runtime 執行層
  integrations/
    hermes/                      # Forge-owned Hermes integration pack
  resources/
    bootstrap_llm_wiki.py        # bootstrap generator
    scripts/query_runtime/       # packaged query runtime modules
skills/                          # agent-facing LLM Wiki skills
tests/                           # Forge 與 integration tests
```

`llm_wiki_forge/integrations/hermes` 是刻意放在可見位置。它不是低階內部資源，而是 Hermes 與 Forge 之間的正式整合契約：Hermes 從這裡安裝 runtime copy，Forge 保存版本化正本。

## 責任邊界

```text
Forge
  repo update -> wiki refresh -> code query -> source search -> evidence validation

Hermes
  receive user questions -> call stable tools -> organize evidence -> write human answers

Hermes integration pack
  Forge-owned copies of Hermes tools, skills, guard rules, and tests
```

簡單說：Forge 管正確性，Hermes 管表達、語義整理與對話回覆。

## 主要功能

### Repo 與 Wiki 維護

- `update`：更新或檢查已註冊來源 repo，刷新 Wiki artifacts，執行 gates，更新 sync state。
- `refresh`：不更新 git，只重建既有 repo 的 Wiki artifacts。
- `repo add`：把來源 repo 註冊進 `wiki.scope.json` 與 repo sync metadata。
- `build` / `bootstrap` / `validate`：建立並驗證新的 Wiki。

### 程式碼證據查詢

- `code query`：執行 packaged query orchestrator，回傳 Hermes-compatible payload。
- `code source-search`：執行固定字串 source search，回傳 compact 或 full evidence。
- 支援近期 evidence pack reuse、similarity check、freshness validation。
- 支援 Slack 尺寸的 compact result，也支援 local debug 用的 full result。

### Hermes Integration

Forge 內含 Hermes integration 正本：

```text
llm_wiki_forge/integrations/hermes/
  tools/llm_wiki_query.py
  tools/llm_wiki_forge.py
  skills/llm-wiki-query/SKILL.md
  hooks/slack_readonly_guard.py
  tests/test_llm_wiki_query_tool.py
  manifest.json
```

Hermes runtime 仍需要在本機保留 copies，因為 Hermes registry 與 skill loader 會讀本機檔案。但這些檔案的正本由 Forge 版本控管。

## 安裝

從 GitHub 安裝：

```bash
python -m pip install git+https://github.com/TedHsuAI/llm-wiki-forge.git
```

本機開發：

```bash
git clone https://github.com/TedHsuAI/llm-wiki-forge.git
cd llm-wiki-forge
python -m pip install -e .
```

CLI entrypoint：

```bash
llm-wiki --version
```

也可以用 Python module 執行：

```bash
python -m llm_wiki_forge --version
```

## 需求

- Python 3.11+
- Git
- 可讀取來源 repo
- 建議安裝 `rg`
- `.NET / C#`：`.slnf`、`.sln`、`.csproj` 可提升 extraction scope 準確度
- Android：Kotlin/Java parser dependencies 會隨預設安裝
- Graphify package：`graphifyy>=0.4.10,<0.9`

當 `.NET` repo 有被卸載或刻意排除的 Visual Studio projects，請優先使用共享的 `.slnf` solution filter。Forge 會把 `.slnf` projects 視為 active project set，並略過 project roots 外的 C# files。沒有 `.slnf` 時，Forge 會使用 `.sln` project entries。

## CLI 快速開始

### 更新已註冊 Repo

來源 git 有變動，且 Wiki 需要刷新時使用：

```bash
llm-wiki update \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key <RepoKey>
```

只想看計畫時先 dry-run：

```bash
llm-wiki update \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key <RepoKey> \
  --dry-run
```

### 刷新 Wiki Artifacts

git 狀態已正確，只需要重建 artifacts 時使用：

```bash
llm-wiki refresh --wiki-root <wiki_root> --repo <RepoName> --json
```

### 查詢程式碼行為

用於業務邏輯、API 行為、派遣、車資、付款、scheduler 等 codebase 問題：

```bash
llm-wiki code query \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --question "搜車中加小費的相關邏輯?" \
  --top 5 \
  --extract-limit 4 \
  --json
```

JSON payload 會包含：

- `decision`
- `next_action`
- `routing.selected_modules`
- `direct_evidence`
- `direct_evidence_count`
- `evidence_pack`
- `reuse_decision`
- `freshness_status`
- `source_search`

當 `next_action` 是 `run_source_search`，再用 deterministic source search：

```bash
llm-wiki code source-search \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --pattern SearchTipEligibilityService \
  --limit 20 \
  --json
```

### 新增 Repo 到 Multi-Repo Wiki

```bash
llm-wiki repo add \
  --repo /home/tedhsu/DispatchRawdata/<RepoName> \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key <RepoKey> \
  --wiki-path <WikiPath>
```

### 建立新 Wiki

```bash
llm-wiki build --repo <repo_path> --wiki-root <wiki_root>
```

如果省略 `--wiki-root`，Forge 預設使用：

```text
<repo_parent>/<repo_name>-llm-wiki
```

## Hermes Integration

安裝 Forge-owned Hermes integration pack：

```bash
python -m llm_wiki_forge integrations install-hermes \
  --hermes-root /home/tedhsu/.hermes \
  --dry-run

python -m llm_wiki_forge integrations install-hermes \
  --hermes-root /home/tedhsu/.hermes
```

只安裝 tool、skill、test，不安裝 hook 時：

```bash
python -m llm_wiki_forge integrations install-hermes \
  --hermes-root /home/tedhsu/.hermes \
  --no-hook
```

安裝後，Hermes 應該提供穩定 tool names：

```text
llm_wiki_query
llm_wiki_source_search
llm_wiki_forge_sync
llm_wiki_forge_repo_add
```

查詢 tools 會刻意保持很薄：Hermes 保留 registry contract，真正查詢行為委派給 Forge。

## 查詢流程

預期 evidence workflow：

```text
llm_wiki_query
  -> routing and direct evidence
  -> llm_wiki_source_search when next_action says run_source_search
  -> read source files named by evidence
  -> answer from traceable code lines
```

不要用記憶回答 code behavior。有效答案應該根據 evidence pack、direct source snippets，或 query 後讀取的 raw source files。

## 內建 Skills

| Skill | 用途 |
| --- | --- |
| `llm-wiki-build` | 完整 build flow 的主要 AI entrypoint |
| `llm-wiki-bootstrap` | 建立新的 LLM Wiki root |
| `llm-wiki-module-onboarding` | 將單一 repo 建成 Wiki module |
| `llm-wiki-integrity-validate` | 唯讀健康檢查 |
| `llm-wiki-repo-infra-backfill` | 改善既有 repo 的 Wiki artifacts |
| `llm-wiki-master-sync` | 從 repo git changes 更新 Wiki state |
| `llm-wiki-pipeline-hardening` | 將 repo 修正推廣成共用 pipeline 規則 |

在 packaged integration 以外使用時，可從 `skills/` 複製到目標 agent 的 skills directory。

## 預期 Wiki Artifacts

成功 build 或 refresh 後，wiki root 應包含：

```text
wiki.scope.json
Wiki/_data/modules/<repo>.json
Wiki/01_Modules/<RepoName>/<RepoName>.md
Wiki/_data/symbols/*.json
Wiki/_data/communities/*.json
Wiki/_data/query_runs/*.json
Wiki/_meta/repo_sync/<RepoName>.json
```

舊 Wiki root 可能仍保留 `scripts/`。Forge 現在不再依賴 wiki-root scripts 來辨識既有 wiki root；新的 query adapter 應優先使用 packaged runtime。

## 驗證

本機開發驗證：

```bash
python -m compileall llm_wiki_forge
python -m pytest tests -q
python -m llm_wiki_forge integrations install-hermes --hermes-root /home/tedhsu/.hermes --dry-run
```

查詢 smoke tests：

```bash
python -m llm_wiki_forge code query \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --question "固定車資怎麼算" \
  --top 3 \
  --extract-limit 2 \
  --json

python -m llm_wiki_forge code source-search \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --pattern JobTraState \
  --limit 1 \
  --json
```

## 相容性

舊命令仍可用：

```text
sync
backfill
query
source-search
graph
```

新的 integration 應優先使用：

```text
update
refresh
code query
code source-search
integrations install-hermes
```

這些名稱對應目前的責任模型：Forge 處理正確性 workflow；Hermes 處理對話與答案整理。
