# Events_* 欄位模式

## 核心規則

Events_* 欄位（如 Events_hd051、Events_hd049 等）是**訂單參數記錄/審計軌跡**，不是電文回傳的資料來源。

## 常見誤區

**誤區**：查詢專派任務小費時，以為 Events_hd051 是電文回傳的來源。

**事實**：
- Events_hd051 只是把小費值「記錄」在訂單參數表裡
- 電文回傳的小費實際來自 `JOB_ExecVEH.FeeCharge`
- 寫入 Events_hd051 和回傳電文讀取的是同一筆資料，但來源不同

## 程式路徑

| 用途 | 來源 | 檔案 |
|------|------|------|
| 寫入 Events_hd051 | `tipInfo.OrderTip` 或 `options.JobOrder.NormalFee` | `TGDS.WebAPI/Controllers/APP/Dispatch/Order.cs` |
| 電文回傳小費 | `JOB_ExecVEH.FeeCharge` | `TGDS.WebAPI/Services/Job/JobServices.cs` |
| TDC 查詢小費 | `JOB_ExecVEH.FeeCharge` | `CoreServers/TDC/SvcWorker/SvcWorker.cs` |

## 其他 Events_* 欄位

- Events_hd049：訂車時前端傳入的計價倍率
- Events_hd053：多元計程車適用的 ETA 上限放寬分鐘
- Events_hd037：鑽石熊會員車資倍率
- Events_1010b：多元計程車相關參數

## 查詢建議

當查詢「某個 Events_* 欄位是不是某個功能的來源」時：
1. 先確認該欄位的寫入位置（通常是 Order.cs 的 InsertIntoOrderParams）
2. 再確認電文/回傳的讀取位置（通常是 JobServices.cs 或 SvcWorker.cs）
3. 兩者可能指向同一筆資料，但來源不同
