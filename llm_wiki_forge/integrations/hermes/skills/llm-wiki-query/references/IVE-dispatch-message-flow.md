# IVE 派遣任務電文與小費流程

## 電文架構

車機接任務的核心電文是 **x4000**（任務詢問），其他相關電文：

| 電文 | 用途 |
|------|------|
| x4000 | 任務詢問（派遣通知）— 最核心 |
| x4002 | 任務確認 |
| x4004 | 任務確認回覆 |
| x4011 | 任務狀態回報 |
| P4D01 | 任務資訊查詢 |
| x5008 | 任務資訊查詢 |

## 電文結構（x4000）

x4000 電文透過 `rep2IVE.Body.UpdateValue()` 寫入：

- **第 4 欄**：`strJobInformation` — 乘客備註（由 `JobInformation_IVE8.GetJobInformation()` 組裝）
- **第 7 欄**：`jobExInfo.ToJsonNetString()` — JSON 格式的任務延伸資料

## 小費完整流程

### 1. 下單階段（Order.cs）

檔案：`TGDS.WebAPI/Controllers/APP/Dispatch/Order.cs`

- `JobOrderObj.NormalFee` — 乘客下單時輸入的小費欄位（`CommonDTO/WebAPI/DTO/JobOrderObj.cs` line 128）
- 專派任務時若 NormalFee 為空，系統自動帶入：
  ```csharp
  if (options.JobOrder.SpecOrder.HasFlag(SpecOrdObj.專派任務車組)
      && (options.JobOrder.NormalFee == null || options.JobOrder.NormalFee == 0))
  {
      Int32.TryParse(_taxiFareCalc.GetFare4345(), out int specialFee);
      options.JobOrder.NormalFee = specialFee;
  }
  ```

### 2. 資料庫儲存

- 欄位：**`JOB_ExecVEH.SpeciallyServiceFee`**
- 注意：下單時叫 `NormalFee`，存入 DB 後叫 `SpeciallyServiceFee`

### 3. 車機查詢階段（JobInfoExtension.cs）

檔案：`TGDS.TCS/Services/Extenstions/JobInfoExtension.cs`

- SQL 讀取 `JOB_ExecVEH.SpeciallyServiceFee`（line 57）
- 填入 `JobExInfo.SpeciallyServiceFee`（line 219-224）

### 4. 電文封裝

檔案：`x4000.cs` line 70

```csharp
rep2IVE.Body.UpdateValue(7, jobExInfo.ToJsonNetString());
```

`SpeciallyServiceFee` 在 JSON 中隨 `JobExInfo` 一起傳給車機。

## 重要提醒

- **USP_mIVE_GetJobInfo 這個 SP 不包含小費欄位**。它只回傳基本任務資訊（備註、付款方式、狀態等）。
- 小費是透過 x4000 電文第 7 欄的 JSON 傳送的，不走這個 SP。
- 乘客備註訊息由 `JobInformation.GetJobClientMemo()` 組裝，讀取 `JOB_ExecVEH` 的 `SoSweetRemind`、`CustMsg`、`ExtMsg`、`OneMsg` 等欄位。

## 關鍵檔案索引

| 檔案 | 用途 |
|------|------|
| `TGDS.WebAPI/Controllers/APP/Dispatch/Order.cs` | 下單時 NormalFee 處理 |
| `CommonDTO/WebAPI/DTO/JobOrderObj.cs` | NormalFee 欄位定義 |
| `TGDS.TCS/Services/Extenstions/JobInfoExtension.cs` | 從 DB 讀取 SpeciallyServiceFee |
| `CommonDTO/WebAPI/DTO/JobExInfo` (XML) | SpeciallyServiceFee 欄位定義 |
| `TGDS.TCS/Task/Plus/IVE/x4000.cs` | 電文封裝 |
| `TGDS.TCS/Services/Extenstions/JobInformation.cs` | 乘客備註訊息組裝 |
| `TGDS.TCS/Services/Extenstions/JobInformation_IVE8.cs` | IVE8 電文組裝 |
