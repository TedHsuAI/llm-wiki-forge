# LLM Wiki 社群檔案路徑不匹配問題

## 問題現象

執行 `graph_runtime --extract` 時出現 extraction-error：

```
Refusing to read path outside wiki.scope.json whitelist:
/mnt/d/CompanyProject/RD.TGDS/DEV/TGDS-TaxiPlus/01_Code/TGDS.WebAPI/Services/TaxiFareCalc.cs
```

## 根因：雙路徑系統

Wiki 裡面有 **兩套路徑**，在不同環境下產生，沒有統一：

### 路徑系統 A：modules/*.json 的 source_paths（正確，WSL）

```
wiki.scope.json (手動定義，WSL 路徑)
    ↓ Generate_Module_Wiki.ps1 讀取
scope.inventory.json (自動產生)
    ↓ Generate_Module_Wiki.ps1 轉換
modules/<module>.json 的 source_paths 欄位
```

產生環境：**Windows/Codex 執行 PowerShell 腳本，或其他明確具備 PowerShell 的管理環境**。WSL Copilot skills 預設是 Linux shell，不應直接執行 `Generate_Module_Wiki.ps1`。
路徑格式：`/home/tedhsu/codebases/dispatch/RD.TGDS/DEV/TGDS-TaxiPlus/01_Code/TGDS.WebAPI`

### 路徑系統 B：communities/*.json 的 source_files（錯誤，Windows）

```
Windows 環境下執行 graphify
    ↓ 掃描程式碼，產生 graph.json
graph.json 裡面寫了 Windows 路徑 (D:\CompanyProject\...)
    ↓ 複製到 WSL
communities/<module>-community-*.json 的 source_files 欄位
```

產生環境：**Windows**（graphify 工具在 Windows 下執行）。
路徑格式：`D:\CompanyProject\RD.TGDS\DEV\TGDS-TaxiPlus\01_Code\TGDS.WebAPI\Controllers\Core\IVEController.cs`

## 為什麼抽取失敗

```
1. 圖路由匹配到模組 tgds-taxiplus-tgds-webapi
2. 找到 community hit (community-0)
3. 從 community 的 source_files 取出檔案路徑 (Windows 格式)
4. 嘗試讀取 D:\CompanyProject\... → 轉成 /mnt/d/CompanyProject\...
5. 檢查 wiki.scope.json 白名單 → /mnt/d/... 不在白名單內 → 拒絕讀取
```

**關鍵：抽取器優先使用 community 的 source_files，而不是 modules 的 source_paths。**

## 診斷步驟

```bash
# 1. 檢查 community 的 source_files 路徑格式
python3 -c "
import json, glob
for f in glob.glob('Wiki/_data/communities/*.json'):
    with open(f) as fh:
        d = json.load(fh)
    for sf in d.get('source_files', []):
        if 'D:' in str(sf):
            print(f'{f}: {sf[:100]}')
            break
"

# 2. 檢查 modules 的 source_paths 路徑格式
python3 -c "
import json
with open('Wiki/_data/modules/<module>.json') as f:
    d = json.load(f)
print(d.get('source_paths', []))
"

# 3. 檢查 wiki.scope.json 白名單
python3 -c "
import json
with open('Wiki/wiki.scope.json') as f:
    d = json.load(f)
for repo in d.get('repos', []):
    for target in repo.get('targets', []):
        print(f\"{target['logicalName']}: {target.get('actualPath', '?')}\")
"
```

## 解決方式

### 方案 A：改 community 的 source_files（換路徑）

寫腳本掃完所有 community 檔案做路徑替換：

```python
import json, glob

win_to_wsl = {
    "D:\\CompanyProject\\RD.TGDS\\DEV\\TGDS-TaxiPlus\\": "/home/tedhsu/codebases/dispatch/RD.TGDS/DEV/TGDS-TaxiPlus/",
    "D:\\CompanyProject\\RD.TGDS\\DEV\\TGDS\\": "/home/tedhsu/codebases/dispatch/RD.TGDS/DEV/TGDS/",
}

for f in glob.glob('Wiki/_data/communities/*.json'):
    with open(f) as fh:
        d = json.load(fh)
    modified = False
    for i, sf in enumerate(d.get('source_files', [])):
        for win, wsl in win_to_wsl.items():
            if sf.startswith(win):
                d['source_files'][i] = wsl + sf[len(win):]
                modified = True
                break
    if modified:
        with open(f, 'w') as fh:
            json.dump(d, fh, indent=2, ensure_ascii=False)
```

**優點**：不用改白名單，路徑系統統一。
**缺點**：下次 graphify 跑完又會被覆蓋回 Windows 路徑。

### 方案 B：加白名單（雙路徑）

在 `wiki.scope.json` 的 `repos` 裡加一個 Windows 路徑的 repo：

```json
{
  "logicalName": "TGDS-TaxiPlus-Windows",
  "actualRoot": "/mnt/d/CompanyProject/RD.TGDS/DEV/TGDS-TaxiPlus",
  "targets": [
    {
      "logicalName": "TGDS.WebAPI",
      "actualPath": "/mnt/d/CompanyProject/RD.TGDS/DEV/TGDS-TaxiPlus/01_Code/TGDS.WebAPI"
    }
  ]
}
```

**優點**：不用改 community 檔案，立刻生效。
**缺點**：白名單變長，路徑系統不統一。

### 方案 C：改 graphify 的輸出（治本）

在 graphify 產生 community 檔案時，就用 WSL 路徑。需要改 graphify 的設定或執行環境，影響範圍更大。

## 影響範圍

| 來源 | 路徑格式 | 正確與否 | 產生環境 |
|------|---------|---------|---------|
| modules/*.json source_paths | WSL `/home/tedhsu/...` | 正確 | Windows/Codex PowerShell build or managed generator run |
| communities/*.json source_files | Windows `D:\CompanyProject\...` | 錯誤 | Windows (graphify) |
| wiki.scope.json actualPath | WSL `/home/tedhsu/...` | 正確 | 手動設定 |

- **repomix 打包**：用 modules 的 source_paths，不受影響
- **查詢抽取**：用 communities 的 source_files，會失敗
- **圖路由**：用 modules 的 source_paths + communities，混合使用

## 注意事項

1. **community 檔案是靜態的** — 不會被重新產生（除非跑 Wiki 同步）
2. **下次 Wiki 同步時又會被覆蓋** — 如果同步是在 Windows 下跑的，community 檔案會重新產生 Windows 路徑
3. **modules/*.json 的 source_paths 已經是 WSL 路徑** — 這套不受影響
4. **graphify 只在 Wiki 同步時跑一次** — 每次查詢不會跑 graphify
