# LLM Wiki 原始碼路徑來源鏈追溯

當使用者問「程式碼證據從哪來的」、「原始碼路徑怎麼來的」時，依照以下五層鏈追溯。

## 五層來源鏈

```
wiki.scope.json (手動定義白名單)
    ↓ 讀取
scope.inventory.json (自動產生)
    ↓ 讀取 + 轉換
Generate_Module_Wiki.ps1 (PowerShell 腳本；WSL Copilot skills 預設不能直接執行)
    ↓ 寫入
modules/<module>.json (模組 JSON)
    ↓ 查詢時讀取
graph_runtime (圖路由)
    ↓ 從 source_paths 提取
direct_evidence (證據 pack)
```

### 第一層：wiki.scope.json（根本來源）

路徑的**最原始定義處**，手動配置的白名單。

路徑：`Wiki/wiki.scope.json`

關鍵結構：
```json
{
  "repos": [
    {
      "logicalName": "TGDS-TaxiPlus",
      "actualRoot": "D:\\CompanyProject\\RD.TGDS\\DEV\\TGDS-TaxiPlus",
      "targets": [
        {
          "logicalName": "TGDS.WebAPI",
          "actualPath": "D:\\CompanyProject\\RD.TGDS\\DEV\\TGDS-TaxiPlus\\01_Code\\TGDS.WebAPI"
        }
      ]
    }
  ]
}
```

`actualPath` 就是原始碼路徑的根本來源。

### 第二層：scope.inventory.json（自動產生）

路徑：`Wiki/_data/scope.inventory.json`

由 `Generate_Module_Wiki.ps1` 讀取 `wiki.scope.json` 後自動產生。

### 第三層：Generate_Module_Wiki.ps1

路徑：`scripts/Generate_Module_Wiki.ps1`

關鍵行：
- 第 20 行：讀取 inventory 檔案
- 第 1855 行：從 inventory target 取出 `actualPath` 賦值給 `SourcePath`
- 第 2034 行：寫入模組 JSON 的 `source_paths` 欄位

### 第四層：模組 JSON

路徑：`Wiki/_data/modules/<module>.json`

包含 `source_paths` 欄位，由腳本寫入。

查詢時圖路由讀取此檔案，從 `source_paths` 取得原始碼路徑進行程式碼提取。

### 第五層：圖路由查詢

執行 `graph_runtime` 時：
1. 路由匹配到模組
2. 從模組 JSON 讀取 `source_paths`
3. 從該路徑下提取程式碼（tree-sitter AST）
4. 將提取結果寫入證據 pack 的 `synthesis_inputs.direct_evidence`

## 快速檢查命令

```bash
# 1. 檢查根本來源
cat Wiki/wiki.scope.json | grep -A 5 actualPath

# 2. 檢查 inventory
cat Wiki/_data/scope.inventory.json | grep -A 5 ActualPath

# 3. 檢查模組 JSON
cat Wiki/_data/modules/<module>.json | grep source_paths

# 4. 檢查證據 pack
python -c "import json; d=json.load(open('Wiki/_data/query_runs/<pack>.json')); print([e['file_path'] for e in d['synthesis_inputs']['direct_evidence']])"
```

## 修改路徑

如果原始碼路徑不對，修改 `wiki.scope.json` 中的 `actualPath`，然後重新執行：

Windows/Codex 管理環境才可執行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/Generate_Module_Wiki.ps1
powershell -ExecutionPolicy Bypass -File scripts/Sync_Master_Full_Wiki.ps1 -AcceptBaseline
```

WSL Copilot 環境只能驗證來源、讀取 metadata、跑 Python query/eval；遇到這兩個 PowerShell 步驟時要回報需要 Windows/Codex 執行，不要在 Linux shell 裡硬跑。
