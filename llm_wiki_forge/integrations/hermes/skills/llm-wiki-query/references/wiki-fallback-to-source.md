# Wiki Fallback to Source Code — 具體操作模式

## 情境
當 `llm-wiki-query` graph runtime 回傳的 direct_evidence 對業務邏輯問題證據不足時（例如：只找到 dispatch/batch 相關模組，但找不到報價/車資計算邏輯）。

## 判斷 Wiki 證據不足的訊號
1. `synthesis_inputs.direct_evidence` 中的 symbol 與問題無關（例如問「搜車邏輯」但只找到 `BatchInfoLookup`）
2. `selected_modules` 全部是 dispatch 相關，沒有 WebAPI 或 fare 相關模組
3. 所有 evidence 的 intent_score 都很低
4. `challenge_findings` 有 `broad-routing` 警告（超過 3 個模組被選中）

## 具體操作步驟

### Step 1：確認 Wiki 證據不足
檢查 evidence pack 的 `synthesis_inputs.direct_evidence`，確認沒有直接相關的程式碼片段。

### Step 2：用關鍵字 grep 搜尋原始碼
對以下四個專案根目錄做 grep：

```bash
roots=(
  "/home/tedhsu/codebases/dispatch/RD.TGDS/DEV/TGDS-TaxiPlus/01_Code/TGDS.WebAPI"
  "/home/tedhsu/codebases/dispatch/TGDS-Dispatch-WebAPI"
  "/home/tedhsu/codebases/dispatch/DispatchRule"
  "/home/tedhsu/codebases/dispatch/RD.TGDS/DEV/TGDS/CoreServers"
)

# 用業務關鍵字搜尋
for kw in "Quotation" "Quotation_Make" "TaxiPlusQuotation" "GetQuotation"; do
  grep -RIn --include="*.cs" --include="*.cshtml" "$kw" "${roots[@]}"
done
```

### Step 3：從 grep 結果找出關鍵檔案
通常會找到：
- `Controllers/APP/Quotation/Quotation_Make.cs` — 入口 controller
- `Models/App/Quotation.cs` — 報價物件與 `DoEstimated()`
- `Services/TaxiFareCalc.cs` — 車資計算核心

### Step 4：讀取關鍵檔案
用 `read_file` 讀取找到的檔案，提取邏輯。

### Step 5：組合答案
從原始碼證據回答問題，並在答案末尾列出檔案路徑與方法名稱。

## 常見業務邏輯對應的搜尋關鍵字

| 業務問題 | 搜尋關鍵字 |
|----------|-----------|
| 搜車/報價 | Quotation, Quotation_Make, TaxiPlusQuotation |
| 派車邏輯 | AutoDispatch, DispatchBatch, JobCondition |
| 車資計算 | TaxiFareCalc, GetDrivingExpenses, FareRate |
| 取消訂單 | CancelJob, CancelOrder |
| 司機定位 | IVE_Status, GeocodingReverse |

## 範例（2026-05-19 搜車問題）
- Wiki 只找到 dispatch/batch 相關模組，沒有報價邏輯
- grep 找到 `Quotation_Make.cs` 的 `Make()` 方法
- 讀取後發現：10 種車型平行計算 + 路線 API + 車資計算
- 完整答案來自原始碼證據
