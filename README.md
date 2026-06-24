# LLM Wiki Forge

LLM Wiki Forge turns a source repo into an LLM-friendly local wiki.

It ships with:

- **AI skills** for agent-driven build flows.
- A thin **`llm-wiki` CLI** for repeatable local or CI usage.

> Current language support: **C# / .NET repositories**.

Repository: <https://github.com/TedHsuAI/llm-wiki-forge>

Languages: [English](#llm-wiki-forge) | [繁體中文](#繁體中文)

## What It Does

For one repo at a time, LLM Wiki Forge can:

- create a new LLM Wiki root when none exists
- generate first-pass module, symbol, community, and query-run artifacts
- run a focused smoke validation
- keep per-repo sync state for later updates
- guide AI agents through a consistent bootstrap -> onboarding -> validation flow

## Install

From GitHub:

```bash
pipx install git+https://github.com/TedHsuAI/llm-wiki-forge.git
```

Or with pip:

```bash
python -m pip install git+https://github.com/TedHsuAI/llm-wiki-forge.git
```

For local development:

```bash
git clone https://github.com/TedHsuAI/llm-wiki-forge.git
cd llm-wiki-forge
python -m pip install -e .
```

## Requirements

- Python 3.11+
- Git
- read access to the target repo
- recommended: `ripgrep` (`rg`)
- for C# repos: `.sln` / `.slnf` / `.csproj` files are preferred when available
- Graphify package: `graphifyy>=0.4.10,<0.9`

When a repo contains unloaded or intentionally excluded Visual Studio projects, prefer a shared `.slnf` solution filter. The bootstrap scanner treats `.slnf` projects as the active project set and skips C# files outside those project roots. If no `.slnf` is present, it uses `.sln` project entries as the active solution scope and skips `.csproj` folders that are not part of the solution.

Installing `llm-wiki-forge` installs the core Python runtime dependencies, including `graphifyy`, LangGraph, Tree-sitter, and the C# parser. Bootstrap also writes those same core dependencies into the generated wiki `requirements.txt`; run CLI commands with `--install-requirements` when the wiki virtual environment must be created or refreshed. Missing or failing Graphify is treated as a generation error, not a downgraded result.

The production Obsidian wiki also tracks external tools in `Wiki/_data/tooling.status.json`: `graphify`, `repomix`, `dotnet`, `node`, and `npm`. Forge writes the same style of tool/runtime status during `update_wiki`; install `repomix`, `.NET SDK`, and Node.js/npm separately when those stages are required. GraphRAG is available as an optional extra with `llm-wiki-forge[graphrag]`.

## CLI Usage

Build a wiki from a repo:

```bash
llm-wiki build --repo <repo_path> --wiki-root <wiki_root>
```

If `--wiki-root` is omitted, it defaults to:

```text
<repo_parent>/<repo_name>-llm-wiki
```

Create only the base wiki scaffold:

```bash
llm-wiki bootstrap --repo <repo_path> --wiki-root <wiki_root>
```

Validate an existing wiki:

```bash
llm-wiki validate --wiki-root <wiki_root> --repo <repo_name>
```

Refresh artifacts for one existing repo:

```bash
llm-wiki backfill --wiki-root <wiki_root> --repo <repo_name>
```

Forge-owned correctness workflows:

```bash
# Update a registered source repo, refresh wiki artifacts, and write sync reports.
llm-wiki update \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key <RepoKey>

# Refresh generated wiki artifacts without updating git.
llm-wiki refresh --wiki-root <wiki_root> --repo <repo_name>

# Query code behavior through the packaged orchestrator.
llm-wiki code query --wiki-root <wiki_root> --question "<question>" --json

# Verify exact code evidence with deterministic source search.
llm-wiki code source-search --wiki-root <wiki_root> --pattern "<identifier>" --limit 20 --json
```

When `--json` is supplied, `code query` and `code source-search` return the same
Hermes-compatible compact/full payload shape used by the current
`llm_wiki_query` and `llm_wiki_source_search` tools, including recent evidence
reuse, freshness validation, shard summaries, compact snippets, next actions,
and source-search limit policy.

`sync`, `backfill`, `query`, and `source-search` remain compatible entrypoints,
but new adapters should prefer `update`, `refresh`, and `code ...` because those
names match the Forge-owned responsibility boundary: repo update, wiki refresh,
and code evidence query.

Create or update repo sync state:

```bash
llm-wiki sync --repo <repo_path> --wiki-root <wiki_root> --accept-baseline
```

Add a repo to an existing multi-repo wiki registry:

```bash
llm-wiki repo add \
  --repo /home/tedhsu/DispatchRawdata/<RepoName> \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key <RepoKey> \
  --wiki-path <WikiPath>
```

Run scheduled-style sync through the registry:

```bash
llm-wiki sync \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key <RepoKey> \
  --accept-baseline
```

For this Forge-centered flow, build/sync/onboarding execution lives in `llm-wiki-forge`.
An existing wiki root may keep `scripts/query_runtime` during the transitional query-runtime phase,
but `scripts/` is no longer required just to recognize an existing wiki root.

The CLI auto-detects Python and creates `<wiki_root>/.venv` when needed.

## AI Skill Usage

Copy the folders under `skills/` into your AI tool's skills directory.

Example:

```text
skills/llm-wiki-build
skills/llm-wiki-bootstrap
skills/llm-wiki-module-onboarding
...
```

Start with:

```text
請用 llm-wiki-build 幫我為 <RepoName> 建立 LLM Wiki。
repo path 是 <repo_path>。
wiki root 是 <wiki_root>。
```

Use `llm-wiki-build` as the default entrypoint. It will:

```text
check paths
detect/create Python venv
bootstrap if needed
onboard one module
run focused validation
report PASS / PARTIAL / FAIL
```

## Included Skills

| Skill | Purpose |
| --- | --- |
| `llm-wiki-build` | Main AI entrypoint for the full build flow |
| `llm-wiki-bootstrap` | Create a new LLM Wiki root |
| `llm-wiki-module-onboarding` | Build one C# repo into a wiki module |
| `llm-wiki-integrity-validate` | Read-only health check |
| `llm-wiki-repo-infra-backfill` | Improve one existing repo's wiki artifacts |
| `llm-wiki-master-sync` | Update wiki state from repo git changes |
| `llm-wiki-pipeline-hardening` | Promote repo fixes into reusable pipeline rules |

## Expected Output

After a successful build, the wiki root should contain:

```text
wiki.scope.json
Wiki/_data/modules/<repo>.json
Wiki/01_Modules/<RepoName>/<RepoName>.md
Wiki/_data/symbols/*.json
Wiki/_data/communities/*.json
Wiki/_data/query_runs/*.json
Wiki/_meta/repo_sync/<RepoName>.json
scripts/
```

## Recommended C# Hints

Providing entry-point hints improves wiki quality:

```text
Controllers/*.cs
Services/*.cs
Repositories/*.cs
Jobs/*.cs
Handlers/*.cs
Filters/*.cs
Program.cs
Startup.cs
HostedService / BackgroundService
```

Example:

```text
Controllers/OrderController.cs :: OrderController.Create
Services/FareService.cs :: FareService.Calculate
Repositories/OrderRepository.cs :: OrderRepository.UpdateStatus
```

## Project Layout

```text
llm-wiki-forge/
├─ llm_wiki_forge/              # thin CLI package
├─ skills/                      # AI skills
│  ├─ llm-wiki-build/
│  ├─ llm-wiki-bootstrap/
│  ├─ llm-wiki-module-onboarding/
│  ├─ llm-wiki-integrity-validate/
│  ├─ llm-wiki-repo-infra-backfill/
│  ├─ llm-wiki-master-sync/
│  └─ llm-wiki-pipeline-hardening/
├─ pyproject.toml
└─ README.md
```

## Status

This project is early and currently focused on C# / .NET codebases. Other stacks, such as app teams or frontend repos, should add language-specific onboarding skills instead of weakening the C# flow.

---

# 繁體中文

LLM Wiki Forge 可以把一個原始碼 repo 建成適合 LLM / AI Agent 使用的本機 Wiki。

它包含兩種使用方式：

- **AI skills**：給 AI agent 使用，讓它照固定流程建置。
- **`llm-wiki` CLI**：給工程師或 CI 使用，讓流程可以重複執行。

> 目前支援語言：**C# / .NET repositories**。

Repository: <https://github.com/TedHsuAI/llm-wiki-forge>

## 功能

LLM Wiki Forge 會一次處理一個 repo，支援：

- 沒有 Wiki 時，建立新的 LLM Wiki root
- 產生第一版 module、symbol、community、query-run artifacts
- 執行 focused smoke validation
- 建立 per-repo sync state，方便後續更新
- 讓 AI agent 依照一致流程執行 bootstrap -> onboarding -> validation

## 安裝

從 GitHub 安裝：

```bash
pipx install git+https://github.com/TedHsuAI/llm-wiki-forge.git
```

或使用 pip：

```bash
python -m pip install git+https://github.com/TedHsuAI/llm-wiki-forge.git
```

本機開發：

```bash
git clone https://github.com/TedHsuAI/llm-wiki-forge.git
cd llm-wiki-forge
python -m pip install -e .
```

## 環境需求

- Python 3.11+
- Git
- 可讀取目標 repo
- 建議安裝 `ripgrep` (`rg`)
- C# repo 建議具備 `.sln` / `.slnf` / `.csproj`
- Graphify 套件：`graphifyy>=0.4.10,<0.9`

如果 repo 裡有已卸載或刻意排除的 Visual Studio project，建議提供可分享的 `.slnf` solution filter。Bootstrap scanner 會把 `.slnf` 內列出的 projects 視為 active project set，並跳過不在這些 project roots 底下的 C# 檔案。若沒有 `.slnf`，則使用 `.sln` 內的 project entries 作為解決方案範圍，跳過不屬於 solution 的 `.csproj` 目錄。

安裝 `llm-wiki-forge` 會一起安裝核心 Python runtime 依賴，包含 `graphifyy`、LangGraph、Tree-sitter 與 C# parser。Bootstrap 也會把同一組核心依賴寫入產生的 wiki `requirements.txt`；如果需要建立或更新 wiki virtual environment，請在 CLI 命令加上 `--install-requirements`。Graphify 缺失或執行失敗會視為生成錯誤，不再產生降級結果。

正式 Obsidian wiki 也會在 `Wiki/_data/tooling.status.json` 追蹤外部工具：`graphify`、`repomix`、`dotnet`、`node`、`npm`。Forge 目前也會在 `update_wiki` 寫出同類型的工具與 runtime 狀態；`repomix`、`.NET SDK`、Node.js/npm 需要依使用場景另行安裝。GraphRAG 已提供選用 extra：`llm-wiki-forge[graphrag]`。

## CLI 用法

從 repo 建立 Wiki：

```bash
llm-wiki build --repo <repo_path> --wiki-root <wiki_root>
```

如果省略 `--wiki-root`，預設會使用：

```text
<repo_parent>/<repo_name>-llm-wiki
```

只建立基礎 Wiki scaffold：

```bash
llm-wiki bootstrap --repo <repo_path> --wiki-root <wiki_root>
```

驗證既有 Wiki：

```bash
llm-wiki validate --wiki-root <wiki_root> --repo <repo_name>
```

補強既有 repo 的 artifacts：

```bash
llm-wiki backfill --wiki-root <wiki_root> --repo <repo_name>
```

Forge-owned 正確性流程：

```bash
# 更新已註冊的 source repo、刷新 Wiki artifacts，並寫入 sync reports。
llm-wiki update \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key <RepoKey>

# 不更新 git，只刷新既有 Wiki artifacts。
llm-wiki refresh --wiki-root <wiki_root> --repo <repo_name>

# 透過 packaged orchestrator 查詢程式碼行為。
llm-wiki code query --wiki-root <wiki_root> --question "<question>" --json

# 用 deterministic source search 驗證精確程式碼證據。
llm-wiki code source-search --wiki-root <wiki_root> --pattern "<identifier>" --limit 20 --json
```

帶 `--json` 時，`code query` 與 `code source-search` 會輸出目前 Hermes
`llm_wiki_query` / `llm_wiki_source_search` tool 使用的 compact/full payload
格式，包含近期 evidence reuse、freshness validation、shard summary、
compact snippets、next action、以及 source-search limit policy。

`sync`、`backfill`、`query`、`source-search` 仍保留相容，但新的 adapter
應優先使用 `update`、`refresh`、`code ...`。這三個名稱對應 Forge 擁有的
責任邊界：repo update、wiki refresh、code evidence query。

建立或更新 repo sync state：

```bash
llm-wiki sync --repo <repo_path> --wiki-root <wiki_root> --accept-baseline
```

將 repo 加入既有 multi-repo wiki registry：

```bash
llm-wiki repo add \
  --repo /home/tedhsu/DispatchRawdata/<RepoName> \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key <RepoKey> \
  --wiki-path <WikiPath>
```

透過 registry 執行排程同等 sync：

```bash
llm-wiki sync \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key <RepoKey> \
  --accept-baseline
```

在這個 Forge-centered flow 裡，build/sync/onboarding 的實作由 `llm-wiki-forge` 負責。
既有 wiki root 可以在過渡期保留 `scripts/query_runtime` 作為查詢 runtime，
但 `scripts/` 不再是判斷既有 wiki root 的必要條件。

CLI 會自動偵測 Python，必要時建立 `<wiki_root>/.venv`。

## AI Skill 用法

把 `skills/` 底下的資料夾複製到你的 AI 工具 skills 目錄。

範例：

```text
skills/llm-wiki-build
skills/llm-wiki-bootstrap
skills/llm-wiki-module-onboarding
...
```

建議一律從 `llm-wiki-build` 開始：

```text
請用 llm-wiki-build 幫我為 <RepoName> 建立 LLM Wiki。
repo path 是 <repo_path>。
wiki root 是 <wiki_root>。
```

`llm-wiki-build` 會執行：

```text
檢查路徑
偵測或建立 Python venv
必要時 bootstrap
onboard 一個 module
執行 focused validation
回報 PASS / PARTIAL / FAIL
```

## Skills

| Skill | 用途 |
| --- | --- |
| `llm-wiki-build` | 主要入口，執行完整建置流程 |
| `llm-wiki-bootstrap` | 建立新的 LLM Wiki root |
| `llm-wiki-module-onboarding` | 將一個 C# repo 建成 Wiki module |
| `llm-wiki-integrity-validate` | 唯讀健康檢查 |
| `llm-wiki-repo-infra-backfill` | 補強既有 repo 的 Wiki artifacts |
| `llm-wiki-master-sync` | 依 git changes 更新 Wiki state |
| `llm-wiki-pipeline-hardening` | 將單一 repo 修補提升成共用 pipeline 規則 |

## 預期輸出

成功建置後，wiki root 至少會包含：

```text
wiki.scope.json
Wiki/_data/modules/<repo>.json
Wiki/01_Modules/<RepoName>/<RepoName>.md
Wiki/_data/symbols/*.json
Wiki/_data/communities/*.json
Wiki/_data/query_runs/*.json
Wiki/_meta/repo_sync/<RepoName>.json
scripts/
```

## 建議提供的 C# 線索

提供入口檔案可以提升 Wiki 品質：

```text
Controllers/*.cs
Services/*.cs
Repositories/*.cs
Jobs/*.cs
Handlers/*.cs
Filters/*.cs
Program.cs
Startup.cs
HostedService / BackgroundService
```

範例：

```text
Controllers/OrderController.cs :: OrderController.Create
Services/FareService.cs :: FareService.Calculate
Repositories/OrderRepository.cs :: OrderRepository.UpdateStatus
```

## 專案結構

```text
llm-wiki-forge/
├─ llm_wiki_forge/              # thin CLI package
├─ skills/                      # AI skills
│  ├─ llm-wiki-build/
│  ├─ llm-wiki-bootstrap/
│  ├─ llm-wiki-module-onboarding/
│  ├─ llm-wiki-integrity-validate/
│  ├─ llm-wiki-repo-infra-backfill/
│  ├─ llm-wiki-master-sync/
│  └─ llm-wiki-pipeline-hardening/
├─ pyproject.toml
└─ README.md
```

## 狀態

這個專案仍在早期階段，目前聚焦在 C# / .NET codebases。其他技術棧，例如 App team 或前端 repo，建議新增語言專屬 onboarding skill，不要稀釋既有 C# 流程。
